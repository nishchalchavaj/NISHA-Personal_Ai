"""Small guest-side Windows Sandbox worker; no network or host credentials are provided."""

import json
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

OUTPUT_LIMIT = 64_000
PATCH_LIMIT = 1_000_000


def _bounded_read(pipe, target, exceeded):
    while True:
        block = pipe.read(8192)
        if not block:
            return
        remaining = OUTPUT_LIMIT - len(target)
        if remaining > 0:
            target.extend(block[:remaining])
        if len(block) > remaining:
            exceeded.add(True)


def _run(command, cwd, env, timeout):
    started = time.monotonic()
    process = subprocess.Popen(
        command,
        cwd=cwd,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        shell=False,
        creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        | getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    stdout = bytearray()
    stderr = bytearray()
    truncated = set()
    readers = [
        threading.Thread(target=_bounded_read, args=(process.stdout, stdout, truncated), daemon=True),
        threading.Thread(target=_bounded_read, args=(process.stderr, stderr, truncated), daemon=True),
    ]
    for reader in readers:
        reader.start()
    timed_out = False
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        try:
            subprocess.run(
                [os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "taskkill.exe"),
                 "/PID", str(process.pid), "/T", "/F"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5,
                check=False,
                shell=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except (OSError, subprocess.SubprocessError):
            pass
        if process.poll() is None:
            process.kill()
        process.wait()
    for reader in readers:
        reader.join(timeout=5)
    return {
        "exit_code": 124 if timed_out else process.returncode,
        "stdout": stdout.decode("utf-8", errors="replace"),
        "stderr": stderr.decode("utf-8", errors="replace"),
        "timed_out": timed_out,
        "output_truncated": bool(truncated),
        "duration_seconds": round(time.monotonic() - started, 3),
    }


def _guest_environment(python_executable):
    system_root = os.environ.get("SystemRoot", r"C:\Windows")
    git = r"C:\NishaTools\Git"
    python = os.path.dirname(python_executable)
    return {
        "SystemRoot": system_root,
        "WINDIR": system_root,
        "TEMP": r"C:\Windows\Temp",
        "TMP": r"C:\Windows\Temp",
        "PATH": ";".join((
            os.path.join(system_root, "System32"),
            system_root,
            os.path.join(system_root, "System32", "Wbem"),
            os.path.join(git, "cmd"),
            os.path.join(git, "mingw64", "bin"),
            os.path.join(git, "usr", "bin"),
            python,
        )),
        "PATHEXT": ".COM;.EXE;.BAT;.CMD;.VBS;.VBE;.JS;.JSE;.WSF;.WSH;.MSC",
        "PYTHONUTF8": "1",
        "PYTHONPATH": r"C:\NishaPackages",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONNOUSERSITE": "1",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": "NUL",
        "GIT_TERMINAL_PROMPT": "0",
        "GCM_INTERACTIVE": "Never",
    }


def _initialize_snapshot(cwd, env, git_exe):
    commands = (
        [git_exe, "init", "--quiet"],
        [git_exe, "add", "--force", "--all"],
        [git_exe, "-c", "user.name=Nisha Sandbox", "-c", "user.email=nisha-sandbox@localhost",
         "commit", "--quiet", "--allow-empty", "-m", "Sandbox snapshot"],
    )
    for command in commands:
        result = subprocess.run(
            command,
            cwd=cwd,
            env=env,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=90,
            check=False,
            shell=False,
        )
        if result.returncode:
            raise RuntimeError("Could not prepare the isolated project snapshot for Git diff capture.")


def _copy_project_snapshot(source, destination):
    destination.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, destination, dirs_exist_ok=True, symlinks=False)


def _capture_patch(cwd, env, git_exe, output_dir):
    add = subprocess.run(
        [git_exe, "add", "--intent-to-add", "--all"],
        cwd=cwd,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=60,
        check=False,
        shell=False,
    )
    if add.returncode:
        return False
    process = subprocess.Popen(
        [git_exe, "diff", "--binary", "--no-ext-diff", "HEAD", "--"],
        cwd=cwd,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        shell=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    patch = bytearray()
    exceeded = set()
    reader = threading.Thread(target=_bounded_patch_read, args=(process.stdout, patch, exceeded), daemon=True)
    reader.start()
    try:
        process.wait(timeout=90)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()
        return False
    reader.join(timeout=5)
    if process.returncode != 0 or exceeded:
        return bool(exceeded)
    if patch:
        (output_dir / "changes.patch").write_bytes(patch)
    return False


def _bounded_patch_read(pipe, target, exceeded):
    while True:
        block = pipe.read(8192)
        if not block:
            return
        remaining = PATCH_LIMIT - len(target)
        if remaining > 0:
            target.extend(block[:remaining])
        if len(block) > remaining:
            exceeded.add(True)


def run(request_path, output_root):
    request_path = Path(request_path)
    output_root = Path(output_root)
    request = json.loads(request_path.read_text(encoding="utf-8"))
    output = {
        "id": request["id"],
        "exit_code": 1,
        "stdout": "",
        "stderr": "",
        "timed_out": False,
        "output_truncated": False,
        "duration_seconds": 0,
        "patch_truncated": False,
    }
    started = time.monotonic()
    env = _guest_environment(request["python"])
    cwd = Path(request["project"])
    python_exe = request["python"]
    git_exe = request["git"]
    try:
        _copy_project_snapshot(Path(r"C:\NishaInput\project"), cwd)
        _initialize_snapshot(cwd, env, git_exe)
        shell = request["shell"]
        argv = request["argv"]
        if shell == "powershell":
            command = [
                os.path.join(env["SystemRoot"], "System32", "WindowsPowerShell", "v1.0", "powershell.exe"),
                "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", request["script"],
            ]
        elif shell == "cmd":
            command = [os.path.join(env["SystemRoot"], "System32", "cmd.exe"), "/d", "/s", "/c", request["script"]]
        elif shell == "python":
            command = [python_exe, *argv[1:]]
        elif shell == "git":
            command = [git_exe, *argv[1:]]
        else:
            raise ValueError("Unsupported terminal command type.")
        result = _run(command, cwd, env, request["timeout_seconds"])
        output.update(result)
        output["patch_truncated"] = _capture_patch(cwd, env, git_exe, output_root)
    except (OSError, ValueError, TypeError, KeyError, RuntimeError, subprocess.SubprocessError) as exc:
        output["stderr"] = str(exc)[:OUTPUT_LIMIT]
    output["duration_seconds"] = round(time.monotonic() - started, 3)
    result_path = output_root / request["result_name"]
    temporary = result_path.with_suffix(".tmp")
    temporary.write_text(json.dumps(output, ensure_ascii=False), encoding="utf-8")
    os.replace(temporary, result_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(run(sys.argv[1], sys.argv[2]))

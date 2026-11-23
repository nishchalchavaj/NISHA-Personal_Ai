"""Privacy-restricted Windows Sandbox execution for approved terminal commands."""

import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from threading import Event, Lock
from uuid import uuid4

from nisha.coding import SKIP_DIRS, _private_file
from nisha.errors import NishaError

MAX_PROJECT_FILES = 20_000
MAX_PROJECT_BYTES = 1_000_000_000
MAX_FILE_BYTES = 100_000_000
MAX_PATCH_BYTES = 1_000_000
MAX_RESULT_BYTES = 1_200_000
SANDBOX_MEMORY_MB = 8192
SANDBOX_START_TIMEOUT = 120
SANDBOX_LAUNCH_GRACE_SECONDS = 30
SANDBOX_SHUTDOWN_GRACE_SECONDS = 3
SANDBOX_CLEANUP_TIMEOUT = 15
POLL_SECONDS = 0.2
EXCLUDED_DIRS = SKIP_DIRS | {
    ".cache", ".codex", ".idea", ".next", ".tox", ".vscode", "browser-data",
    "coverage", "data", "env", "envs", "logs", "profiles", "venv",
}
EXCLUDED_SUFFIXES = {
    ".db", ".journal", ".kdbx", ".key", ".log", ".p12", ".pem", ".pfx",
    ".sqlite", ".sqlite3",
}


class WindowsSandboxRunner:
    """Run commands in an offline disposable guest and return only bounded output.

    The guest receives a read-only snapshot of tracked project files, read-only Python
    and Git runtimes, and one empty writable results folder. Host project files are never
    mounted writable. No network, clipboard, audio, video, printer, or GPU sharing is
    enabled. When Sandbox is unavailable, this runner refuses; it never falls back to the
    signed-in host account.
    """

    def __init__(self, data_dir, executable=None, popen=subprocess.Popen, clock=time.monotonic):
        self.data_dir = Path(data_dir).resolve()
        self.executable = Path(executable or Path(os.environ.get("WINDIR", r"C:\Windows"))
                               / "System32" / "WindowsSandbox.exe")
        self._popen = popen
        self._clock = clock
        self._lock = Lock()
        self._state_lock = Lock()
        self._cancel_event = Event()
        self._active_process = None

    @property
    def available(self):
        return os.name == "nt" and self.executable.is_file()

    def run(self, shell, argv, script, project_root, timeout):
        if not self.available:
            raise NishaError(
                "Windows Sandbox is unavailable. Enable the Windows Sandbox optional feature, "
                "restart Windows if requested, then retry. Commands are not run on the host."
            )
        if not self._lock.acquire(blocking=False):
            raise NishaError("Another NISHA Sandbox command is running. Wait and retry.")
        self._cancel_event.clear()
        job_root = None
        sandbox_process = None
        sandbox_closed = False
        launch_started = None
        guest_seen = False
        try:
            if self._sandbox_already_running():
                raise NishaError("Close the existing Windows Sandbox window before running NISHA commands.")
            jobs_root = self.data_dir / "terminal-sandbox"
            jobs_root.mkdir(parents=True, exist_ok=True)
            job_root = Path(tempfile.mkdtemp(prefix="job-", dir=jobs_root))
            input_root = job_root / "input"
            project_copy = input_root / "project"
            output_root = job_root / "output"
            input_root.mkdir()
            output_root.mkdir()
            staged = self._stage_project(Path(project_root).resolve(), project_copy)
            tool_paths = self._stage_tool_mappings(jobs_root)
            request_id = uuid4().hex
            result_name = f"result-{request_id}.json"
            request = {
                "id": request_id,
                "shell": shell,
                "argv": list(argv),
                "script": script,
                "project": r"C:\NishaWork",
                "timeout_seconds": max(1, min(int(timeout), 300)),
                "result_name": result_name,
                "python": tool_paths["python_guest"],
                "git": tool_paths["git_guest"],
            }
            (input_root / "request.json").write_text(
                json.dumps(request, ensure_ascii=False), encoding="utf-8"
            )
            worker = Path(__file__).with_name("sandbox_worker.py")
            shutil.copyfile(worker, input_root / "worker.py")
            (input_root / "bootstrap.ps1").write_text(
                "$ErrorActionPreference = 'Stop'\n"
                "$python = '" + tool_paths["python_guest"] + "'\n"
                "try { & $python 'C:\\NishaInput\\worker.py' 'C:\\NishaInput\\request.json' 'C:\\NishaOutput' } "
                "finally { shutdown.exe /s /t 2 /f | Out-Null }\n",
                encoding="utf-8",
            )
            config_path = job_root / "run.wsb"
            self._write_configuration(config_path, input_root, output_root, tool_paths)
            sandbox_process = self._popen(
                [str(self.executable), str(config_path)],
                cwd=str(job_root),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                shell=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            launch_started = self._clock()
            with self._state_lock:
                self._active_process = sandbox_process
            result_path = output_root / result_name
            deadline = self._clock() + SANDBOX_START_TIMEOUT + request["timeout_seconds"] + 30
            while self._clock() < deadline:
                if self._cancel_event.is_set():
                    self._close_sandbox(sandbox_process)
                    raise NishaError("The approved Windows Sandbox command was stopped.")
                if result_path.is_file() and not result_path.is_symlink():
                    break
                if sandbox_process.poll() is not None:
                    guest_present = self._sandbox_process_present()
                    guest_seen = guest_seen or guest_present
                    if not guest_present and (
                        guest_seen or self._clock() - launch_started >= SANDBOX_LAUNCH_GRACE_SECONDS
                    ):
                        if self._cancel_event.is_set():
                            raise NishaError("The approved Windows Sandbox command was stopped.")
                        raise NishaError("Windows Sandbox closed before returning a command receipt.")
                time.sleep(POLL_SECONDS)
            else:
                self._close_sandbox(sandbox_process)
                sandbox_closed = True
                raise NishaError("Windows Sandbox did not return a result before the execution deadline.")
            if result_path.stat().st_size > MAX_RESULT_BYTES:
                raise NishaError("Windows Sandbox returned an oversized result; it was discarded.")
            result = json.loads(result_path.read_text(encoding="utf-8"))
            validated = self._validate_result(result, staged, output_root, self.data_dir, request_id)
            if self._sandbox_process_present():
                time.sleep(SANDBOX_SHUTDOWN_GRACE_SECONDS)
                self._close_sandbox(sandbox_process)
            sandbox_closed = True
            return validated
        except NishaError:
            raise
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            raise NishaError("The isolated Windows Sandbox command failed safely.") from exc
        finally:
            if sandbox_process is not None and not sandbox_closed and self._sandbox_process_present():
                self._close_sandbox(sandbox_process)
            if job_root is not None:
                self._remove_job_root(job_root)
            with self._state_lock:
                self._active_process = None
            self._cancel_event.clear()
            self._lock.release()

    def stop(self):
        self._cancel_event.set()
        with self._state_lock:
            process = self._active_process
        if process is None:
            return {"status": "no_active_sandbox_command"}
        self._close_sandbox(process)
        return {"status": "stopping_sandbox_command"}

    @staticmethod
    def _remove_job_root(job_root):
        deadline = time.monotonic() + SANDBOX_CLEANUP_TIMEOUT
        while True:
            try:
                shutil.rmtree(job_root)
                return
            except FileNotFoundError:
                return
            except OSError as exc:
                if time.monotonic() >= deadline:
                    raise NishaError(
                        "Windows Sandbox closed, but its temporary job files remained locked."
                    ) from exc
                time.sleep(POLL_SECONDS)

    @staticmethod
    def _sandbox_already_running():
        return WindowsSandboxRunner._sandbox_process_present()

    @staticmethod
    def _sandbox_process_present():
        try:
            for image in (b"WindowsSandbox.exe", b"WindowsSandboxRemoteSession.exe"):
                result = subprocess.run(
                    ["tasklist.exe", "/FI", f"IMAGENAME eq {image.decode()}", "/FO", "CSV", "/NH"],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    timeout=5,
                    check=False,
                    shell=False,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                if image in result.stdout:
                    return True
            return False
        except (OSError, subprocess.SubprocessError):
            return True  # Fail closed if the single-instance check cannot be made.

    @staticmethod
    def _stage_project(source, destination):
        source = Path(source).resolve()
        destination = Path(destination)
        destination.mkdir(parents=True)
        git = shutil.which("git")
        files = None
        if git:
            try:
                listed = subprocess.run(
                    [git, "-C", str(source), "ls-files", "--cached", "-z"],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    timeout=10,
                    check=False,
                    shell=False,
                )
                if listed.returncode == 0:
                    files = [Path(item) for item in listed.stdout.decode("utf-8", "surrogateescape").split("\0") if item]
            except (OSError, subprocess.SubprocessError):
                files = None
        if not files:
            files = []
            for current, dirs, names in os.walk(source, followlinks=False):
                current_path = Path(current)
                dirs[:] = sorted(
                    name for name in dirs
                    if name.casefold() not in EXCLUDED_DIRS
                    and not (current_path / name).is_symlink()
                )
                files.extend((current_path / name).relative_to(source) for name in names)
        count = 0
        total_bytes = 0
        skipped_private = 0
        for relative in files:
            if relative.is_absolute() or ".." in relative.parts or any(
                part.casefold() in EXCLUDED_DIRS for part in relative.parts
            ):
                continue
            path = source / relative
            if path.is_symlink() or _private_file(path) or path.suffix.casefold() in EXCLUDED_SUFFIXES:
                skipped_private += 1
                continue
            try:
                resolved = path.resolve(strict=True)
                if not resolved.is_relative_to(source) or not resolved.is_file():
                    continue
                size = resolved.stat().st_size
            except OSError:
                continue
            if size > MAX_FILE_BYTES:
                raise NishaError(f"Sandbox snapshot refused an oversized project file: {relative}")
            count += 1
            total_bytes += size
            if count > MAX_PROJECT_FILES or total_bytes > MAX_PROJECT_BYTES:
                raise NishaError("Sandbox snapshot exceeded its file-count or 1 GB size limit.")
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(resolved, target)
        if count == 0:
            raise NishaError("The project snapshot contains no eligible files.")
        return {"file_count": count, "bytes": total_bytes, "excluded_private_files": skipped_private}

    @staticmethod
    def _stage_tool_mappings(cache_root):
        python_venv = Path(sys.prefix).resolve()
        python_base = Path(sys.base_prefix).resolve()
        package_root = python_venv / "Lib" / "site-packages"
        if not (python_base / "python.exe").is_file() or not package_root.is_dir():
            raise NishaError("A read-only Python runtime could not be prepared for Windows Sandbox.")
        python_tag = f"Python{sys.version_info.major}{sys.version_info.minor}"
        python_copy = cache_root / "toolchain" / python_tag
        if not (python_copy / "python.exe").is_file():
            python_copy.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(
                python_base,
                python_copy,
                ignore=shutil.ignore_patterns(
                    "Doc", "include", "Scripts", "Tools", "tcl", "share", "site-packages", "__pycache__"
                ),
                dirs_exist_ok=True,
            )
        if not (python_copy / "python.exe").is_file():
            raise NishaError("A local read-only Python runtime could not be staged for Windows Sandbox.")
        git_exe = shutil.which("git")
        if not git_exe:
            raise NishaError("Git is required to snapshot project changes inside Windows Sandbox.")
        git_exe = Path(git_exe).resolve()
        git_root = git_exe.parent.parent
        git_guest = Path(r"C:\NishaTools\Git") / git_exe.relative_to(git_root)
        return {
            "python_guest": r"C:\NishaTools\Python\python.exe",
            "python_runtime": python_copy,
            "python_packages": package_root,
            "git_root": git_root,
            "git_host_exe": git_exe,
            "git_guest": str(git_guest),
        }

    @staticmethod
    def _write_configuration(path, input_root, output_root, tools):
        root = ET.Element("Configuration")
        for tag, value in (
            ("vGPU", "Disable"),
            ("Networking", "Disable"),
            ("AudioInput", "Disable"),
            ("VideoInput", "Disable"),
            ("ClipboardRedirection", "Disable"),
            ("PrinterRedirection", "Disable"),
            ("ProtectedClient", "Enable"),
            ("MemoryInMB", str(SANDBOX_MEMORY_MB)),
        ):
            ET.SubElement(root, tag).text = value
        mapped = ET.SubElement(root, "MappedFolders")
        mappings = [
            (input_root, Path(r"C:\NishaInput"), True),
            (output_root, Path(r"C:\NishaOutput"), False),
            (tools["python_runtime"], Path(r"C:\NishaTools\Python"), True),
            (tools["python_packages"], Path(r"C:\NishaPackages"), True),
            (tools["git_root"], Path(r"C:\NishaTools\Git"), True),
        ]
        for host, guest, read_only in mappings:
            entry = ET.SubElement(mapped, "MappedFolder")
            ET.SubElement(entry, "HostFolder").text = str(host)
            ET.SubElement(entry, "SandboxFolder").text = str(guest)
            ET.SubElement(entry, "ReadOnly").text = str(read_only).lower()
        logon = ET.SubElement(root, "LogonCommand")
        ET.SubElement(logon, "Command").text = (
            "powershell.exe -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass "
            "-File C:\\NishaInput\\bootstrap.ps1"
        )
        ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)

    @staticmethod
    def _validate_result(result, staged, output_root, data_dir, expected_id):
        required = {"exit_code", "stdout", "stderr", "timed_out", "output_truncated", "duration_seconds"}
        if not isinstance(result, dict) or not required.issubset(result):
            raise NishaError("Windows Sandbox returned an invalid command receipt.")
        if (
            result.get("id") != expected_id
            or not re.fullmatch(r"[0-9a-f]{32}", expected_id)
            or isinstance(result["exit_code"], bool)
            or not isinstance(result["exit_code"], int)
            or not isinstance(result["stdout"], str)
            or not isinstance(result["stderr"], str)
            or not isinstance(result["timed_out"], bool)
            or not isinstance(result["output_truncated"], bool)
            or not isinstance(result["duration_seconds"], (int, float))
            or isinstance(result["duration_seconds"], bool)
            or not math.isfinite(result["duration_seconds"])
            or result["duration_seconds"] < 0
        ):
            raise NishaError("Windows Sandbox returned a malformed command receipt.")
        patch_source = output_root / "changes.patch"
        patch_path = None
        if patch_source.is_file() and not patch_source.is_symlink():
            size = patch_source.stat().st_size
            if size <= MAX_PATCH_BYTES:
                patch_destination = data_dir / "reports" / "terminal-patches" / f"{expected_id}.patch"
                patch_destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(patch_source, patch_destination)
                patch_path = str(patch_destination)
        return {
            **result,
            "stdout": result["stdout"][:64_000],
            "stderr": result["stderr"][:64_000],
            "output_truncated": bool(result["output_truncated"]),
            "snapshot": staged,
            "changes_patch_path": patch_path,
            "isolation": {
                "sandbox": "Windows Sandbox",
                "network": False,
                "clipboard": False,
                "host_project_read_only_snapshot": True,
                "host_python_and_git_read_only": True,
                "host_user_profile_or_credentials_mapped": False,
            },
        }

    @staticmethod
    def _close_sandbox(process):
        try:
            process.terminate()
            process.wait(timeout=5)
        except (OSError, subprocess.SubprocessError):
            try:
                process.kill()
            except OSError:
                pass
        # The launcher and the packaged remote-session app have separate lifetimes.
        for image in ("WindowsSandbox.exe", "WindowsSandboxRemoteSession.exe"):
            try:
                subprocess.run(
                    ["taskkill.exe", "/IM", image, "/T", "/F"],
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

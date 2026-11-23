import json
import os
import subprocess
import sys
import xml.etree.ElementTree as ET
from io import BytesIO
from pathlib import Path
from threading import Event, Thread
from time import monotonic, sleep

import pytest

from nisha.errors import NishaError
from nisha.sandbox import WindowsSandboxRunner
from nisha.sandbox_worker import _bounded_patch_read, _copy_project_snapshot, _run


class FinishedProcess:
    def poll(self):
        return 0

    def terminate(self):
        pass

    def kill(self):
        pass

    def wait(self, timeout=None):
        return 0


class ActiveProcess:
    def __init__(self):
        self.started = Event()
        self.stopped = Event()

    def poll(self):
        return 1 if self.stopped.is_set() else None

    def terminate(self):
        self.stopped.set()

    def kill(self):
        self.stopped.set()

    def wait(self, timeout=None):
        self.stopped.set()
        return 1


def test_sandbox_runs_only_offline_with_minimal_readonly_inputs_and_local_patch(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    (project / "src").mkdir()
    (project / "src" / "app.py").write_text("print('before')\n", encoding="utf-8")
    subprocess.run(["git", "init", "--quiet"], cwd=project, check=True, shell=False)
    subprocess.run(["git", "add", "src/app.py"], cwd=project, check=True, shell=False)
    (project / ".env").write_text("PASSWORD=do-not-stage\n", encoding="utf-8")
    (project / "trader").mkdir()
    (project / "trader" / "private.py").write_text("sensitive\n", encoding="utf-8")
    sandbox_exe = tmp_path / "WindowsSandbox.exe"
    sandbox_exe.write_bytes(b"fixture")
    captured = {}

    def fake_popen(command, **kwargs):
        config = ET.parse(command[1]).getroot()
        captured["config"] = config
        folders = config.find("MappedFolders").findall("MappedFolder")
        mapped = {
            node.findtext("SandboxFolder"): Path(node.findtext("HostFolder"))
            for node in folders
        }
        input_root = mapped[r"C:\NishaInput"]
        output_root = mapped[r"C:\NishaOutput"]
        captured["project_files"] = sorted(
            str(path.relative_to(input_root / "project"))
            for path in (input_root / "project").rglob("*")
            if path.is_file()
        )
        request = json.loads((input_root / "request.json").read_text(encoding="utf-8"))
        captured["request"] = request
        (output_root / "changes.patch").write_text("diff --git a/src/app.py b/src/app.py\n", encoding="utf-8")
        (output_root / request["result_name"]).write_text(
            json.dumps({
                "id": request["id"],
                "exit_code": 0,
                "stdout": "sandbox-ok",
                "stderr": "",
                "timed_out": False,
                "output_truncated": False,
                "duration_seconds": 0.1,
                "patch_truncated": False,
            }),
            encoding="utf-8",
        )
        return FinishedProcess()

    runner = WindowsSandboxRunner(tmp_path / "data", executable=sandbox_exe, popen=fake_popen)
    result = runner.run("python", ("python", "-c", "print('ok')"), None, project, 10)

    config = captured["config"]
    assert config.findtext("Networking") == "Disable"
    assert config.findtext("ClipboardRedirection") == "Disable"
    assert config.findtext("AudioInput") == "Disable"
    assert config.findtext("VideoInput") == "Disable"
    assert config.findtext("PrinterRedirection") == "Disable"
    assert config.findtext("vGPU") == "Disable"
    assert config.findtext("ProtectedClient") == "Enable"
    mappings = config.find("MappedFolders").findall("MappedFolder")
    assert sum(node.findtext("ReadOnly") == "false" for node in mappings) == 1
    python_mount = next(node for node in mappings if node.findtext("SandboxFolder") == r"C:\NishaTools\Python")
    python_host = Path(python_mount.findtext("HostFolder"))
    assert python_host.parent.name == "toolchain"
    assert python_host.name.startswith("Python")
    assert captured["request"]["python"].rsplit("\\", 1)[0] == python_mount.findtext("SandboxFolder")
    assert captured["project_files"] == ["src\\app.py"]
    assert result["stdout"] == "sandbox-ok"
    assert result["isolation"]["network"] is False
    assert result["isolation"]["host_user_profile_or_credentials_mapped"] is False
    assert Path(result["changes_patch_path"]).read_text(encoding="utf-8").startswith("diff --git")
    assert list((tmp_path / "data" / "terminal-sandbox").glob("job-*")) == []


def test_sandbox_unavailable_fails_closed_without_running_host_command(tmp_path):
    runner = WindowsSandboxRunner(tmp_path / "data", executable=tmp_path / "missing.exe")
    with pytest.raises(NishaError, match="Commands are not run on the host"):
        runner.run("powershell", (), "Write-Output host", tmp_path, 1)


def test_sandbox_rejects_result_receipt_from_another_job(tmp_path):
    result = {
        "id": "f" * 32,
        "exit_code": 0,
        "stdout": "",
        "stderr": "",
        "timed_out": False,
        "output_truncated": False,
        "duration_seconds": 0.1,
    }
    with pytest.raises(NishaError, match="malformed command receipt"):
        WindowsSandboxRunner._validate_result(
            result, {}, tmp_path / "output", tmp_path / "data", "a" * 32
        )


def test_emergency_stop_terminates_active_sandbox_job(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    (project / "main.py").write_text("print('fixture')\n", encoding="utf-8")
    sandbox_exe = tmp_path / "WindowsSandbox.exe"
    sandbox_exe.write_bytes(b"fixture")
    process = ActiveProcess()

    def fake_popen(*_args, **_kwargs):
        process.started.set()
        return process

    runner = WindowsSandboxRunner(
        tmp_path / "data", executable=sandbox_exe, popen=fake_popen
    )
    runner._sandbox_process_present = lambda: False
    runner._stage_tool_mappings = lambda _cache: {
        "python_guest": r"C:\NishaTools\Python\python.exe",
        "python_runtime": tmp_path / "python",
        "python_packages": tmp_path / "packages",
        "git_root": tmp_path / "git",
        "git_host_exe": tmp_path / "git" / "bin" / "git.exe",
        "git_guest": r"C:\NishaTools\Git\bin\git.exe",
    }
    failures = []

    def execute():
        try:
            runner.run("python", ("python", "-c", "pass"), None, project, 10)
        except NishaError as exc:
            failures.append(str(exc))

    worker = Thread(target=execute)
    worker.start()
    assert process.started.wait(5), failures
    deadline = monotonic() + 5
    while runner._active_process is None and monotonic() < deadline:
        sleep(0.01)
    assert runner._active_process is process
    assert runner.stop()["status"] == "stopping_sandbox_command"
    worker.join(timeout=10)
    assert worker.is_alive() is False
    assert failures == ["The approved Windows Sandbox command was stopped."]


def test_guest_copies_snapshot_into_its_private_working_disk(tmp_path):
    readonly_input = tmp_path / "input" / "project"
    readonly_input.mkdir(parents=True)
    (readonly_input / "main.py").write_text("print('isolated')\n", encoding="utf-8")
    guest_workspace = tmp_path / "guest" / "NishaWork"
    _copy_project_snapshot(readonly_input, guest_workspace)
    (guest_workspace / "main.py").write_text("print('changed in guest')\n", encoding="utf-8")
    assert (readonly_input / "main.py").read_text(encoding="utf-8") == "print('isolated')\n"


@pytest.mark.parametrize("size", [0, 1, 63_999, 64_000, 64_001, 2_000_000])
def test_guest_command_capture_is_bounded_for_small_and_hostile_output(tmp_path, size):
    code = f"import sys; sys.stdout.write('x' * {size}); sys.stderr.write('y' * {size})"
    result = _run(
        [sys.executable, "-c", code],
        tmp_path,
        {"SystemRoot": os.environ["SystemRoot"]},
        10,
    )
    assert result["exit_code"] == 0
    assert len(result["stdout"]) == min(size, 64_000)
    assert len(result["stderr"]) == min(size, 64_000)
    assert result["output_truncated"] is (size > 64_000)


def test_guest_command_timeout_returns_bounded_failure(tmp_path):
    result = _run(
        [sys.executable, "-c", "import time; time.sleep(20)"],
        tmp_path,
        {"SystemRoot": os.environ["SystemRoot"]},
        1,
    )
    assert result["timed_out"] is True
    assert result["exit_code"] == 124


def test_patch_capture_caps_large_changes_without_persisting_partial_patch():
    captured = bytearray()
    exceeded = set()
    reader = Thread(target=_bounded_patch_read, args=(BytesIO(b"z" * 1_000_001), captured, exceeded))
    reader.start()
    reader.join(timeout=5)
    assert reader.is_alive() is False
    assert len(captured) == 1_000_000
    assert exceeded == {True}


def test_terminal_prepare_refuses_host_fallback_when_sandbox_missing(core, tmp_path):
    from nisha.terminal import TerminalService

    project = tmp_path / "project"
    project.mkdir()
    core.connections.save(json.dumps({
        "projects": [{"name": "No Sandbox", "folder": str(project)}],
        "default_project": "No Sandbox",
    }))
    core.terminal = TerminalService(
        core.connections,
        tmp_path / "data",
        core.store,
        sandbox=WindowsSandboxRunner(tmp_path / "data", executable=tmp_path / "missing.exe"),
    )
    with pytest.raises(NishaError, match="Commands are not run on the host"):
        core.terminal.prepare("python", "No Sandbox", args=["-c", "print('must-not-run')"])

import shutil
import subprocess
import sys
from time import monotonic

import pytest

from nisha.core import NishaCore
from nisha.errors import ModelUnavailable
from nisha.settings import ModelProfile, Settings
from nisha.storage import Store


class FakeGateway:
    def __init__(self):
        self.calls = []
        self.fail = False
        self.summary_fail = False

    def stream(self, alias, messages):
        self.calls.append((alias, messages))
        yield "Hello "
        if self.fail:
            raise ModelUnavailable("Simulated outage")
        yield "Nishchal."

    def complete(self, alias, messages):
        if self.summary_fail:
            raise ModelUnavailable("Simulated summary outage")
        return "The user is developing NISHA."

    def close(self):
        pass

    def headers(self):
        return {}


class FixtureSandboxRunner:
    """Test-only process double; production code always requires Windows Sandbox."""

    available = True

    def stop(self):
        return {"status": "no_active_sandbox_command"}

    def run(self, shell, argv, script, project_root, timeout):
        command = list(argv)
        if shell == "python":
            command[0] = sys.executable
        elif shell == "git":
            command[0] = shutil.which("git")
        started = monotonic()
        process = subprocess.Popen(
            command,
            cwd=project_root,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
        )
        timed_out = False
        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            process.kill()
            stdout, stderr = process.communicate()
        return {
            "exit_code": 124 if timed_out else process.returncode,
            "stdout": stdout[:64_000].decode("utf-8", errors="replace"),
            "stderr": stderr[:64_000].decode("utf-8", errors="replace"),
            "timed_out": timed_out,
            "output_truncated": len(stdout) > 64_000 or len(stderr) > 64_000,
            "duration_seconds": monotonic() - started,
            "isolation": {"sandbox": "test-only process double", "network": False},
            "snapshot": {"file_count": 0, "bytes": 0},
            "changes_patch_path": None,
            "patch_truncated": False,
        }


@pytest.fixture
def core(tmp_path):
    settings = Settings(
        instant_smalltalk=False,  # Most unit tests exercise generated-answer paths.
        background_actions=False,  # UI tests explicitly opt in with mocked desktop actions.
        external_tasks_enabled=True,
        data_dir=tmp_path,
        models={
            "local_fast": ModelProfile(
                model="ollama_chat/llama3.2", local=True, context_window=4096, max_output=256
            ),
            "cloud": ModelProfile(
                model="openai/test", local=False, context_window=4096, max_output=256
            ),
        },
        recent_exchanges=2,
    )
    instance = NishaCore(settings, FakeGateway(), Store(tmp_path / "test.sqlite3"))
    instance.terminal.sandbox = FixtureSandboxRunner()
    return instance

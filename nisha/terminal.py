"""Approval-gated Windows Sandbox terminal actions with bounded local results."""

import json
import os
import re
import shutil
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from threading import Lock, RLock
from time import monotonic
from uuid import uuid4

from nisha.coding import redact_sensitive_text
from nisha.errors import NishaError
from nisha.sandbox import WindowsSandboxRunner

MAX_OUTPUT_BYTES = 64_000
MAX_ARGS = 32
MAX_ARG_CHARS = 4096
MAX_COMMAND_CHARS = 12_000
MAX_RUNTIME_SECONDS = 300
APPROVAL_SECONDS = 120
SECRET_ARGUMENT = re.compile(
    r"(?i)(?:api[_-]?key|password|passwd|client[_-]?secret|access[_-]?token|credential)\s*[:=]\s*[^\s]+"
)
BLOCKED_COMMAND = re.compile(
    r"(?i)(?:\b(?:format(?:\.com)?|diskpart|bcdedit|shutdown|restart-computer|stop-computer|"
    r"clear-disk|initialize-disk|remove-partition|set-executionpolicy|reg\s+delete)\b|"
    r"(?:^|[\s;&|])(?:rm|del|erase|rmdir)\s+[^\r\n]*(?:\\\s*$|/s\s+/q)|"
    r"(?:^|\s)-enc(?:odedcommand)?(?:\s|$))"
)
NETWORK_COMMANDS = {"push", "pull", "fetch", "clone", "submodule"}
CRITICAL_GIT = {"reset", "clean", "filter-branch", "gc", "prune"}


@dataclass(frozen=True)
class PendingCommand:
    shell: str
    argv: tuple[str, ...]
    script: str | None
    project: str
    working_directory: str
    digest: str
    risk: str
    expires: float


@dataclass(frozen=True)
class TerminalReceipt:
    shell: str
    command: tuple[str, ...]
    working_directory: str
    start_time: str
    end_time: str
    duration_seconds: float
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool
    output_truncated: bool
    isolation: dict
    snapshot: dict
    changes_patch_path: str | None
    patch_truncated: bool
    approved: bool


class TerminalService:
    """Run explicitly approved commands in configured project folders only.

    Production commands run in an offline Windows Sandbox over a sanitized, read-only
    project snapshot. This service fails closed when Windows Sandbox is unavailable.
    """

    def __init__(self, connections, data_dir, store=None, timeout=MAX_RUNTIME_SECONDS, sandbox=None):
        self.connections = connections
        self.data_dir = Path(data_dir).resolve()
        self.store = store
        self.timeout = max(1, min(int(timeout), MAX_RUNTIME_SECONDS))
        self.sandbox = sandbox or WindowsSandboxRunner(self.data_dir)
        self.pending = {}
        self.lock = RLock()
        self.log_lock = Lock()
        self.receipt_log = self.data_dir / "reports" / "terminal-commands.jsonl"

    def _project(self, name):
        config = self.connections.load()
        project = next(
            (item for item in config.projects if item.name.casefold() == name.casefold()
             or any(alias.casefold() == name.casefold() for alias in item.aliases)),
            None,
        )
        if project is None:
            raise NishaError("Terminal commands require a configured project name.")
        root = Path(project.folder).resolve()
        if not root.is_dir():
            raise NishaError("The configured project folder is unavailable.")
        return project, root

    @staticmethod
    def _powerShell_executable():
        system_root = Path(os.environ.get("SYSTEMROOT", r"C:\Windows"))
        windows_powershell = system_root / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
        if windows_powershell.is_file():
            return str(windows_powershell)
        executable = shutil.which("pwsh")
        if executable:
            return executable
        raise NishaError("PowerShell is unavailable.")

    def _command(self, shell, args, script):
        if shell not in {"powershell", "cmd", "python", "git"}:
            raise NishaError("Choose PowerShell, CMD, Python, or Git.")
        if (args is None) == (script is None):
            raise NishaError("Supply either an argument list or a shell script, not both.")
        if args is not None:
            if not isinstance(args, list) or not 1 <= len(args) <= MAX_ARGS:
                raise NishaError(f"Commands require 1–{MAX_ARGS} arguments.")
            if any(not isinstance(arg, str) or len(arg) > MAX_ARG_CHARS or "\x00" in arg for arg in args):
                raise NishaError("Command arguments must be text up to 4096 characters each.")
            if shell in {"powershell", "cmd"}:
                raise NishaError("PowerShell and CMD require a script string.")
            if shell == "python":
                argv = ["python", *args]
            else:
                subcommand = args[0].casefold()
                if any(
                    arg.casefold() in {"-c", "--git-dir", "--work-tree", "--exec-path"}
                    or arg.casefold().startswith(("--git-dir=", "--work-tree=", "--exec-path=", "--config-env"))
                    for arg in args
                ):
                    raise NishaError("Git directory/configuration overrides are blocked.")
                if subcommand in CRITICAL_GIT or any(arg.casefold() in {"--hard", "-fdx", "--force"} for arg in args):
                    raise NishaError("This destructive Git command is blocked by NISHA's terminal policy.")
                if subcommand in NETWORK_COMMANDS:
                    raise NishaError("Git network commands are blocked; NISHA Sandbox runs offline.")
                executable = shutil.which("git")
                if not executable:
                    raise NishaError("Git is unavailable.")
                argv = ["git", *args]
        else:
            if shell not in {"powershell", "cmd"} or not isinstance(script, str):
                raise NishaError("Shell scripts are available only for PowerShell or CMD.")
            if not 1 <= len(script.strip()) <= MAX_COMMAND_CHARS or "\x00" in script:
                raise NishaError("Shell scripts must contain 1–12000 characters.")
            if BLOCKED_COMMAND.search(script):
                raise NishaError("This destructive or policy-bypass command is blocked.")
            if SECRET_ARGUMENT.search(script):
                raise NishaError("Do not put credentials in a command; use a configured credential store.")
            if shell == "powershell":
                argv = [self._powerShell_executable(), "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", script]
            else:
                executable = os.environ.get("COMSPEC", r"C:\Windows\System32\cmd.exe")
                if not Path(executable).is_file():
                    raise NishaError("CMD is unavailable.")
                argv = [executable, "/d", "/s", "/c", script]
        if sum(len(part) for part in argv) > MAX_COMMAND_CHARS + MAX_ARGS * MAX_ARG_CHARS:
            raise NishaError("The command exceeds the supported total size.")
        if any(SECRET_ARGUMENT.search(part) for part in argv):
            raise NishaError("Do not put credentials in command arguments; use a configured credential store.")
        return argv

    @staticmethod
    def _risk(shell, argv):
        subcommand = Path(argv[1]).name.casefold() if shell == "git" and len(argv) > 1 else ""
        if subcommand in NETWORK_COMMANDS:
            return "level_3_external"
        if shell in {"powershell", "cmd"}:
            return "level_2_shell"
        if shell == "python" and any(arg in {"-c", "-m"} for arg in argv[1:]):
            return "level_2_code"
        return "level_1_development"

    def prepare(self, shell, project_name, args=None, script=None):
        if not self.sandbox.available:
            raise NishaError(
                "Windows Sandbox is unavailable. Enable the Windows Sandbox optional feature, "
                "restart Windows if requested, then retry. Commands are not run on the host."
            )
        argv = self._command(shell, args, script)
        project, root = self._project(project_name)
        risk = self._risk(shell, argv)
        approval_id = uuid4().hex
        digest = sha256("\0".join(argv).encode("utf-8")).hexdigest()
        pending = PendingCommand(
            shell=shell,
            argv=tuple(argv),
            script=script,
            project=project.name,
            working_directory=str(root),
            digest=digest,
            risk=risk,
            expires=monotonic() + APPROVAL_SECONDS,
        )
        with self.lock:
            self.pending = {key: item for key, item in self.pending.items() if item.expires > monotonic()}
            self.pending[approval_id] = pending
        if self.store:
            self.store.audit("terminal_prepare", risk)
        return {
            "status": "approval_required",
            "approval_id": approval_id,
            "shell": shell,
            "command": list(pending.argv),
            "project": project.name,
            "working_directory": str(root),
            "risk": risk,
            "requires_confirmation": True,
            "expires_in_seconds": APPROVAL_SECONDS,
            "limits": {
                "timeout_seconds": self.timeout,
                "sandbox_memory_bytes": 8192 * 1024 * 1024,
                "stdout_stderr_bytes_each": MAX_OUTPUT_BYTES,
                "network": "disabled",
                "clipboard": "disabled",
                "host_project": "read-only sanitized tracked-file snapshot",
                "host_user_profile_or_credentials": "not mapped",
                "changes": "sandbox edits are returned as a local patch for separate review",
            },
        }

    def execute(self, approval_id, approved):
        with self.lock:
            pending = self.pending.pop(approval_id, None)
        if not pending or pending.expires < monotonic():
            raise NishaError("Terminal approval expired or was already used. Prepare the command again.")
        if approved is not True:
            if self.store:
                self.store.audit("terminal_execute", "cancelled")
            return {"status": "cancelled"}
        _project, root = self._project(pending.project)
        if str(root) != pending.working_directory:
            raise NishaError("The project directory changed after command review. Prepare again.")
        if sha256("\0".join(pending.argv).encode("utf-8")).hexdigest() != pending.digest:
            raise NishaError("The command changed after review. Prepare again.")
        receipt = self._run(pending, root)
        if self.store:
            self.store.audit("terminal_execute", "timed_out" if receipt.timed_out else str(receipt.exit_code))
        return {"status": "completed", **asdict(receipt)}

    def _run(self, pending, root):
        start = datetime.now(UTC)
        started = monotonic()
        result = self.sandbox.run(
            pending.shell, pending.argv, pending.script, root, self.timeout
        )
        end = datetime.now(UTC)
        receipt = TerminalReceipt(
            shell=pending.shell,
            command=tuple(redact_sensitive_text(part) for part in pending.argv),
            working_directory=str(root),
            start_time=start.isoformat(),
            end_time=end.isoformat(),
            duration_seconds=round(max(monotonic() - started, float(result.get("duration_seconds", 0))), 3),
            exit_code=int(result["exit_code"]),
            stdout=redact_sensitive_text(str(result["stdout"]))[:MAX_OUTPUT_BYTES],
            stderr=redact_sensitive_text(str(result["stderr"]))[:MAX_OUTPUT_BYTES],
            timed_out=bool(result["timed_out"]),
            output_truncated=bool(result["output_truncated"]),
            isolation=dict(result["isolation"]),
            snapshot=dict(result["snapshot"]),
            changes_patch_path=result.get("changes_patch_path"),
            patch_truncated=bool(result.get("patch_truncated", False)),
            approved=True,
        )
        self.receipt_log.parent.mkdir(parents=True, exist_ok=True)
        with self.log_lock, self.receipt_log.open("a", encoding="utf-8") as log:
            log.write(json.dumps(asdict(receipt), ensure_ascii=False) + "\n")
        return receipt

    def stop(self):
        result = self.sandbox.stop()
        if self.store:
            self.store.audit("terminal_stop", result["status"])
        return result

    def read_patch(self, patch_id):
        if not re.fullmatch(r"[0-9a-f]{32}", patch_id or ""):
            raise NishaError("The terminal patch id is invalid.")
        path = self.data_dir / "reports" / "terminal-patches" / f"{patch_id}.patch"
        try:
            if path.is_symlink() or not path.is_file() or path.stat().st_size > 1_000_000:
                raise NishaError("The terminal patch is unavailable or exceeds its size limit.")
            patch = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise NishaError("The terminal patch is unavailable.") from exc
        return {"patch_id": patch_id, "patch": redact_sensitive_text(patch)}

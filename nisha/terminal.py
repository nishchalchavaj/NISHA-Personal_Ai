"""Approval-gated Windows terminal actions with bounded output and process resources."""

import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from threading import Lock, RLock, Thread
from time import monotonic
from uuid import uuid4

from nisha.coding import redact_sensitive_text
from nisha.errors import NishaError

MAX_OUTPUT_BYTES = 64_000
MAX_ARGS = 32
MAX_ARG_CHARS = 4096
MAX_COMMAND_CHARS = 12_000
MAX_RUNTIME_SECONDS = 300
MAX_PROCESS_MEMORY = 2 * 1024 * 1024 * 1024
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
    process_job_limits: dict
    approved: bool


class TerminalService:
    """Run explicitly approved commands in configured project folders only.

    Windows Job Objects bound process lifetime/resources and kill child processes when the
    job closes. They do not restrict filesystem or network access; this service is not an
    AppContainer or Windows Sandbox.
    """

    def __init__(self, connections, data_dir, store=None, timeout=MAX_RUNTIME_SECONDS):
        self.connections = connections
        self.data_dir = Path(data_dir).resolve()
        self.store = store
        self.timeout = max(1, min(int(timeout), MAX_RUNTIME_SECONDS))
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
                argv = [sys.executable, *args]
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
                executable = shutil.which("git")
                if not executable:
                    raise NishaError("Git is unavailable.")
                argv = [executable, *args]
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
        argv = self._command(shell, args, script)
        project, root = self._project(project_name)
        risk = self._risk(shell, argv)
        approval_id = uuid4().hex
        digest = sha256("\0".join(argv).encode("utf-8")).hexdigest()
        pending = PendingCommand(
            shell=shell,
            argv=tuple(argv),
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
                "process_memory_bytes": MAX_PROCESS_MEMORY,
                "stdout_stderr_bytes_each": MAX_OUTPUT_BYTES,
                "filesystem_and_network_isolation": "not provided; command runs as the signed-in user",
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
        environment = {
            key: os.environ[key]
            for key in (
                "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "PATH", "USERPROFILE",
                "LOCALAPPDATA", "APPDATA", "PROGRAMDATA", "COMSPEC", "PATHEXT",
            ) if key in os.environ
        }
        environment.update({"PYTHONUTF8": "1", "PYTHONDONTWRITEBYTECODE": "1"})
        import win32con

        flags = (
            getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            | getattr(subprocess, "CREATE_NO_WINDOW", 0)
            | win32con.CREATE_SUSPENDED
        )
        process = subprocess.Popen(
            pending.argv,
            cwd=root,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
            creationflags=flags,
        )
        job_handle = None
        output = {"stdout": bytearray(), "stderr": bytearray()}
        truncated = set()

        def drain(name, pipe):
            while chunk := pipe.read(8192):
                room = MAX_OUTPUT_BYTES - len(output[name])
                if room > 0:
                    output[name].extend(chunk[:room])
                if len(chunk) > room:
                    truncated.add(name)

        readers = [Thread(target=drain, args=(name, getattr(process, name)), daemon=True) for name in output]
        try:
            job_handle, job_limits = self._assign_windows_job(process)
            self._resume_windows_process(process)
            for reader in readers:
                reader.start()
            timed_out = False
            try:
                exit_code = process.wait(timeout=self.timeout)
            except subprocess.TimeoutExpired:
                timed_out = True
                self._terminate_tree(process, job_handle)
                if process.poll() is None:
                    process.kill()
                process.wait()
                exit_code = 124
        except Exception:
            self._terminate_tree(process, job_handle)
            if process.poll() is None:
                process.kill()
            process.wait()
            raise
        finally:
            if job_handle is not None:
                try:
                    import win32api
                    win32api.CloseHandle(job_handle)
                except (ImportError, OSError):
                    pass
        for reader in readers:
            if reader.ident is not None:
                reader.join(timeout=5)
        end = datetime.now(UTC)
        receipt = TerminalReceipt(
            shell=pending.shell,
            command=tuple(redact_sensitive_text(part) for part in pending.argv),
            working_directory=str(root),
            start_time=start.isoformat(),
            end_time=end.isoformat(),
            duration_seconds=round(monotonic() - started, 3),
            exit_code=exit_code,
            stdout=redact_sensitive_text(output["stdout"].decode("utf-8", errors="replace")),
            stderr=redact_sensitive_text(output["stderr"].decode("utf-8", errors="replace")),
            timed_out=timed_out,
            output_truncated=bool(truncated),
            process_job_limits=job_limits,
            approved=True,
        )
        self.receipt_log.parent.mkdir(parents=True, exist_ok=True)
        with self.log_lock, self.receipt_log.open("a", encoding="utf-8") as log:
            log.write(json.dumps(asdict(receipt), ensure_ascii=False) + "\n")
        return receipt

    @staticmethod
    def _assign_windows_job(process):
        if os.name != "nt":
            raise NishaError("Terminal process limits are available only on Windows.")
        try:
            import win32job

            job = win32job.CreateJobObject(None, "")
            limits = win32job.QueryInformationJobObject(job, win32job.JobObjectExtendedLimitInformation)
            basic = limits["BasicLimitInformation"]
            basic["LimitFlags"] |= (
                win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
                | win32job.JOB_OBJECT_LIMIT_PROCESS_MEMORY
                | win32job.JOB_OBJECT_LIMIT_PROCESS_TIME
            )
            basic["PerProcessUserTimeLimit"] = MAX_RUNTIME_SECONDS * 10_000_000
            limits["ProcessMemoryLimit"] = MAX_PROCESS_MEMORY
            win32job.SetInformationJobObject(job, win32job.JobObjectExtendedLimitInformation, limits)
            win32job.AssignProcessToJobObject(job, process._handle)
            return job, {
                "enabled": True,
                "kill_process_tree_on_timeout_or_close": True,
                "per_process_user_time_seconds": MAX_RUNTIME_SECONDS,
                "per_process_memory_bytes": MAX_PROCESS_MEMORY,
                "filesystem_or_network_restriction": False,
            }
        except Exception as exc:
            try:
                process.kill()
                process.wait(timeout=5)
            except (OSError, subprocess.SubprocessError):
                pass
            raise NishaError("Windows could not apply the required process Job Object limits; command was stopped.") from exc

    @staticmethod
    def _resume_windows_process(process):
        if os.name != "nt":
            raise NishaError("Terminal process execution is available on Windows only.")
        import ctypes
        from ctypes import wintypes

        resume = ctypes.WinDLL("ntdll").NtResumeProcess
        resume.argtypes = [wintypes.HANDLE]
        resume.restype = wintypes.LONG
        status = resume(wintypes.HANDLE(int(process._handle)))
        if status != 0:
            raise NishaError("Windows could not start the approved process inside its Job Object.")

    @staticmethod
    def _terminate_tree(process, job_handle):
        if job_handle is not None:
            try:
                import win32job
                win32job.TerminateJobObject(job_handle, 1)
                return
            except (ImportError, OSError):
                pass
        if os.name == "nt":
            taskkill = Path(os.environ.get("SYSTEMROOT", r"C:\Windows")) / "System32" / "taskkill.exe"
            if taskkill.is_file():
                try:
                    subprocess.run(
                        [str(taskkill), "/PID", str(process.pid), "/T", "/F"],
                        stdin=subprocess.DEVNULL,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        timeout=5,
                        shell=False,
                        check=False,
                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                    )
                    return
                except (OSError, subprocess.SubprocessError):
                    pass
        process.kill()

"""Explicit bounded tools; terminal commands use a separate approval-gated service."""

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from threading import RLock
from time import monotonic
from uuid import uuid4

from send2trash import send2trash

from nisha.errors import NishaError

TOOL_CATALOG = (
    {
        "name": "list_files",
        "description": "List files directly inside the NISHA workspace.",
        "parameters": {},
        "risk": "safe",
        "requires_confirmation": False,
    },
    {
        "name": "read_file",
        "description": "Read a UTF-8 text file inside the NISHA workspace.",
        "parameters": {"path": "relative workspace file path"},
        "risk": "safe",
        "requires_confirmation": False,
    },
    {
        "name": "delete_file",
        "description": "Move a workspace file to the recycle bin after approval.",
        "parameters": {"path": "relative workspace file path"},
        "risk": "sensitive",
        "requires_confirmation": True,
    },
)
TERMINAL_TOOL = {
    "name": "run_terminal_command",
    "description": "Prepare a project-scoped command for offline Windows Sandbox execution; execution requires separate one-use approval and never falls back to the host.",
    "parameters": {
        "shell": "powershell, cmd, python, or git",
        "project": "configured project name; command working directory",
        "args": "argument list for python/git, or script for powershell/cmd",
    },
    "risk": "sensitive_or_critical",
    "requires_confirmation": True,
}
_REGISTERED_ACTIONS = frozenset(tool["name"] for tool in TOOL_CATALOG)


@dataclass(frozen=True)
class PendingAction:
    path: Path
    digest: str
    expires: float


class ToolService:
    def __init__(self, store, workspace: Path, trash=send2trash):
        self.store = store
        self.workspace = workspace.resolve()
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.trash = trash
        self.pending = {}
        self.lock = RLock()

    @staticmethod
    def catalog():
        """Return registered tool metadata, including separate terminal approval flow."""
        return [
            {**tool, "parameters": dict(tool["parameters"])}
            for tool in (*TOOL_CATALOG, TERMINAL_TOOL)
        ]

    def allowed_file(self, name):
        if not isinstance(name, str) or not name.strip():
            raise NishaError("Specify a relative file path in data/workspace.")
        relative = Path(name)
        if relative.is_absolute() or relative.drive or ":" in name:
            raise NishaError("Only relative workspace paths are allowed.")
        candidate = (self.workspace / relative).resolve()
        if not candidate.is_relative_to(self.workspace) or not candidate.is_file():
            raise NishaError("That file is outside the allowed workspace or does not exist.")
        if candidate.stat().st_size > 10_000_000:
            raise NishaError("This tool accepts files up to 10 MB.")
        return candidate

    def propose(self, action, name=""):
        with self.lock:
            self.pending = {
                key: value for key, value in self.pending.items() if value.expires > monotonic()
            }
            if action == "list_files":
                files = [
                    str(p.relative_to(self.workspace))
                    for p in self.workspace.iterdir()
                    if p.is_file() and p.resolve().is_relative_to(self.workspace)
                ]
                self.store.audit(action, "completed")
                return {"status": "completed", "result": sorted(files)[:100]}
            if action not in _REGISTERED_ACTIONS:
                self.store.audit("unknown_tool", "denied")
                raise NishaError("Tool is not registered. Arbitrary system commands are disabled.")
            path = self.allowed_file(name)
            if action == "read_file":
                with path.open("r", encoding="utf-8") as source:
                    result = source.read(20_000)
                self.store.audit(action, "completed")
                return {"status": "completed", "result": result}
            token = str(uuid4())
            self.pending[token] = PendingAction(
                path, sha256(path.read_bytes()).hexdigest(), monotonic() + 120
            )
            self.store.audit(action, "awaiting_confirmation")
            return {
                "status": "confirmation_required",
                "approval_id": token,
                "description": f"Move {path.relative_to(self.workspace)} to the recycle bin?",
            }

    def confirm(self, approval_id, approved):
        with self.lock:
            pending = self.pending.pop(approval_id, None)
            if pending is None or pending.expires < monotonic():
                raise NishaError("Approval expired or was already used. Propose the action again.")
            if not approved:
                self.store.audit("delete_file", "cancelled")
                return {"status": "cancelled"}
            path = self.allowed_file(str(pending.path.relative_to(self.workspace)))
            if path != pending.path or sha256(path.read_bytes()).hexdigest() != pending.digest:
                raise NishaError("The file changed after the preview. Propose the action again.")
            self.trash(str(path))
            self.store.audit("delete_file", "completed")
            return {"status": "completed", "result": "Moved to the recycle bin."}

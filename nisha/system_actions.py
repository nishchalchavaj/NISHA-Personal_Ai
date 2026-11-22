"""Windows shell locations and explicit, one-use approval for destructive actions."""

import ctypes
import os
import re
import subprocess
from pathlib import Path
from time import time
from uuid import uuid4

from nisha.errors import NishaError
from nisha.process_lifetime import user_app_options


class SystemActions:
    def __init__(self, desktop, clock=time, executor=None):
        self.desktop, self.clock = desktop, clock
        self.executor = executor or self.perform
        self.pending = {}
        self.explorer_location = {}
        self.explorer_back = {}
        self.opened_file = {}

    def forget_explorer(self, session):
        self.explorer_location.pop(session, None)
        self.explorer_back.pop(session, None)

    def _navigate_explorer(self, session, destination, location):
        try:
            self.desktop.navigate_explorer(destination, location)
        except (NishaError, OSError) as exc:
            return f"I couldn't navigate Explorer: {exc}"
        self.explorer_back.setdefault(session, []).append(location)
        self.explorer_location[session] = (
            "this pc" if destination == "this pc" else Path(destination).resolve()
        )
        name = "This PC" if destination == "this pc" else Path(destination).name or str(destination)
        return f"Asked Explorer to open {name} in the same window."

    def _open_inside_explorer(self, text, session):
        """Resolve a short follow-up against the last Explorer location."""
        location = self.explorer_location.get(session)
        if location is None:
            return None
        value = re.sub(r"\s+", " ", text.casefold()).strip(" .!?")
        if value in {"back", "go back", "go back one folder"}:
            previous = self.explorer_back.get(session, [])
            if not previous:
                return "I don't have an earlier Explorer location in this conversation."
            destination = previous[-1]
            try:
                self.desktop.navigate_explorer(destination, location)
            except (NishaError, OSError) as exc:
                return f"I couldn't go back in Explorer: {exc}"
            previous.pop()
            self.explorer_location[session] = destination
            return "Asked Explorer to go back to " + (
                "This PC." if destination == "this pc" else f"{Path(destination).name or destination}."
            )
        if re.fullmatch(r"(?:go to|open|show) (?:the |my )?(?:this|my|just) pc", value):
            return self._navigate_explorer(session, "this pc", location)
        match = re.fullmatch(
            r"(?:please )?(?:open|show|go to|enter) (?:the |my )?(.+?)",
            text.strip().strip(".!?"),
            re.IGNORECASE,
        )
        if not match:
            bare_drive = re.fullmatch(
                r"(?:(?:local disk|disk|drive)\s+)([a-z])(?::|\s+drive)?",
                text.strip().strip(".!?"), re.IGNORECASE,
            )
            same_window = re.fullmatch(
                r"(?:please )?(?:(?:with|in) the same window[, ]+)?(?:open|go to|enter) (.+?)(?: in the same window)?",
                text.strip().strip(".!?"), re.IGNORECASE,
            )
            if not same_window and not bare_drive:
                return None
            name = same_window[1].strip() if same_window else text.strip().strip(".!?")
        else:
            name = match[1].strip()
            name = re.sub(r"\s+in the same window$", "", name, flags=re.IGNORECASE)
        if re.search(r"\bin (?:google chrome|chrome|microsoft edge|edge)$", name, re.IGNORECASE):
            return None
        if name.casefold().startswith("desktop ") or " and " in name.casefold():
            return None
        name = re.sub(r"^(?:file|folder)\s+|\s+folder$", "", name, flags=re.IGNORECASE)
        if location == "this pc" and name.casefold() == "local dixie":
            name = "local disk c"
        # Explicitly named apps, sites and locations are separate tasks.
        if re.search(r"[/\\]|\b(?:app|application|website|site|browser)\b", name, re.IGNORECASE):
            return None
        if location == "recycle bin":
            return None
        def is_explicit_other_target():
            from nisha.actions import WEBSITES, spoken_website

            if name.casefold() in WEBSITES or spoken_website(name):
                return True
            app_path = getattr(self.desktop, "app_path", None)
            if app_path is not None:
                try:
                    return bool(app_path(name))
                except (NishaError, OSError):
                    pass
            return False

        drive = re.fullmatch(
            r"(?:(?:local disk|disk|drive)\s+)?([a-z])(?::|\s+drive)?",
            name, re.IGNORECASE,
        )
        if location == "this pc" or drive and name.casefold().startswith(("local disk", "disk ", "drive ")):
            if not drive:
                if is_explicit_other_target():
                    return None
                return f"I couldn't find {name} in This PC. Name a drive, or say 'open {name} app/site'."
            path = Path(drive[1].upper() + ":\\")
            if not path.is_dir():
                return f"I couldn't find drive {drive[1].upper()}: in This PC."
        else:
            folder = Path(location)
            if not folder.is_dir():
                self.forget_explorer(session)
                return "That Explorer folder is no longer available. Open it again."
            try:
                candidates = [p for p in folder.iterdir() if p.name.casefold() == name.casefold()]
                if not candidates:
                    candidates = [p for p in folder.iterdir() if p.stem.casefold() == name.casefold()]
            except OSError:
                return "I couldn't read that Explorer folder."
            if len(candidates) > 1:
                return "Several items have that name here. Say the full file or folder name."
            if not candidates:
                if is_explicit_other_target():
                    return None
                return f"I couldn't find {name} in {folder.name or folder}. Name another item or an app/site."
            path = candidates[0]
        try:
            if path.is_dir():
                return self._navigate_explorer(session, path, location)
            self.desktop.open_file(path)
            self.opened_file[session] = path
            self.forget_explorer(session)
            return f"Asked the default app to open {path.name}."
        except (NishaError, OSError) as exc:
            return f"I couldn't open {path.name}: {exc}"

    def handle(self, text, session):
        value = re.sub(r"\s+", " ", text.casefold()).strip(" .!?")
        opened = re.fullmatch(
            r"(?:please )?(?:open|show|launch) (?:the |my |a )?"
            r"(recycle bin|recycle bin icon|this pc|my pc|ypc|my computer|downloads|downloads folder)",
            value,
        )
        if opened:
            target = opened[1]
            name = (
                "recycle bin"
                if target.startswith("recycle bin")
                else "this pc"
                if target in {"this pc", "my pc", "ypc", "my computer"}
                else "downloads"
            )
            try:
                self.desktop.open_special(name)
            except (NishaError, OSError) as exc:
                return f"I couldn't open {name}: {exc}"
            self.explorer_location[session] = (
                "this pc" if name == "this pc" else Path.home() / "Downloads" if name == "downloads" else "recycle bin"
            )
            self.explorer_back[session] = []
            return f"Asked Windows Explorer to open {name}."
        inside = self._open_inside_explorer(text, session)
        if inside is not None:
            return inside
        approve = re.fullmatch(r"approve (recycle bin|shutdown|restart) ([a-f0-9]{8})", value)
        if approve:
            operation, token = approve.groups()
            expected = self.pending.get(session)
            if not expected or expected[:2] != (operation, token) or expected[2] < self.clock():
                return "That approval is missing or expired. No system action was performed."
            self.pending.pop(session, None)  # Consume before dispatch; replay cannot run again.
            try:
                return self.executor(operation)
            except (NishaError, OSError, subprocess.SubprocessError) as exc:
                return f"Windows did not complete {operation}: {exc}"
        recycle = re.fullmatch(
            r"(?:please )?(?:empty|clear|delete|remove) "
            r"(?:(?:everything|all(?: the)? files|all|the contents)(?: in| from)? )?"
            r"(?:the |my )?recycle bin",
            value,
        )
        shutdown = re.fullmatch(
            r"(?:please )?(?:shut down|shutdown|restart|reboot)(?: the | my )?(?:pc|computer|windows)?",
            value,
        )
        if recycle or shutdown:
            operation = (
                "recycle bin"
                if recycle
                else "restart"
                if "restart" in value or "reboot" in value
                else "shutdown"
            )
            token = uuid4().hex[:8]
            self.pending[session] = (operation, token, self.clock() + 180)
            consequence = (
                "permanently remove everything currently in the Recycle Bin"
                if operation == "recycle bin"
                else "restart your PC"
                if operation == "restart"
                else "shut down your PC"
            )
            return f"I haven't done that. To {consequence}, say 'approve {operation} {token}' within three minutes."
        return None

    @staticmethod
    def perform(operation):
        if os.name != "nt":
            raise NishaError("This action is available on Windows.")
        if operation == "recycle bin":
            result = ctypes.windll.shell32.SHEmptyRecycleBinW(None, None, 0x1 | 0x2 | 0x4)
            if result:
                raise NishaError(f"Recycle Bin returned Windows status {result}.")
            return "Windows reported that the Recycle Bin was emptied."
        if operation not in {"shutdown", "restart"}:
            raise ValueError("Unsupported system operation")
        command = ["shutdown.exe", "/r" if operation == "restart" else "/s", "/t", "0"]
        subprocess.Popen(command, shell=False, **user_app_options())
        return f"Asked Windows to {operation} the PC."

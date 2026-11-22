"""Cached Windows Start-menu inventory, including Store/MSIX applications."""

import json
import os
import re
import subprocess
from pathlib import Path
from threading import RLock
from time import monotonic

from nisha.errors import NishaError


def app_name(value):
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


def friendly_name(value):
    key = app_name(value)
    key = re.sub(r"^(?:adobe|google|microsoft) ", "", key)
    return {"vs code": "visual studio code", "vscode": "visual studio code"}.get(key, key)


class AppCatalog:
    def __init__(self, reader=None, clock=monotonic):
        self.reader = reader or self.read_windows
        self.clock = clock
        self.entries = []
        self.expires = 0
        self.lock = RLock()

    @staticmethod
    def read_windows():
        if os.name != "nt":
            return []
        executable = (
            Path(os.environ.get("WINDIR", "C:/Windows"))
            / "System32/WindowsPowerShell/v1.0/powershell.exe"
        )
        result = subprocess.run(
            [
                str(executable),
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                "[Console]::OutputEncoding=[System.Text.Encoding]::UTF8; @(Get-StartApps | Select-Object Name,AppID) | ConvertTo-Json -Compress",
            ],
            capture_output=True,
            encoding="utf-8",
            timeout=12,
            check=False,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        if result.returncode:
            raise NishaError("Windows app discovery is unavailable. Configured apps still work.")
        entries = json.loads(result.stdout.lstrip("\ufeff") or "[]")
        return entries if isinstance(entries, list) else [entries]

    def all(self, refresh=False):
        with self.lock:
            if refresh or self.clock() >= self.expires:
                try:
                    self.entries = [
                        entry
                        for entry in self.reader()
                        if isinstance(entry, dict) and entry.get("Name") and entry.get("AppID")
                    ]
                except (OSError, ValueError, subprocess.TimeoutExpired, NishaError):
                    self.expires = self.clock() + 30
                else:
                    self.expires = self.clock() + 300
            return list(self.entries)

    @staticmethod
    def shortcuts():
        """Return local user/public launch shortcuts without following them."""
        if os.name != "nt":
            return []
        user = Path(os.environ.get("USERPROFILE", str(Path.home())))
        appdata = Path(os.environ.get("APPDATA", user / "AppData/Roaming"))
        program_data = Path(os.environ.get("PROGRAMDATA", "C:/ProgramData"))
        public = Path(os.environ.get("PUBLIC", "C:/Users/Public"))
        try:
            from win32com.shell import shell, shellcon

            desktop = Path(shell.SHGetFolderPath(0, shellcon.CSIDL_DESKTOPDIRECTORY, None, 0))
        except (ImportError, OSError):
            desktop = user / "Desktop"
        roots = [
            desktop,
            public / "Desktop",
            appdata / "Microsoft/Windows/Start Menu/Programs",
            program_data / "Microsoft/Windows/Start Menu/Programs",
        ]
        found = []
        for root in roots:
            if not root.is_dir():
                continue
            try:
                found.extend(path for path in root.rglob("*.lnk") if path.is_file())
            except OSError:
                continue
        return sorted(set(found), key=lambda path: str(path).casefold())

    def resolve_shortcut(self, name):
        key = app_name(name)
        matches = [path for path in self.shortcuts() if app_name(path.stem) == key]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise NishaError(
                "Several shortcuts have that name. Use an installed app name or rename the shortcut."
            )
        return None

    def resolve(self, name):
        key = app_name(name)
        key = {
            "vs code": "visual studio code",
            "vscode": "visual studio code",
            "edge": "microsoft edge",
            "chrome": "google chrome",
        }.get(key, key)
        entries = self.all()
        matches = [e for e in entries if app_name(e["Name"]) == key]
        if not matches:
            matches = [
                e
                for e in entries
                if re.fullmatch(re.escape(key) + r" (?:\d+(?: \d+)*|desktop)", app_name(e["Name"]))
            ]
        if not matches:
            friendly = friendly_name(name)
            matches = [e for e in entries if friendly_name(e["Name"]) == friendly]
            if not matches:
                matches = [
                    e
                    for e in entries
                    if re.fullmatch(
                        re.escape(friendly) + r" (?:\d+(?: \d+)*|desktop)", friendly_name(e["Name"])
                    )
                ]
            if not matches and re.search(r" \d{2}$", friendly):
                # Spoken Adobe year names often omit '20'. Keep the app prefix
                # exact, and still reject multiple matching installed versions.
                matches = [
                    e
                    for e in entries
                    if re.sub(r" 20(\d{2})$", r" \1", friendly_name(e["Name"])) == friendly
                ]
        if len(matches) == 1:
            return "shell:AppsFolder\\" + matches[0]["AppID"]
        if len(matches) > 1:
            raise NishaError(
                "Several installed apps match. Use the full name: "
                + ", ".join(e["Name"] for e in matches)
            )
        return None

    def handle(self, text):
        if text.casefold().strip(" .!?") in {
            "list installed apps",
            "show installed apps",
            "what apps are installed",
            "refresh installed apps",
        }:
            entries = self.all(refresh=text.casefold().startswith("refresh"))
            names = sorted(e["Name"] for e in entries)
            return (
                "Installed Windows apps:\n" + "\n".join(names)
                if names
                else "Windows app discovery is unavailable. Check configured app paths in config/nisha.yaml."
            )
        if text.casefold().strip(" .!?") in {
            "list shortcuts",
            "show shortcuts",
            "what shortcuts are installed",
        }:
            names = sorted({path.stem for path in self.shortcuts()})
            return (
                "Shortcuts on this PC:\n" + "\n".join(names[:200])
                if names
                else "No desktop or Start-menu shortcuts found."
            )
        return None

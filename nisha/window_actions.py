"""Native window requests and observed results; never terminate app processes."""

import os
import re
from dataclasses import dataclass
from time import monotonic, sleep

from nisha.errors import NishaError


@dataclass(frozen=True)
class Window:
    handle: int
    pid: int
    title: str


class WindowsBackend:
    def __init__(self):
        if os.name != "nt":
            raise NishaError("Window control is available on Windows.")
        import ctypes

        import pywintypes
        import win32gui
        import win32process

        self.gui, self.process = win32gui, win32process
        self.native_error = pywintypes.error
        self.ctypes = ctypes
        self.cloaked = ctypes.WinDLL("dwmapi").DwmGetWindowAttribute
        self.cloaked.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_void_p, ctypes.c_ulong]
        self.cloaked.restype = ctypes.c_long
        self.minimize_async = ctypes.WinDLL("user32", use_last_error=True).ShowWindowAsync
        self.minimize_async.argtypes = [ctypes.c_void_p, ctypes.c_int]
        self.minimize_async.restype = ctypes.c_int

    def windows(self):
        result = []

        def visit(handle, _):
            try:
                if not self.gui.IsWindowVisible(handle):
                    return
                cloaked = self.ctypes.c_ulong()
                if (
                    self.cloaked(
                        handle, 14, self.ctypes.byref(cloaked), self.ctypes.sizeof(cloaked)
                    )
                    == 0
                    and cloaked.value
                ):
                    return  # Hidden on another virtual desktop, not visible here.
                title = self.gui.GetWindowText(handle).strip()
                category = self.gui.GetClassName(handle)
                if not title or category in {
                    "Progman",
                    "WorkerW",
                    "Shell_TrayWnd",
                    "Shell_SecondaryTrayWnd",
                }:
                    return
                # Owned popups/save dialogs are handled by their main window.
                if self.gui.GetWindow(handle, 4):  # GW_OWNER
                    return
                style = self.gui.GetWindowLong(handle, -20)  # GWL_EXSTYLE
                if style & 0x80 and not style & 0x40000:  # Tool window, not an app window.
                    return
                pid = self.process.GetWindowThreadProcessId(handle)[1]
                # The assistant retains its resident window/listener.
                if pid == os.getpid():
                    return
                result.append(Window(handle, pid, title))
            except self.native_error:
                return  # A window can disappear while enumerating.

        self.gui.EnumWindows(visit, None)
        return result

    def status(self, window):
        try:
            if not self.gui.IsWindow(window.handle):
                return "closed"
            if self.process.GetWindowThreadProcessId(window.handle)[1] != window.pid:
                return "closed"  # The original window closed and its handle was reused.
            if not self.gui.IsWindowVisible(window.handle):
                return "hidden"
            return "minimized" if self.gui.IsIconic(window.handle) else "open"
        except self.native_error:
            return "closed"

    def request(self, window, action):
        if self.status(window) in {"closed", "hidden"}:
            return
        try:
            if action == "minimize":
                if not self.minimize_async(window.handle, 6):  # SW_MINIMIZE
                    raise NishaError("Windows rejected a minimize request.")
            elif action == "close":
                self.gui.PostMessage(window.handle, 0x10, 0, 0)  # WM_CLOSE; preserve save prompts.
            else:
                raise ValueError("Unsupported window action.")
        except self.native_error as exc:
            raise NishaError(
                "Windows rejected a window request; the app may need elevated access."
            ) from exc


class WindowActions:
    def __init__(self, backend=None, wait_seconds=None):
        self.backend = backend
        self.wait_seconds = wait_seconds

    def handle(self, text):
        normalized = re.sub(r"\s+", " ", text.casefold()).strip(" .!?")
        excluded = re.fullmatch(
            r"(?:please )?(close|minimi[sz]e) (?:all )?(?:the |my |open )?windows except (?:the )?(.+)",
            normalized,
        )
        if excluded:
            action = "close" if excluded[1] == "close" else "minimize"
            name = excluded[2].strip()
            try:
                backend = self.backend or WindowsBackend()
                windows = backend.windows()
                if not any(name in window.title.casefold() for window in windows):
                    return f"I couldn't identify a {name} window to keep open. Nothing was {action}d."
                targets = [window for window in windows if name not in window.title.casefold()]
                return self.perform(action, targets)
            except (NishaError, OSError) as exc:
                return f"I couldn't {action} the other windows: {exc}"
        match = re.fullmatch(
            r"(?:please )?(close|minimi[sz]e) (?:all )?(?:(?:the|my|your|open|desktop) )*windows(?: on (?:the |my )?desktop)?",
            normalized,
        )
        if normalized in {"show desktop", "show my desktop"}:
            action = "minimize"
        elif match:
            action = "close" if match[1] == "close" else "minimize"
        else:
            targeted = re.fullmatch(r"(?:please )?(close|minimi[sz]e) (?:the |my )?(.+)", normalized)
            if (
                not targeted
                or targeted[2] in {"youtube", "google", "gmail", "github", "wikipedia"}
                or " and " in targeted[2]
            ):
                return None
            action = "close" if targeted[1] == "close" else "minimize"
            try:
                backend = self.backend or WindowsBackend()
                target = targeted[2]
                if target == "spotify":
                    import psutil

                    def is_spotify(window):
                        try:
                            return psutil.Process(window.pid).name().casefold() == "spotify.exe"
                        except (psutil.NoSuchProcess, psutil.AccessDenied):
                            return False
                else:
                    def is_spotify(window):
                        return False
                windows = [
                    window for window in backend.windows()
                    if target in window.title.casefold() or is_spotify(window)
                ]
                if not windows:
                    return f"I couldn't find a visible {target} window. Nothing was {action}d."
                return self.perform(action, windows)
            except (NishaError, OSError) as exc:
                return f"I couldn't {action} the {target} window: {exc}"
        try:
            return self.perform(action)
        except (NishaError, OSError) as exc:
            return f"I couldn't {action} the windows: {exc}"

    def perform(self, action, windows=None):
        backend = self.backend or WindowsBackend()
        targets = backend.windows() if windows is None else windows
        if not targets:
            return "No other visible app windows to " + action + "."
        errors = []
        for window in targets:
            try:
                backend.request(window, action)
            except (NishaError, OSError):
                errors.append(window)
        finished = (
            {"closed", "hidden", "minimized"} if action == "minimize" else {"closed", "hidden"}
        )
        # Word can hide its frame briefly while it finishes closing. Allow that
        # transition to settle before deciding it only hid. Apps that actually
        # hide to a tray still receive the honest "hid instead of closing" result.
        settled = finished if action == "minimize" else {"closed"}
        wait_seconds = (
            self.wait_seconds
            if self.wait_seconds is not None
            else (3.0 if action == "close" else 0.8)
        )
        deadline = monotonic() + wait_seconds
        while (
            any(backend.status(window) not in settled for window in targets)
            and monotonic() < deadline
        ):
            sleep(0.05)
        states = [backend.status(window) for window in targets]
        remaining = sum(state not in finished for state in states)
        if action == "minimize":
            observed = sum(state == "minimized" for state in states)
            reply = f"Verified {observed} app window(s) minimized."
        else:
            closed, hidden = states.count("closed"), states.count("hidden")
            reply = f"Verified {closed} app window(s) closed."
            if hidden:
                reply += f" {hidden} window(s) hid instead of closing."
        if remaining:
            reply += f" {remaining} window(s) remain open; check for a save prompt or an app that refused the request."
        if errors:
            reply += f" Windows rejected {len(errors)} request(s)."
        return reply

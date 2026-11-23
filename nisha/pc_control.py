"""Explicit, accessible control of the user's currently visible Windows apps.

This is deliberately grounded in UI Automation. A model cannot invent a control
or silently execute arbitrary shell commands through this interface.
"""

import os
import re
from time import monotonic, sleep

from nisha.errors import NishaError
from nisha.window_actions import WindowsBackend

KEYS = {
    "ctrl s": "^s",
    "control s": "^s",
    "ctrl f": "^f",
    "control f": "^f",
    "ctrl a": "^a",
    "control a": "^a",
    "ctrl c": "^c",
    "control c": "^c",
    "ctrl v": "^v",
    "control v": "^v",
    "ctrl z": "^z",
    "control z": "^z",
    "ctrl y": "^y",
    "control y": "^y",
    "ctrl t": "^t",
    "control t": "^t",
    "ctrl w": "^w",
    "control w": "^w",
    "ctrl l": "^l",
    "control l": "^l",
    "escape": "{ESC}",
    "esc": "{ESC}",
    "tab": "{TAB}",
    "enter": "{ENTER}",
    "return": "{ENTER}",
    "up": "{UP}",
    "down": "{DOWN}",
    "left": "{LEFT}",
    "right": "{RIGHT}",
    "page up": "{PGUP}",
    "page down": "{PGDN}",
}
CONTROL_TYPES = {
    "Button",
    "Edit",
    "ComboBox",
    "MenuItem",
    "TabItem",
    "Hyperlink",
    "CheckBox",
    "RadioButton",
    "ListItem",
}
REVIEW_ACTION = re.compile(
    r"\b(?:send|submit|publish|post|share|subscribe|like|purchase|buy|pay|order|"
    r"delete|remove|erase|uninstall|format|reset|transfer|withdraw|"
    r"confirm|approve|authorize|allow|accept|yes|okay|ok)\b",
    re.IGNORECASE,
)


def normalize(value):
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


class UIABackend:
    def __init__(self):
        if os.name != "nt":
            raise NishaError("PC control is available on Windows.")
        import sys

        # Qt's desktop thread is STA; comtypes must use the same COM apartment.
        sys.coinit_flags = 2
        from pywinauto import Desktop, keyboard

        self.desktop = Desktop(backend="uia")
        self.keyboard = keyboard
        self.windows = WindowsBackend()

    def app_windows(self):
        return self.windows.windows()

    def controls(self, window):
        try:
            root = self.desktop.window(handle=window.handle)
            return [
                item
                for item in root.descendants(depth=7)
                if item.element_info.control_type in CONTROL_TYPES
                and item.element_info.name.strip()
                and item.is_visible()
                and item.is_enabled()
            ][:300]
        except Exception as exc:
            raise NishaError("I couldn't inspect this app's accessible controls.") from exc

    def spotify_player_buttons(self, window):
        """Read only the now-playing transport group, not playlist Play buttons."""
        try:
            root = self.desktop.window(handle=window.handle)
            groups = [
                item for item in root.descendants(depth=14)
                if item.element_info.control_type == "Group"
                and item.element_info.name == "Player controls"
                and item.is_visible()
            ]
            if len(groups) != 1:
                raise NishaError("I couldn't identify Spotify's player controls.")
            return [
                item for item in groups[0].descendants(depth=6)
                if item.element_info.control_type == "Button"
                and item.element_info.name.strip()
                and item.is_visible()
                and item.is_enabled()
            ]
        except NishaError:
            raise
        except Exception as exc:
            raise NishaError("I couldn't inspect Spotify's player controls.") from exc

    def focus(self, window):
        try:
            self.desktop.window(handle=window.handle).set_focus()
        except Exception as exc:
            raise NishaError("I couldn't focus that app window.") from exc

    def is_foreground(self, window):
        import win32gui

        return win32gui.GetForegroundWindow() == window.handle

    def click(self, control, button="left", clicks=1):
        try:
            control.click_input(button=button, double=clicks == 2)
        except Exception as exc:
            raise NishaError("The app refused that control click.") from exc

    def drag(self, source, target):
        try:
            source.drag_mouse_input(dst=target, src=source, button="left")
        except Exception as exc:
            raise NishaError("The app refused that accessible-control drag.") from exc

    def type_text(self, control, value):
        try:
            control.set_edit_text(value)
            return control.get_value() == value
        except Exception as exc:
            raise NishaError("I couldn't set or verify that text field.") from exc

    def press(self, keys):
        self.keyboard.send_keys(keys)

    def scroll(self, window, direction):
        from pywinauto import mouse

        try:
            point = self.desktop.window(handle=window.handle).rectangle().mid_point()
            mouse.scroll(coords=(point.x, point.y), wheel_dist=3 if direction == "up" else -3)
        except Exception as exc:
            raise NishaError("I couldn't scroll that app window.") from exc


class PCControl:
    def __init__(self, backend=None):
        self.backend = backend

    def _backend(self):
        return self.backend or UIABackend()

    def _window(self, backend, app):
        key = normalize(app)
        if not key or len(key) > 80:
            raise NishaError("Name the app window to control.")
        matches = [w for w in backend.app_windows() if key in normalize(w.title)]
        if not matches and key == "spotify":
            import psutil

            for window in backend.app_windows():
                try:
                    if psutil.Process(window.pid).name().casefold() == "spotify.exe":
                        matches.append(window)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
        if not matches:
            raise NishaError(f"I couldn't find an open {app} window.")
        if len(matches) > 1:
            names = ", ".join(w.title[:70] for w in matches[:5])
            raise NishaError(f"Several windows match {app}: {names}. Use a more specific title.")
        return matches[0]

    def _control(self, backend, window, label, types=None):
        key = normalize(label)
        if not key or len(key) > 100:
            raise NishaError("Name a visible control.")
        controls = backend.controls(window)
        matches = [
            c
            for c in controls
            if normalize(c.element_info.name) == key
            and (not types or c.element_info.control_type in types)
        ]
        if not matches:
            matches = [
                c
                for c in controls
                if key in normalize(c.element_info.name)
                and (not types or c.element_info.control_type in types)
            ]
        if not matches:
            raise NishaError(f"I couldn't find an accessible '{label}' control in {window.title}.")
        if len(matches) > 1:
            raise NishaError(
                f"Several controls match '{label}' in {window.title}. Use a more specific name."
            )
        return matches[0]

    def open_control(self, label, current_app):
        if not current_app:
            return None
        if REVIEW_ACTION.search(label):
            return "That control needs NISHA's reviewed action workflow."
        try:
            backend = self._backend()
            window = self._window(backend, current_app)
            control = self._control(
                backend, window, label,
                {"Button", "MenuItem", "TabItem", "Hyperlink", "ListItem"},
            )
            backend.focus(window)
            backend.click(control)
            return f"Opened '{control.element_info.name}' in {window.title}. Check the app for the result."
        except (NishaError, OSError, ImportError) as exc:
            return str(exc)

    def search(self, query, current_app):
        if not current_app or not 1 <= len(query) <= 200 or any(c in query for c in "\r\n\x00"):
            return "Give me a search phrase of 1–200 characters."
        try:
            backend = self._backend()
            window = self._window(backend, current_app)
            fields = [
                c for c in backend.controls(window)
                if c.element_info.control_type == "Edit"
                and "search" in normalize(c.element_info.name).split()
            ]
            if len(fields) != 1:
                return f"I couldn't identify one search field in {window.title}. Name its control explicitly."
            backend.focus(window)
            if not backend.type_text(fields[0], query):
                raise NishaError("The app didn't confirm the search text.")
            try:
                fields[0].set_focus()
            except Exception as exc:
                raise NishaError("I couldn't focus the search field to submit it.") from exc
            backend.press("{ENTER}")
            return f"Asked {window.title} to search for {query}."
        except NishaError as exc:
            return str(exc)

    def focus_app(self, app):
        try:
            backend = self._backend()
            window = self._window(backend, app)
            backend.focus(window)
            if not backend.is_foreground(window):
                return f"I asked Windows to focus {window.title}, but it isn't the foreground window."
            return f"Focused and verified {window.title} is the foreground window."
        except NishaError as exc:
            return str(exc)
        except (OSError, ImportError):
            return "Windows accessibility is unavailable, so I couldn't verify the foreground window."

    def launch_and_focus(self, desktop, app, wait_seconds=8):
        try:
            desktop.open_app(app)
        except (NishaError, OSError) as exc:
            return f"I couldn't launch {app}: {exc}"
        deadline = monotonic() + wait_seconds
        while True:
            result = self.focus_app(app)
            if result.startswith("Focused and verified "):
                return result
            if monotonic() >= deadline:
                return f"Asked Windows to launch {app}, but I couldn't verify it in the foreground. {result}"
            sleep(0.2)

    def handle(self, text, current_app=None):
        value = text.strip().strip(".!?")
        prefix = r"(?:please\s+)?(?:(?:can|could|would) you\s+)?"
        first_link = re.fullmatch(prefix + r"(?:click|tap|select) (?:on )?the first link", value, re.IGNORECASE)
        windows = re.fullmatch(
            prefix + r"(?:show|list) (?:open |running )?(?:app )?windows", value, re.IGNORECASE
        )
        inspect = re.fullmatch(
            prefix + r"(?:show|list) (?:controls|buttons) (?:in|on) (.+)", value, re.IGNORECASE
        )
        click = re.fullmatch(
            prefix + r"(?:click|tap|select) (.+?) (?:in|on) (.+)", value, re.IGNORECASE
        )
        right_click = re.fullmatch(
            prefix + r"right[ -]click (.+?) (?:in|on) (.+)", value, re.IGNORECASE
        )
        double_click = re.fullmatch(
            prefix + r"double[ -]click (.+?) (?:in|on) (.+)", value, re.IGNORECASE
        )
        drag = re.fullmatch(
            prefix + r"drag (.+?) (?:to|onto) (.+?) (?:in|on) (.+)",
            value,
            re.IGNORECASE,
        )
        focus = re.fullmatch(
            prefix + r"(?:switch to|focus|activate|bring) (.+?)(?: to (?:the )?(?:front|foreground))?",
            value, re.IGNORECASE,
        )
        foreground = re.fullmatch(
            prefix + r"(?:open|bring) (.+?) (?:in|on|to) (?:the )?(?:front|foreground)",
            value, re.IGNORECASE,
        )
        if foreground:
            focus = foreground
        scroll = re.fullmatch(prefix + r"scroll (up|down) (?:in|on) (.+)", value, re.IGNORECASE)
        typing = re.fullmatch(
            prefix + r"type (.+?) into (.+?) (?:in|on) (.+)", value, re.IGNORECASE | re.DOTALL
        )
        press = re.fullmatch(prefix + r"press (.+?) (?:in|on) (.+)", value, re.IGNORECASE)
        if current_app:
            inspect = inspect or re.fullmatch(prefix + r"(?:show|list) (?:controls|buttons)", value, re.IGNORECASE)
            click = click or re.fullmatch(prefix + r"(?:click|tap|select) (.+)", value, re.IGNORECASE)
            right_click = right_click or re.fullmatch(
                prefix + r"right[ -]click (.+)", value, re.IGNORECASE
            )
            double_click = double_click or re.fullmatch(
                prefix + r"double[ -]click (.+)", value, re.IGNORECASE
            )
            drag = drag or re.fullmatch(prefix + r"drag (.+?) (?:to|onto) (.+)", value, re.IGNORECASE)
            typing = typing or re.fullmatch(prefix + r"type (.+?) into (.+)", value, re.IGNORECASE | re.DOTALL)
            press = press or re.fullmatch(prefix + r"press (.+)", value, re.IGNORECASE)
            scroll = scroll or re.fullmatch(prefix + r"scroll (up|down)", value, re.IGNORECASE)
        if not any((windows, inspect, click, right_click, double_click, drag, typing, press, focus, scroll, first_link)):
            return None
        if focus:
            return self.focus_app(focus[1].strip())
        if first_link and not current_app:
            return "Name the app or webpage containing the link first."
        try:
            backend = self._backend()
            if windows:
                found = backend.app_windows()
                return (
                    "Open app windows:\n" + "\n".join(w.title for w in found[:80])
                    if found
                    else "No other visible app windows."
                )
            if inspect:
                app = inspect[1] if inspect.lastindex else current_app
            elif first_link:
                app = current_app
            elif drag:
                app = drag[3] if drag.lastindex == 3 else current_app
            elif click or right_click or double_click:
                target = click or right_click or double_click
                app = target[2] if target.lastindex == 2 else current_app
            elif typing:
                app = typing[3] if typing.lastindex == 3 else current_app
            elif press:
                app = press[2] if press.lastindex == 2 else current_app
            elif scroll:
                app = scroll[2] if scroll.lastindex == 2 else current_app
            else:
                app = current_app
            app = app.strip()
            window = self._window(backend, app)
            if scroll:
                backend.focus(window)
                backend.scroll(window, scroll[1].casefold())
                return f"Scrolled {scroll[1].casefold()} in {window.title}. Check the app for the position."
            if inspect:
                found = backend.controls(window)
                names = list(
                    dict.fromkeys(
                        f"{c.element_info.control_type}: {c.element_info.name}" for c in found
                    )
                )
                return (
                    f"Controls in {window.title}:\n" + "\n".join(names[:100])
                    if names
                    else f"{window.title} exposes no named controls."
                )
            if first_link:
                links = [
                    control for control in backend.controls(window)
                    if control.element_info.control_type == "Hyperlink"
                    and control.element_info.name.strip()
                ]
                if not links:
                    raise NishaError(f"I couldn't identify a first link in {window.title}.")
                backend.focus(window)
                backend.click(links[0])
                return f"Clicked the first accessible link, '{links[0].element_info.name}', in {window.title}."
            if click or right_click or double_click:
                match = click or right_click or double_click
                label = match[1].strip()
                if REVIEW_ACTION.search(label):
                    raise NishaError(
                        "That control can make an external or destructive change. Use NISHA's reviewed action workflow."
                    )
                control = self._control(backend, window, label)
                backend.focus(window)
                button = "right" if right_click else "left"
                clicks = 2 if double_click else 1
                backend.click(control, button=button, clicks=clicks)
                verb = "Right-clicked" if right_click else "Double-clicked" if double_click else "Clicked"
                return f"{verb} '{control.element_info.name}' in {window.title}. Check the app for the result."
            if drag:
                source_label, target_label = drag[1].strip(), drag[2].strip()
                if REVIEW_ACTION.search(source_label) or REVIEW_ACTION.search(target_label):
                    raise NishaError(
                        "That drag may make a destructive or external change. Use NISHA's reviewed action workflow."
                    )
                source = self._control(backend, window, source_label)
                target = self._control(backend, window, target_label)
                if source is target:
                    raise NishaError("Choose two different accessible controls to drag between.")
                backend.focus(window)
                backend.drag(source, target)
                return (
                    f"Dragged '{source.element_info.name}' to '{target.element_info.name}' "
                    f"in {window.title}. Check the app for the result."
                )
            if typing:
                content, label = typing[1], typing[2].strip()
                if not content or len(content) > 5000:
                    raise NishaError("The text must be between 1 and 5000 characters.")
                control = self._control(backend, window, label, {"Edit"})
                if getattr(control.element_info, "is_password", False):
                    raise NishaError("I won't enter text into a password field.")
                backend.focus(window)
                if not backend.type_text(control, content):
                    raise NishaError("The app didn't confirm the entered text.")
                return f"Verified text in '{control.element_info.name}' in {window.title}."
            key = normalize(press[1])
            if key in {"enter", "return"}:
                raise NishaError("Enter may submit an unseen form. Name its control or use a reviewed action workflow.")
            if key not in KEYS:
                raise NishaError(
                    "That key combination isn't supported. Try a standard key such as Ctrl+S, Ctrl+F, Tab or Escape."
                )
            backend.focus(window)
            backend.press(KEYS[key])
            return f"Sent {press[1]} to {window.title}. Check the app for the result."
        except NishaError as exc:
            return str(exc)

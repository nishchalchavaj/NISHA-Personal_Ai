from types import SimpleNamespace

import pytest

from nisha.pc_control import PCControl
from nisha.window_actions import Window


class FakeControl:
    def __init__(self, name, kind="Button", password=False):
        self.element_info = SimpleNamespace(name=name, control_type=kind, is_password=password)

    def set_focus(self):
        pass


class FakeBackend:
    def __init__(self, windows=None, controls=None):
        self._windows = windows or [Window(1, 2, "Notes - Notepad")]
        self._controls = controls or [FakeControl("Save"), FakeControl("Text Editor", "Edit")]
        self.calls = []
        self.foreground = True

    def app_windows(self):
        return self._windows

    def controls(self, window):
        return self._controls

    def focus(self, window):
        self.calls.append(("focus", window.title))

    def is_foreground(self, window):
        return self.foreground

    def click(self, control, button="left", clicks=1):
        self.calls.append(("click", control.element_info.name, button, clicks))

    def drag(self, source, target):
        self.calls.append(("drag", source.element_info.name, target.element_info.name))

    def type_text(self, control, value):
        self.calls.append(("type", control.element_info.name, value))
        return True

    def press(self, keys):
        self.calls.append(("press", keys))

    def scroll(self, window, direction):
        self.calls.append(("scroll", window.title, direction))


def test_discover_and_control_named_app():
    backend = FakeBackend()
    controller = PCControl(backend)
    assert "Notes - Notepad" in controller.handle("show open windows")
    assert "Button: Save" in controller.handle("show controls in Notepad")
    assert "Clicked 'Save'" in controller.handle("click Save in Notepad")
    assert backend.calls[-1] == ("click", "Save", "left", 1)
    assert "Verified text" in controller.handle("type hello into Text Editor in Notepad")
    assert backend.calls[-1] == ("type", "Text Editor", "hello")
    assert "Sent Ctrl+S" in controller.handle("press Ctrl+S in Notepad")
    assert backend.calls[-1] == ("press", "^s")
    assert "Focused" in controller.handle("switch to Notepad")
    assert "Scrolled down" in controller.handle("scroll down in Notepad")
    assert backend.calls[-1] == ("scroll", "Notes - Notepad", "down")


def test_short_followups_use_current_app_without_guessing_another_window():
    backend = FakeBackend()
    controller = PCControl(backend)
    assert "Clicked 'Save'" in controller.handle("click Save", current_app="Notepad")
    assert "Verified text" in controller.handle(
        "type hello into Text Editor", current_app="Notepad"
    )
    assert "Sent Ctrl+S" in controller.handle("press Ctrl+S", current_app="Notepad")
    assert "Scrolled down" in controller.handle("scroll down", current_app="Notepad")
    assert "Button: Save" in controller.handle("show controls", current_app="Notepad")
    assert "Opened 'Save'" in controller.open_control("Save", "Notepad")
    assert controller.handle("click Save") is None


def test_search_uses_one_accessible_search_field():
    backend = FakeBackend(controls=[FakeControl("Search", "Edit")])
    controller = PCControl(backend)
    assert "Asked Notes - Notepad to search" in controller.search("project", "Notepad")
    assert backend.calls[-2:] == [("type", "Search", "project"), ("press", "{ENTER}")]
    backend._controls.append(FakeControl("Search files", "Edit"))
    assert "couldn't identify one search field" in controller.search("project", "Notepad")


def test_first_link_click_uses_current_app_and_first_accessible_hyperlink():
    backend = FakeBackend(controls=[FakeControl("Dr Bro", "Hyperlink"), FakeControl("Other", "Hyperlink")])
    controller = PCControl(backend)
    assert "Dr Bro" in controller.handle("Click on the first link", current_app="Notepad")
    assert backend.calls[-1] == ("click", "Dr Bro", "left", 1)
    assert "Name the app" in controller.handle("Click on the first link")


def test_ambiguous_and_missing_targets_never_act():
    backend = FakeBackend(windows=[Window(1, 2, "Notes - Notepad"), Window(2, 3, "Draft - Notepad")])
    controller = PCControl(backend)
    assert "Several windows" in controller.handle("click Save in Notepad")
    assert not backend.calls
    backend._windows = [Window(1, 2, "Notes - Notepad")]
    assert "couldn't find" in controller.handle("click Missing in Notepad")
    assert not backend.calls


def test_password_and_unknown_shortcut_are_rejected():
    backend = FakeBackend(controls=[FakeControl("Password", "Edit", password=True)])
    controller = PCControl(backend)
    assert "password field" in controller.handle("type secret into Password in Notepad")
    assert "isn't supported" in controller.handle("press Alt+F4 in Notepad")
    assert "reviewed action" in controller.handle("click Send in Notepad")
    assert "reviewed action" in controller.open_control("Confirm", "Notepad")
    assert "Enter may submit" in controller.handle("press Enter in Notepad")
    assert not backend.calls


def test_right_and_double_click_target_one_named_control():
    backend = FakeBackend()
    controller = PCControl(backend)
    assert "Right-clicked 'Save'" in controller.handle("right-click Save in Notepad")
    assert backend.calls[-1] == ("click", "Save", "right", 1)
    assert "Double-clicked 'Save'" in controller.handle("double click Save", current_app="Notepad")
    assert backend.calls[-1] == ("click", "Save", "left", 2)
    assert "reviewed action" in controller.handle("double-click Delete in Notepad")
    assert backend.calls[-1] == ("click", "Save", "left", 2)


def test_drag_uses_two_named_accessible_controls_and_refuses_sensitive_targets():
    backend = FakeBackend(
        windows=[Window(1, 2, "File Explorer")],
        controls=[FakeControl("Report"), FakeControl("Archive folder")],
    )
    controller = PCControl(backend)
    assert "Dragged 'Report' to 'Archive folder'" in controller.handle(
        "drag Report to Archive folder in Explorer"
    )
    assert backend.calls[-1] == ("drag", "Report", "Archive folder")
    assert "reviewed action workflow" in controller.handle(
        "drag Report to Delete in Explorer"
    )
    assert backend.calls[-1] == ("drag", "Report", "Archive folder")


def test_pc_commands_route_as_actions():
    from nisha.responsiveness import action_request

    for phrase in (
        "show open windows", "show controls in Chrome", "click Save in Notepad",
        "type hello into Search in Chrome", "press Ctrl+F in Chrome", "list shortcuts",
        "switch to Chrome", "scroll down in Chrome", "right-click Save in Notepad",
        "double-click Save in Notepad",
        "drag Report to Archive in Explorer",
    ):
        assert action_request(phrase), phrase


def test_focus_only_claims_foreground_after_verification():
    backend = FakeBackend(windows=[Window(7, 8, "New Tab - Google Chrome")])
    controller = PCControl(backend)
    backend.foreground = False
    assert "isn't the foreground" in controller.handle("bring Chrome to foreground")
    backend.foreground = True
    assert "Focused and verified" in controller.handle("bring Chrome to foreground")


def test_launch_focus_reports_verified_state():
    backend = FakeBackend(windows=[Window(7, 8, "New Tab - Google Chrome")])
    controller = PCControl(backend)
    launched = []
    desktop = SimpleNamespace(open_app=lambda name: launched.append(name))
    assert "Focused and verified" in controller.launch_and_focus(desktop, "chrome")
    assert launched == ["chrome"]


def test_launch_focus_does_not_claim_foreground_when_unverified():
    backend = FakeBackend(windows=[Window(7, 8, "New Tab - Google Chrome")])
    backend.foreground = False
    controller = PCControl(backend)
    result = controller.launch_and_focus(
        SimpleNamespace(open_app=lambda name: None), "chrome", wait_seconds=0
    )
    assert "couldn't verify it in the foreground" in result


def test_spotify_window_remains_findable_after_title_changes(monkeypatch):
    import psutil

    monkeypatch.setattr(
        psutil, "Process", lambda pid: SimpleNamespace(name=lambda: "Spotify.exe")
    )
    window = Window(7, 42, "Artist - Current Song")
    backend = FakeBackend(windows=[window])
    assert PCControl(backend)._window(backend, "spotify") == window


def test_visual_coordinate_click_checks_dimensions_and_bounds(monkeypatch):
    import sys

    from nisha.errors import NishaError
    from nisha.pc_control import UIABackend

    clicks = []
    pyautogui = SimpleNamespace(size=lambda: (100, 80), click=lambda **kwargs: clicks.append(kwargs))
    monkeypatch.setitem(sys.modules, "pyautogui", pyautogui)
    backend = object.__new__(UIABackend)
    backend.click_point(50, 20, 100, 80)
    assert clicks == [{"x": 50, "y": 20, "clicks": 1, "interval": 0}]

    with pytest.raises(NishaError, match="size changed"):
        backend.click_point(50, 20, 200, 80)
    with pytest.raises(NishaError, match="outside"):
        backend.click_point(100, 20, 100, 80)
    assert len(clicks) == 1

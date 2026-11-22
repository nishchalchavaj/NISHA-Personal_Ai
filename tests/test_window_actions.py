import pytest

from nisha.errors import NishaError
from nisha.window_actions import Window, WindowActions


class Backend:
    def __init__(self, refuses=False, prompt=False):
        self.states = {1: "open", 2: "open"}
        self.calls = []
        self.refuses, self.prompt = refuses, prompt

    def windows(self):
        return [Window(handle, 123, "Example app") for handle in self.states]

    def status(self, window):
        return self.states[window.handle]

    def request(self, window, action):
        self.calls.append((window.handle, action))
        if self.refuses:
            raise NishaError("Denied")
        if window.handle == 2 and self.prompt:
            return
        self.states[window.handle] = "closed" if action == "close" else "minimized"


@pytest.mark.parametrize(
    "phrase,action",
    [
        ("close windows", "close"),
        ("close all your windows", "close"),
        ("Please minimize all open windows!", "minimize"),
        ("minimise windows", "minimize"),
        ("show desktop", "minimize"),
    ],
)
def test_exact_window_commands_do_native_actions_without_model(core, phrase, action):
    backend = Backend()
    core.window_actions = WindowActions(backend, wait_seconds=0)
    reply = core.chat(phrase, core.new_session())
    assert backend.calls == [(1, action), (2, action)]
    assert "Verified 2" in reply
    assert not core.gateway.calls


def test_unsaved_prompt_is_reported_as_still_open():
    actions = WindowActions(Backend(prompt=True), wait_seconds=0)
    reply = actions.handle("close windows")
    assert "Verified 1" in reply and "1 window(s) remain open" in reply
    assert "save prompt" in reply


def test_denied_requests_never_claim_success():
    actions = WindowActions(Backend(refuses=True), wait_seconds=0)
    reply = actions.handle("minimize windows")
    assert "Verified 0" in reply and "2 window(s) remain open" in reply
    assert "rejected 2" in reply


def test_close_all_except_named_window_keeps_that_window():
    class Named(Backend):
        def windows(self):
            return [Window(1, 123, "ChatGPT"), Window(2, 124, "Word")]

    backend = Named()
    reply = WindowActions(backend, wait_seconds=0).handle("close all windows except ChatGPT")
    assert backend.calls == [(2, "close")]
    assert "Verified 1" in reply
    assert backend.states[1] == "open"


def test_close_waits_for_hidden_window_shutdown(monkeypatch):
    time = [0.0]

    class Closing(Backend):
        def request(self, window, action):
            self.states[window.handle] = "hidden"

        def status(self, window):
            return "closed" if time[0] >= 0.1 else self.states[window.handle]

    monkeypatch.setattr("nisha.window_actions.monotonic", lambda: time[0])
    monkeypatch.setattr(
        "nisha.window_actions.sleep", lambda delay: time.__setitem__(0, time[0] + delay)
    )
    reply = WindowActions(Closing()).handle("close windows")
    assert reply == "Verified 2 app window(s) closed."


def test_close_reports_app_that_stays_hidden(monkeypatch):
    time = [0.0]

    class Hides(Backend):
        def request(self, window, action):
            self.states[window.handle] = "hidden"

    monkeypatch.setattr("nisha.window_actions.monotonic", lambda: time[0])
    monkeypatch.setattr(
        "nisha.window_actions.sleep", lambda delay: time.__setitem__(0, time[0] + delay)
    )
    reply = WindowActions(Hides()).handle("close windows")
    assert reply == "Verified 0 app window(s) closed. 2 window(s) hid instead of closing."
    assert time[0] >= 3


def test_close_allows_slow_editor_shutdown(monkeypatch):
    time = [0.0]

    class SlowEditor(Backend):
        def request(self, window, action):
            pass

        def status(self, window):
            return "closed" if time[0] >= 2 else "open"

    monkeypatch.setattr("nisha.window_actions.monotonic", lambda: time[0])
    monkeypatch.setattr(
        "nisha.window_actions.sleep", lambda delay: time.__setitem__(0, time[0] + delay)
    )
    reply = WindowActions(SlowEditor()).handle("close windows")
    assert reply == "Verified 2 app window(s) closed."


@pytest.mark.parametrize(
    "phrase",
    [
        "write about windows",
        "close YouTube",
        "explain how to minimize windows",
        "do not close windows",
    ],
)
def test_unrelated_phrases_do_not_control_windows(phrase):
    backend = Backend()
    assert WindowActions(backend).handle(phrase) is None
    assert not backend.calls


def test_uncertain_voice_command_cannot_control_windows(core):
    backend = Backend()
    core.window_actions = WindowActions(backend)
    reply = "".join(core.stream("close windows", core.new_session(), uncertain=True))
    assert "confirm command" in reply and not backend.calls

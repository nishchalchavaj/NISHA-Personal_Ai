import re

import pytest

from nisha.actions import WebsiteActions
from nisha.dialogue import resolve_followup
from nisha.responsiveness import action_request
from nisha.window_actions import Window, WindowActions


def test_bare_open_uses_only_nearby_named_target(core):
    opened = []
    core.workflows.desktop.app_path = lambda name: "synthetic.exe" if name == "chrome" else None
    core.workflows.desktop.open_app = opened.append
    session = core.new_session()
    core.chat("Open Chrome", session)
    assert "chrome" in core.chat("Open", session).casefold()
    assert opened == ["chrome", "chrome"]
    assert not core.gateway.calls
    assert core.store.history(session)[1][-2]["content"] == "Open"


def test_bare_open_without_reference_requests_target(core):
    assert "haven't" in core.chat("Open", core.new_session())
    assert not core.gateway.calls


def test_old_reference_or_executable_is_not_reused():
    history = [
        {"role": "user", "content": "open cmd.exe /c erase"},
        {"role": "assistant", "content": "No action"},
    ]
    assert resolve_followup("Open", history) == "Open"


@pytest.mark.parametrize(
    "command",
    [
        "Clear everything in Recycle Bin",
        "Shut down the PC",
        "Open unknown installed program",
        "Open Recycle Bin",
        "Open My PC",
    ],
)
def test_action_requests_never_become_freeform_claims(core, command):
    core.workflows.desktop.open_special = lambda *_: None
    core.workflows.desktop.app_path = lambda *_: None
    core.actions = WebsiteActions(lambda *_args, **_kwargs: pytest.fail("Unexpected website"))
    reply = core.chat(command, core.new_session())
    assert reply and not core.gateway.calls


def test_windows_shell_locations_use_windows_adapter(core):
    opened = []
    core.workflows.desktop.open_special = opened.append
    session = core.new_session()
    assert "Explorer" in core.chat("Open Recycle Bin", session)
    assert "Explorer" in core.chat("Open My PC", session)
    assert opened == ["recycle bin", "this pc"]
    assert not core.gateway.calls


def test_unknown_app_name_does_not_become_google_search(core):
    opened = []
    core.actions = WebsiteActions(lambda url, **_: opened.append(url) or True)
    core.workflows.desktop.app_path = lambda _: None
    reply = core.chat("open Rain Simulator", core.new_session())
    assert "haven't opened" in reply
    assert not opened and not core.gateway.calls


def test_recycle_bin_and_power_require_one_use_exact_session_approval(core):
    performed = []
    core.system_actions.executor = lambda op: performed.append(op) or "Windows accepted."
    first = core.new_session()
    second = core.store.new_session()
    prompt = core.chat("Clear everything in Recycle Bin", first)
    token = re.search(r"approve recycle bin ([a-f0-9]{8})", prompt)[1]
    assert "No system action" in core.chat(f"approve recycle bin {token}", second)
    assert performed == []
    assert core.chat(f"approve recycle bin {token}", first) == "Windows accepted."
    assert performed == ["recycle bin"]
    assert "No system action" in core.chat(f"approve recycle bin {token}", first)
    prompt = core.chat("shut down the PC", first)
    token = re.search(r"approve shutdown ([a-f0-9]{8})", prompt)[1]
    core.chat(f"approve shutdown {token}", first)
    assert performed == ["recycle bin", "shutdown"]


@pytest.mark.parametrize("phrase", [
    "Delete everything from the recycle bin.",
    "Delete all the files from the Recycle Bin.",
    "Clear everything in Recycle Bin.",
])
def test_spoken_recycle_bin_variants_prepare_approval_without_deleting(core, phrase):
    performed = []
    core.system_actions.executor = lambda op: performed.append(op)
    reply = core.chat(phrase, core.new_session())
    assert re.search(r"approve recycle bin [a-f0-9]{8}", reply)
    assert not performed and not core.gateway.calls


def test_spoken_background_recycle_request_reaches_approval_handler(core):
    performed = []
    core.system_actions.executor = lambda op: performed.append(op)
    session = core.new_session()
    reply = core.background_action("Delete everything from the recycle bin.", session)
    assert re.search(r"approve recycle bin [a-f0-9]{8}", reply)
    assert not performed and not core.gateway.calls


def test_chrome_search_launches_explicit_browser_not_website_fallback(core):
    searches = []
    websites = []
    core.workflows.desktop.search_in_browser = lambda name, query: searches.append((name, query))
    core.actions = WebsiteActions(lambda url, **_: websites.append(url) or True)
    reply = core.chat("Open Chrome and search for YouTube.", core.new_session())
    assert searches == [("chrome", "youtube")]
    assert "Asked chrome to search for youtube" in reply
    assert not websites and not core.gateway.calls


def test_browser_search_uses_installed_browser_and_encodes_query(monkeypatch):
    from nisha.desktop import DesktopAdapter

    launches = []
    adapter = DesktopAdapter()
    monkeypatch.setattr(adapter, "app_path", lambda name: "C:/Chrome/chrome.exe")
    monkeypatch.setattr(
        "nisha.desktop.subprocess.Popen", lambda args, **kwargs: launches.append((args, kwargs))
    )
    adapter.search_in_browser("chrome", "YouTube tutorials")
    assert launches[0][0] == [
        "C:/Chrome/chrome.exe", "https://www.google.com/search?q=YouTube+tutorials"
    ]
    assert launches[0][1]["shell"] is False


def test_approval_expires_and_new_session_clears_it(core):
    clock = [100.0]
    core.system_actions.clock = lambda: clock[0]
    core.system_actions.executor = lambda *_: pytest.fail("Expired approval executed")
    session = core.new_session()
    prompt = core.chat("empty recycle bin", session)
    token = re.search(r"approve recycle bin ([a-f0-9]{8})", prompt)[1]
    clock[0] = 281
    assert "expired" in core.chat(f"approve recycle bin {token}", session)
    core.new_session()
    assert not core.system_actions.pending


def test_targeted_window_action_uses_only_matching_title(core):
    class Backend:
        def __init__(self):
            self.calls = []
            self.state = {1: "open", 2: "open"}

        def windows(self):
            return [Window(1, 100, "VLC media player"), Window(2, 101, "Word")]

        def status(self, window):
            return self.state[window.handle]

        def request(self, window, action):
            self.calls.append((window.handle, action))
            self.state[window.handle] = "minimized"

    backend = Backend()
    core.window_actions = WindowActions(backend, wait_seconds=0)
    session = core.new_session()
    assert "Verified 1" in core.chat("Minimize VLC media player", session)
    assert backend.calls == [(1, "minimize")]
    assert "Nothing" in core.chat("Minimize missing app", session)


def test_direct_quiet_language_and_action_controls_are_not_queued(core):
    from nisha.interaction import is_quiet_request, is_silent_request

    assert is_quiet_request("Don't say any word")
    assert is_quiet_request("Be silent")
    assert is_silent_request("Don't say any word")
    assert not is_silent_request("Don't disturb me")
    assert not action_request("Start a new conversation")
    assert not action_request("send it")
    assert action_request("Open Recycle Bin")
    assert action_request("Clear everything in Recycle Bin")

from urllib.parse import parse_qs, urlparse

import pytest

from nisha.actions import WebsiteActions
from nisha.browser_session import SessionControls, youtube_url
from nisha.errors import NishaError


@pytest.mark.parametrize(
    "utterance",
    [
        "open YouTube and search Dr Bro",
        "open YouTube search Dr Bro",
        "search Dr Bro on YouTube",
        "find Dr Bro channel in YouTube",
    ],
)
def test_search_stays_on_youtube(core, utterance):
    calls = []
    core.actions = WebsiteActions(lambda url, new: calls.append(url) or True)
    reply = core.chat(utterance, core.new_session())
    assert urlparse(calls[0]).hostname == "www.youtube.com"
    assert parse_qs(urlparse(calls[0]).query)["search_query"] == ["Dr Bro"]
    assert "YouTube" in reply and not core.gateway.calls


class Browser:
    def __init__(self):
        self.calls = []
        self.fail = False

    def request(self, operation, **kwargs):
        self.calls.append((operation, kwargs))
        if self.fail:
            raise NishaError("Page changed; no account action confirmed.")
        if operation == "preview":
            return {
                "action": kwargs["action"],
                "url": "https://www.youtube.com/@DrBro",
                "title": "Dr Bro - YouTube",
                "already": False,
            }
        return {"message": "YouTube confirmed the subscription."}


def test_compound_subscription_is_reviewed_then_explicitly_approved_once(core):
    core.actions = WebsiteActions(lambda *args, **kwargs: True)
    browser = Browser()
    core.actions.youtube.browser = browser
    session = core.new_session()
    reply = core.chat("open YouTube and search Dr Bro and subscribe", session)
    assert "Review YouTube action" in reply
    assert [op for op, _ in browser.calls] == ["select_channel", "preview"]
    token = next(iter(core.actions.youtube.pending))
    reply = core.chat("approve youtube action", session)
    assert "confirmed" in reply
    assert len([op for op, _ in browser.calls if op == "apply"]) == 1
    core.chat("approve youtube " + token, session)
    assert len([op for op, _ in browser.calls if op == "apply"]) == 1


def test_new_conversation_and_unclear_speech_cannot_approve_account_action(core):
    core.actions = WebsiteActions(lambda *args, **kwargs: True)
    browser = Browser()
    core.actions.youtube.browser = browser
    session = core.new_session()
    core.chat("subscribe", session)
    token = next(iter(core.actions.youtube.pending))
    core.new_session()
    assert not core.actions.youtube.pending
    core.chat("approve youtube " + token, session)
    list(core.stream("subscribe", session, uncertain=True))
    assert all(op != "apply" for op, _ in browser.calls)


def test_browser_failure_and_expired_approval_are_honest(core):
    core.actions = WebsiteActions(lambda *args, **kwargs: True)
    browser = Browser()
    core.actions.youtube.browser = browser
    session = core.new_session()
    core.chat("subscribe", session)
    token = next(iter(core.actions.youtube.pending))
    core.actions.youtube.pending[token]["expires"] = 0
    assert "expired" in core.chat("approve youtube " + token, session)
    assert not any(op == "apply" for op, _ in browser.calls)
    browser.fail = True
    assert "no account action confirmed" in core.chat("like this video", session)


@pytest.mark.parametrize(
    "value",
    [
        "youtube.com.evil.org/watch",
        "https://evil.org/youtube",
        "http://youtube.com",
        "https://user:pass@youtube.com",
        "file:///youtube.com",
    ],
)
def test_account_controls_reject_untrusted_origins(value):
    assert youtube_url(value) is None


class Button:
    def __init__(self, name="Subscribe"):
        self.name, self.clicks = name, 0

    def window_text(self):
        return self.name

    def is_visible(self):
        return True

    def is_enabled(self):
        return True

    def invoke(self):
        self.clicks += 1
        self.name = "Subscribed"


class Document:
    def __init__(self, buttons):
        self.buttons = buttons

    def window_text(self):
        return "Dr Bro - YouTube"

    def descendants(self, control_type):
        return self.buttons


def test_accessibility_action_requires_unchanged_page_and_verifies_new_state():
    button = Button()
    document = Document([button])
    controls = SessionControls(windows=[])
    page = ["https://www.youtube.com/@DrBro"]
    controls.page = lambda: (None, document, page[0])
    preview = controls.preview("subscribe")
    page[0] = "https://www.youtube.com/@SomeoneElse"
    with pytest.raises(ValueError, match="changed"):
        controls.apply(preview)
    assert not button.clicks
    page[0] = preview["url"]
    assert "confirmed" in controls.apply(preview)["message"]
    assert button.clicks == 1
    assert controls.preview("subscribe")["already"]


def test_search_results_and_ambiguous_buttons_never_mutate():
    button = Button()
    controls = SessionControls(windows=[])
    document = Document([button, Button()])
    controls.page = lambda: (None, document, "https://www.youtube.com/results?search_query=Dr+Bro")
    with pytest.raises(ValueError, match="channel page"):
        controls.preview("subscribe")
    controls.page = lambda: (None, document, "https://www.youtube.com/@DrBro")
    with pytest.raises(ValueError, match="uniquely"):
        controls.preview("subscribe")
    assert not button.clicks


@pytest.mark.parametrize(
    "name,already",
    [
        ("Subscribe to Dr Bro", False),
        ("Subscribed to Dr Bro", True),
        ("Unsubscribe from Dr Bro", True),
    ],
)
def test_named_subscription_accessibility_labels(name, already):
    controls = SessionControls(windows=[])
    controls.page = lambda: (None, Document([Button(name)]), "https://www.youtube.com/@DrBro")
    assert controls.preview("subscribe")["already"] is already

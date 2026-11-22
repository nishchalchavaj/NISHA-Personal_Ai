from urllib.parse import urlparse

import pytest

from nisha.actions import WebsiteActions
from nisha.browser_commands import chrome_youtube_video_request
from nisha.browser_session import SessionControls, same_youtube_page
from nisha.listening import is_close_phrase
from nisha.responsiveness import action_request


@pytest.mark.parametrize("utterance", [
    "Open Chrome search YouTube and in YouTube search Dr.Bro channel and play any video",
    "Open Chrome, search YouTube, then search Dr Bro channel and play a video.",
])
def test_compound_chrome_youtube_request_is_parsed(utterance):
    assert chrome_youtube_video_request(utterance).replace(".", " ").casefold() == "dr bro"


def test_compound_request_stays_in_chrome_and_reports_verified_video(core):
    opened, browser_calls, defaults = [], [], []
    core.workflows.desktop.search_youtube_channel = lambda name, channel: opened.append(
        (name, channel)
    )
    core.actions = WebsiteActions(lambda url, **_: defaults.append(url) or True)
    core.actions.youtube.browser.request = lambda operation, **kwargs: (
        browser_calls.append((operation, kwargs))
        or {"title": "Verified video", "channel": kwargs["target"], "url": "https://www.youtube.com/watch?v=abc"}
    )
    reply = core.background_action(
        "Open Chrome search YouTube and in YouTube search Dr.Bro channel and play any video",
        core.new_session(),
    )
    assert opened == [("chrome", "Dr.Bro")]
    assert browser_calls == [("play_channel_video", {"browser": "chrome", "target": "Dr.Bro"})]
    assert "Playing Verified video" in reply
    assert not defaults and not core.gateway.calls


def test_chrome_navigation_failure_never_claims_playback(core):
    from nisha.errors import NishaError

    core.workflows.desktop.search_youtube_channel = lambda *_: None
    core.actions.youtube.browser.request = lambda *_args, **_kwargs: (_ for _ in ()).throw(
        NishaError("No exact channel")
    )
    reply = core.chat(
        "Open Chrome search YouTube and in YouTube search Dr Bro channel and play any video",
        core.new_session(),
    )
    assert "couldn't verify video playback" in reply and "Playing" not in reply


def test_chrome_url_named_address_bar_is_accepted_without_page_inputs(monkeypatch):
    class Element:
        def __init__(self, kind, name, value=None):
            self.element_info = type("Info", (), {"control_type": kind})()
            self.name, self.value = name, value

        def window_text(self):
            return self.name

        def get_value(self):
            return self.value

        def is_visible(self):
            return True

    address = Element("Edit", "youtube.com/@DrBro", "youtube.com/@DrBro")
    doc = Element("Document", "Dr Bro - YouTube")
    fake_input = Element("Edit", "YouTube URL", "https://www.youtube.com/@Wrong")

    class Window:
        def window_text(self):
            return "Dr Bro - YouTube - Google Chrome"

        def descendants(self, control_type=None):
            items = [address, doc, fake_input]
            return [x for x in items if x.element_info.control_type == control_type] if control_type else items

    monkeypatch.setattr(SessionControls, "is_browser", staticmethod(lambda window, browser=None: browser == "chrome"))
    _, document, url = SessionControls([Window()]).page(browser="chrome")
    assert document is doc and url == "https://youtube.com/@DrBro"


def test_youtube_address_alias_and_watch_identity():
    assert same_youtube_page(
        "https://youtube.com/@DrBro/videos", "https://www.youtube.com/@DrBro/videos"
    )
    assert same_youtube_page(
        "https://youtube.com/watch?v=abc&feature=share", "https://www.youtube.com/watch?v=abc"
    )
    assert not same_youtube_page(
        "https://youtube.com/watch?v=other", "https://www.youtube.com/watch?v=abc"
    )


@pytest.mark.parametrize("phrase", ["Close Nisha", "Close yourself", "If you are Nisha, close yourself"])
def test_latest_close_phrases_stay_ui_controls(phrase):
    assert is_close_phrase(phrase)
    assert not action_request(phrase)


def test_video_playback_selects_exact_handle_and_verifies_watch_page(monkeypatch):
    state = {"page": "results", "played": False}
    channel_url = "https://www.youtube.com/@DrBro"
    video_url = "https://www.youtube.com/watch?v=abc123"

    class Item:
        def __init__(self, name, url=None, action=None):
            self.name, self.url, self.action = name, url, action

        def window_text(self):
            return self.name

        def is_visible(self):
            return True

        def legacy_properties(self):
            return {"Value": self.url}

        def invoke(self):
            if self.action:
                self.action()

        def select(self):
            self.invoke()

    class Document:
        def descendants(self, control_type):
            if state["page"] == "results" and control_type == "Hyperlink":
                return [
                    Item("Dr Bro Shorts @drbro_shorts", "https://www.youtube.com/@drbro_shorts"),
                    Item("Dr Bro Verified @DrBro", channel_url, lambda: state.update(page="channel")),
                ]
            if state["page"] == "channel" and control_type == "TabItem":
                return [Item("Videos", action=lambda: state.update(page="videos"))]
            if state["page"] == "videos" and control_type == "Hyperlink":
                return [Item("A verified video", video_url, lambda: state.update(page="watch"))]
            if state["page"] == "watch" and control_type == "Button":
                return [Item("Pause keyboard shortcut k")]
            return []

    urls = {
        "results": "https://www.youtube.com/results?search_query=Dr+Bro",
        "channel": channel_url,
        "videos": channel_url + "/videos",
        "watch": video_url,
    }
    document = Document()
    controls = SessionControls([])

    def page(browser=None, expected_url=None):
        url = urls[state["page"]]
        assert browser == "chrome"
        if expected_url and expected_url != url:
            raise ValueError("Not loaded yet")
        assert urlparse(url).hostname == "www.youtube.com"
        return None, document, url

    monkeypatch.setattr(controls, "page", page)
    result = controls.play_channel_video("chrome", "Dr.Bro")
    assert result["url"] == video_url and state["page"] == "watch"

from nisha.actions import WebsiteActions
from nisha.dialogue import is_action_intent
from nisha.music import spotify_request
from nisha.orchestration import split_compound


def test_splits_compound_commands_into_ordered_app_and_web_steps():
    request = "close all windows, open Spotify play sad songs and by the check all new email and write draft reply for all"
    assert split_compound(request) == [
        "close all windows",
        "open Spotify play sad songs",
        "check all new email",
        "write draft reply for all",
    ]
    assert is_action_intent(request)


def test_established_chrome_search_workflow_keeps_its_existing_route():
    assert split_compound(
        "Please open Chrome and search for lecture notes then open the first result"
    ) == []


def test_compound_request_routes_actions_to_native_app_and_website_adapters(core):
    calls = []
    core.pc_control.launch_and_focus = (
        lambda _desktop, app: calls.append(("app", app))
        or f"Focused and verified {app} is the foreground window."
    )
    core.actions = WebsiteActions(lambda url, **_kwargs: calls.append(("web", url)) or True)
    result = core.chat("open Chrome and open Wikipedia", core.new_session())
    assert calls == [
        ("app", "chrome"),
        ("web", "https://www.wikipedia.org/"),
    ]
    assert "Step 1: open Chrome" in result and "Step 2: open Wikipedia" in result


def test_mood_conversation_routes_to_spotify_search_request():
    request = "Today I am stressed after college so play some song in Spotify"
    assert split_compound(request) == []
    assert is_action_intent(request)
    assert spotify_request(request) == "search_play:calm relaxing music"


def test_spotify_accepts_direct_mood_and_open_then_play_phrasing():
    assert spotify_request("play sad songs in Spotify") == "search_play:sad songs"
    assert spotify_request("open Spotify play sad songs") == "search_play:sad songs"


def test_open_spotify_and_play_song_keeps_context_and_calls_playback(core):
    request = "open Spotify and play some song"
    assert split_compound(request) == []
    calls = []
    core.music.search_and_play = lambda query, open_first=False: calls.append(
        (query, open_first)
    ) or "Searched Spotify and started the uniquely identified result."

    result = core.chat(request, core.new_session())

    assert calls == [("popular songs", True)]
    assert "started" in result
    assert "I haven't done that action" not in result


def test_ordinary_conversation_is_not_split_into_actions():
    assert split_compound("I want to learn how to open apps and play music") == []
    assert not is_action_intent("I want to learn how to open apps and play music")
    assert split_compound("I was thinking maybe I should open Chrome") == []

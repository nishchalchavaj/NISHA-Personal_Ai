from types import SimpleNamespace

from nisha.connections import Routine
from nisha.live_weather import LiveWeather, weather_request
from nisha.music import SpotifyControl, spotify_request
from nisha.pc_control import PCControl
from nisha.preferences import Preferences
from nisha.window_actions import Window


def test_spoken_spacing_still_runs_saved_routine(core, tmp_path):
    config = core.connections.load()
    config.routines = [Routine.model_validate({
        "name": "TimePass", "trigger": "Let's Timepass",
        "steps": [{"action": "open_path", "target": str(tmp_path)}],
    })]
    core.connections.save(config.model_dump_json())
    opened = []
    core.workflows.desktop.open_path = lambda path: opened.append(path)
    result = core.chat("Let's time pass.", core.new_session())
    assert "Asked Windows to open" in result
    assert opened == [tmp_path]
    assert not core.gateway.calls


class Response:
    def __init__(self, data):
        self.data = data

    def raise_for_status(self):
        pass

    def json(self):
        return self.data


class WeatherClient:
    def __init__(self):
        self.calls = []

    def get(self, url, params):
        self.calls.append((url, params))
        if "geocoding" in url:
            return Response({"results": [{
                "name": "Nargund", "admin1": "Karnataka", "country": "India",
                "latitude": 15.723, "longitude": 75.387,
            }]})
        return Response({"current": {
            "time": "2026-10-26T23:00", "temperature_2m": 24.5,
            "relative_humidity_2m": 70, "wind_speed_10m": 8,
            "weather_code": 3,
        }})


def test_live_weather_is_sourced_and_not_guessed(core):
    client = WeatherClient()
    core.weather = LiveWeather(client)
    assert weather_request("weather in Nargonda") == "Nargund"
    result = core.chat("weather in Nargonda", core.new_session())
    assert "24.5°C" in result and "Open-Meteo" in result
    assert client.calls[0][1]["countryCode"] == "IN"
    assert not core.gateway.calls


def test_weather_failure_does_not_recycle_an_old_forecast(core):
    class OfflineClient:
        def get(self, url, params):
            raise __import__("httpx").ConnectError("offline")

    core.weather = LiveWeather(OfflineClient())
    result = core.chat("What is weather exactly now?", core.new_session())
    assert "won't guess" in result
    assert not core.gateway.calls


def test_direct_address_preference_is_retained(core):
    prefs = Preferences(core.store)
    prefs.observe("Sir or boss, both.")
    assert prefs.all()["address"]["value"] == "Sir or Boss"
    assert "avoid using the user's given name" in prefs.style("Hello")[0]


class Button:
    def __init__(self, name):
        self.element_info = SimpleNamespace(name=name, control_type="Button")


class SpotifyBackend:
    def __init__(self):
        self.window = Window(1, 2, "Spotify")
        self.playing = False

    def app_windows(self):
        return [self.window]

    def controls(self, window):
        return [Button("Play"), Button("Play")]  # Other playlist buttons are ignored.

    def spotify_player_buttons(self, window):
        return [Button("Pause" if self.playing else "Play")]

    def focus(self, window):
        pass

    def click(self, control):
        self.playing = True


def test_spotify_play_requires_visible_control_confirmation(core):
    backend = SpotifyBackend()
    core.music = SpotifyControl(core.workflows.desktop, PCControl(backend), sleeper=lambda _: None)
    result = core.chat("Play the current song which is paused", core.new_session())
    assert "Spotify now shows Pause" in result
    assert backend.playing
    assert not core.gateway.calls


def test_spotify_without_visible_window_never_claims_playback(core):
    backend = SpotifyBackend()
    backend.app_windows = list
    core.music = SpotifyControl(core.workflows.desktop, PCControl(backend))
    result = core.chat("play music", core.new_session())
    assert "couldn't find a visible Spotify window" in result
    assert not core.gateway.calls


def test_spotify_correction_stays_grounded(core):
    backend = SpotifyBackend()
    core.music = SpotifyControl(core.workflows.desktop, PCControl(backend), sleeper=lambda _: None)
    session = core.new_session()
    core.current_surface[session] = "spotify"
    result = core.chat("You are not playing, Nisha.", session)
    assert "Spotify now shows Pause" in result
    assert not core.gateway.calls


def test_spotify_spoken_shortcuts_use_player_controls():
    assert spotify_request("Click on the pause button.", "spotify") == "play"
    assert spotify_request("Open Spotify and Space.") == "open_play"


def test_spotify_visible_window_keeps_followup_context(core):
    backend = SpotifyBackend()
    backend.spotify_player_buttons = lambda window: []
    core.music = SpotifyControl(core.workflows.desktop, PCControl(backend))
    session = core.new_session()
    assert "couldn't identify one accessible Play button" in core.chat("Play the song", session)
    assert core.current_surface[session] == "spotify"
    assert spotify_request("Click on the pause button.", core.current_surface[session]) == "play"


def test_spotify_waits_for_player_controls_after_launch(core):
    backend = SpotifyBackend()
    original = backend.spotify_player_buttons
    reads = 0
    elapsed = 0.0

    def delayed_buttons(window):
        nonlocal reads
        reads += 1
        return [] if reads < 3 else original(window)

    def advance(seconds):
        nonlocal elapsed
        elapsed += seconds

    backend.spotify_player_buttons = delayed_buttons
    desktop = SimpleNamespace(open_app=lambda name: None)
    control = SpotifyControl(
        desktop, PCControl(backend), sleeper=advance, clock=lambda: elapsed
    )
    result = control.play(open_first=True)
    assert "Spotify now shows Pause" in result
    assert reads >= 4


def test_uncertain_open_command_accepts_repeated_app_name(core, monkeypatch):
    launched = []
    monkeypatch.setattr(
        core.pc_control, "launch_and_focus",
        lambda desktop, name: launched.append(name) or "Focused and verified Google Chrome is the foreground window.",
    )
    session = core.new_session()
    assert "audio wasn't clear" in "".join(core.stream("open Chrome", session, uncertain=True))
    result = core.chat("Chrome.", session)
    assert "Focused and verified" in result
    assert launched == ["chrome"]
    assert not core.gateway.calls

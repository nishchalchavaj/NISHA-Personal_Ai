"""Grounded Spotify playback through visible, accessible controls."""

import re
from time import monotonic, sleep

from nisha.errors import NishaError
from nisha.pc_control import PCControl, normalize


def spotify_request(text, current_app=""):
    value = re.sub(r"\s+", " ", text.casefold()).strip(" .!?")
    value = re.sub(r"[, ]+(?:nisha|neesha|nishaa|nisa|meesha)$", "", value).strip(" ,")
    mood = None
    if re.search(r"\b(?:stressed|stressful|overwhelmed|exhausted|tired|rough day)\b", value):
        mood = "calm relaxing music"
    elif re.search(r"\b(?:sad|down|unhappy|heartbroken)\b", value):
        mood = "sad songs"
    elif re.search(r"\b(?:happy|excited|energetic|great mood)\b", value):
        mood = "upbeat feel good songs"
    if re.search(r"\b(?:play|put on|start)\b", value) and re.search(
        r"\b(?:spotify|songs?|music)\b", value
    ):
        app_and_query = re.search(
            r"\b(?:open|launch|start)\s+spotify\b.{0,24}\bplay\s+(?P<query>.+)$",
            value,
        )
        if app_and_query:
            query = app_and_query["query"].strip(" .,!?")
            if query in {"song", "songs", "some song", "some music", "music"}:
                query = mood or "popular songs"
            return "search_play:" + query[:120]
        explicit = re.search(
            r"\b(?:play|put on|start)\s+(?:(?:me|some|a|the)\s+)*(?P<query>.+?)\s+(?:in|on)\s+spotify\b",
            value,
        )
        if explicit:
            query = explicit["query"].strip(" .,!?")
            if query in {"song", "songs", "music", "some song", "some music"} or query in {"a song", "a music"}:
                query = mood or "popular songs"
            return "search_play:" + query[:120]
        if mood and re.search(r"\b(?:play|put on|start)\b", value):
            return "search_play:" + mood
    if re.fullmatch(r"(?:please )?(?:open|opens|launch|start) spotify(?:,? (?:and|then) play(?: (?:a|the|current))? (?:song|music))?", value):
        return "open_play" if " play" in value else "open"
    if re.fullmatch(r"(?:please )?(?:play|resume) (?:the |a |my |current |paused )*(?:song|music)(?: which is paused)?(?: (?:in|on) spotify)?", value):
        return "play"
    if re.fullmatch(r"(?:please )?(?:just )?click (?:on )?(?:that |the )?pause button to play (?:it|the song)", value):
        return "play"
    if current_app.casefold() == "spotify" and re.fullmatch(
        r"(?:please )?(?:just )?click (?:on )?(?:that |the )?(?:pause|play) button",
        value,
    ):
        return "play"
    if re.fullmatch(r"(?:please )?(?:open|launch|start) spotify (?:and|then) (?:press )?space", value):
        return "open_play"
    if current_app.casefold() == "spotify" and value in {
        "you are not playing", "you are not playing just play",
        "you are not playing, just play", "you're not playing",
        "no it's not", "no, it's not", "no its not", "no, its not",
        "it's not done yet", "just play",
    }:
        return "play"
    return None


class SpotifyControl:
    def __init__(self, desktop, pc_control=None, sleeper=sleep, clock=monotonic):
        self.desktop = desktop
        self.pc_control = pc_control or PCControl()
        self.sleeper = sleeper
        self.clock = clock
        self.last_window_visible = False

    def play(self, open_first=False):
        self.last_window_visible = False
        if open_first:
            try:
                self.desktop.open_app("spotify")
            except (NishaError, OSError) as exc:
                return f"I couldn't open Spotify: {exc}"
        try:
            backend = self.pc_control._backend()
            deadline = self.clock() + (8 if open_first else 0)
            while True:
                try:
                    window = self.pc_control._window(backend, "spotify")
                    self.last_window_visible = True
                    break
                except NishaError:
                    if self.clock() >= deadline:
                        return "I couldn't find a visible Spotify window, so I couldn't play or verify music."
                    self.sleeper(0.2)
            player_buttons = getattr(backend, "spotify_player_buttons", None)
            backend.focus(window)
            controls_deadline = self.clock() + (10 if open_first else 3)
            while True:
                try:
                    controls = player_buttons(window) if player_buttons else backend.controls(window)
                except NishaError:
                    controls = []
                buttons = [c for c in controls if c.element_info.control_type == "Button"]
                play_buttons = [c for c in buttons if normalize(c.element_info.name) in {"play", "play button", "resume"}]
                pause_buttons = [c for c in buttons if normalize(c.element_info.name) in {"pause", "pause button"}]
                if play_buttons or pause_buttons or self.clock() >= controls_deadline:
                    break
                self.sleeper(0.3)
            if len(play_buttons) != 1:
                if len(pause_buttons) == 1:
                    return "Spotify shows a Pause control, which suggests playback is active. I can't verify the sound output."
                return "I couldn't identify one accessible Play button in Spotify, so I can't confirm playback."
            backend.focus(window)
            backend.click(play_buttons[0])
            deadline = self.clock() + 2
            while self.clock() < deadline:
                self.sleeper(0.15)
                try:
                    controls = player_buttons(window) if player_buttons else backend.controls(window)
                except NishaError:
                    continue
                if any(
                    c.element_info.control_type == "Button"
                    and normalize(c.element_info.name) in {"pause", "pause button"}
                    for c in controls
                ):
                    return "Clicked Spotify's Play button; Spotify now shows Pause. I can't verify the sound output."
            return "Clicked Spotify's Play button, but I couldn't verify that playback started."
        except (NishaError, OSError) as exc:
            return f"I couldn't control or verify Spotify playback: {exc}"

    def open(self):
        return self.pc_control.launch_and_focus(self.desktop, "spotify")

    def search_and_play(self, query, open_first=False):
        """Search Spotify and play only when one result Play control is identifiable."""
        self.last_window_visible = False
        try:
            if open_first:
                self.desktop.open_app("spotify")
            backend = self.pc_control._backend()
            deadline = self.clock() + (8 if open_first else 0)
            while True:
                try:
                    window = self.pc_control._window(backend, "spotify")
                    self.last_window_visible = True
                    break
                except NishaError:
                    if self.clock() >= deadline:
                        return "I couldn't find a visible Spotify window, so I couldn't search or play music."
                    self.sleeper(0.2)
            backend.focus(window)
            fields = [
                item for item in backend.controls(window)
                if item.element_info.control_type == "Edit"
                and "search" in normalize(item.element_info.name).split()
            ]
            if len(fields) != 1:
                return "Spotify is open, but I couldn't identify one safe search field. No search or playback action was made."
            if not backend.type_text(fields[0], query):
                return "Spotify didn't confirm the search text, so I didn't try to play a result."
            fields[0].set_focus()
            backend.press("{ENTER}")
            self.sleeper(1.2)
            controls = backend.controls(window)
            candidates = [
                item for item in controls
                if item.element_info.control_type == "Button"
                and normalize(item.element_info.name) in {"play", "play result", "play song"}
            ]
            outside_player = []
            for item in candidates:
                parent = item
                in_player = False
                for _ in range(8):
                    try:
                        parent = parent.parent()
                        if normalize(parent.element_info.name) == "player controls":
                            in_player = True
                            break
                    except (AttributeError, OSError, RuntimeError):
                        in_player = True
                        break
                if not in_player:
                    outside_player.append(item)
            if len(outside_player) != 1:
                return (
                    f"Searched Spotify for {query}. I couldn't identify one unique matching Play control, "
                    "so I left the results open for you to choose."
                )
            backend.focus(window)
            backend.click(outside_player[0])
            deadline = self.clock() + 2
            while self.clock() < deadline:
                self.sleeper(0.15)
                buttons = getattr(backend, "spotify_player_buttons", None)
                if buttons and any(
                    item.element_info.control_type == "Button"
                    and normalize(item.element_info.name) in {"pause", "pause button"}
                    for item in buttons(window)
                ):
                    return f"Searched Spotify for {query} and started the uniquely identified result. Spotify now shows Pause; I can't verify the sound output."
            return f"Searched Spotify for {query} and selected its unique Play result, but playback wasn't confirmed."
        except (NishaError, OSError, ImportError) as exc:
            return f"I couldn't search or play Spotify music: {exc}"

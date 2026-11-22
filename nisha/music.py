"""Grounded Spotify playback through visible, accessible controls."""

import re
from time import monotonic, sleep

from nisha.errors import NishaError
from nisha.pc_control import PCControl, normalize


def spotify_request(text, current_app=""):
    value = re.sub(r"\s+", " ", text.casefold()).strip(" .!?")
    value = re.sub(r"[, ]+(?:nisha|neesha|nishaa|nisa|meesha)$", "", value).strip(" ,")
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

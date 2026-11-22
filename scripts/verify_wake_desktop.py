"""Cached local ASR -> Qt wake -> conversation attention with preserved context."""

import logging
import os
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from time import sleep

os.environ["QT_QPA_PLATFORM"] = "offscreen"

import numpy as np
from faster_whisper.audio import decode_audio
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication
from verify_listening import SyntheticStream

from nisha.actions import WebsiteActions
from nisha.core import NishaCore
from nisha.settings import load_settings
from nisha.ui.app import NishaWindow
from nisha.ui.listener import ContinuousListener
from nisha.voice import WindowsSpeech


class Gateway:
    def stream(self, _alias, _messages):
        yield "YouTube was sent to your browser."

    def close(self):
        pass


class PacedStream(SyntheticStream):
    def read(self, frames):
        sleep(0.09)  # Base stream sleeps 0.01s: use the actual microphone cadence.
        return super().read(frames)


def main():
    manual = "--manual" in sys.argv
    enrolled = "--enrolled" in sys.argv
    if "--debug" in sys.argv:
        logging.basicConfig(level=logging.INFO)
    settings = load_settings()
    app = QApplication([])
    with TemporaryDirectory(prefix="desktop-wake-check-", dir=settings.data_dir) as directory:
        root = Path(directory)
        browser_calls = []
        core = NishaCore(
            settings.model_copy(update={"data_dir": root, "online_visuals": False}),
            Gateway(),
            actions=WebsiteActions(lambda url, new: browser_calls.append(url) or True),
        )
        window = NishaWindow(core, start_listener=False, background_enabled=True)
        window.device_poll_timer.stop()
        previous = window.session
        core.store.exchange(previous, "Old question", "Old reply", cloud_allowed=False)
        clips = []
        phrases = (
            [
                "Open Facebook.",
                "Hey Nisha.",
                "Nisha, open YouTube.",
                "What site did you open?",
                "Goodbye.",
            ]
            if manual
            else [
                "This is background discussion.",
                "Hey Nisha.",
                "Nisha, open YouTube.",
                "What site did you open?",
                "Goodbye.",
            ]
        )
        for index, phrase in enumerate(phrases):
            wav = root / f"speech-{index}.wav"
            WindowsSpeech(settings.voice.rate).save(phrase, wav)
            audio = decode_audio(str(wav), sampling_rate=16000)
            clips.append(
                np.concatenate(
                    [np.zeros(4800, dtype=np.float32), audio, np.zeros(16000, dtype=np.float32)]
                )
            )
        listener = ContinuousListener(settings.voice)
        if enrolled:
            from nisha.listening import SpeechDetector
            from nisha.voice_profile import VoiceProfile

            profile = VoiceProfile(settings.data_dir)
            take = next(entry for entry in profile.entries() if entry["kind"] == "wake")
            clips[1] = np.pad(profile.audio(take), (4800, 32000))
            listener.engine.personal_model_path = profile.model_path
            listener.engine.detector_factory = SpeechDetector
        window.listener = listener
        batches = [np.concatenate(clips[:3]), clips[3], clips[4]]
        listener.engine.stream_factory = lambda **_kw: PacedStream(batches.pop(0))
        listener.wake.connect(window.wake_received)
        listener.opened.connect(window.open_from_wake)
        listener.command.connect(window.heard_command)
        listener.uncertain.connect(window.heard_uncertain)
        errors, calls, wakes, dismissals, openings = [], [], [], [], []
        listener.command.connect(lambda text: calls.append((window.session, text)))
        window.start_speech = lambda *_: None  # Test ASR/dispatch; no speaker playback.
        listener.error.connect(errors.append)
        listener.wake.connect(lambda: wakes.append(window.session))
        listener.opened.connect(
            lambda: openings.append(
                window.isVisible() and not window.voice_awake and not listener.engine.gate.awake
            )
        )
        if "--debug" in sys.argv:
            original_transcribe = listener.engine.speech.transcribe

            def transcribe(audio):
                text = original_transcribe(audio)
                print(f"Decoded {len(audio) / 16000:.1f}s: {text!r}", flush=True)
                return text

            listener.engine.speech.transcribe = transcribe
            listener.state.connect(lambda state: print("Listener:", state, flush=True))
            listener.command.connect(lambda text: print("Command:", text, flush=True))
            listener.uncertain.connect(lambda text: print("Uncertain:", text, flush=True))

        def dismiss():
            assert not listener.engine.stopped.is_set() and not listener.engine.muted.is_set()
            window.close_requested()
            dismissals.append(not window.isVisible() and not listener.engine.gate.awake)
            listener.engine.stop()

        listener.dismissed.connect(dismiss)

        def start_turn(text, **_kwargs):
            window.current_user = text
            window.current_reply = core.chat(text, window.session)
            window.render()
            listener.engine.resume(follow_up=True)

        window.start_turn = start_turn
        if manual:
            window.open_fresh()
            assert not listener.engine.gate.awake and not listener.engine.blocked()
        else:
            window.hide_to_background()
        loop = QEventLoop()
        listener.finished.connect(loop.quit)
        QTimer.singleShot(45000, loop.quit)
        listener.start()
        loop.exec()
        try:
            assert listener.wait(2000), (
                f"Wake listening did not finish: calls={calls}, wakes={wakes}, dismissals={dismissals}, errors={errors}"
            )
            app.processEvents()
            assert not errors, errors
            assert len(calls) == 2 and window.session == previous, calls
            assert calls[0][0] == calls[1][0] == window.session
            assert browser_calls == ["https://www.youtube.com/"]
            assert len(wakes) == (2 if manual else 1) and all(
                wake == window.session for wake in wakes
            ), wakes
            assert openings == ([] if manual else [True]), openings
            assert dismissals == [True] and window.in_background
            assert len(core.store.history(window.session)[1]) == 6
            print(
                "PASS: manual opening stayed idle and ignored Open Facebook until Hey Nisha; the following command and follow-up kept the existing context, then Goodbye hid the window. Real cached ASR; browser/TTS playback simulated."
                if manual
                else "PASS: the first Hey Nisha opened the hidden window quietly; the next prefixed command started conversation and preserved context for its follow-up. Goodbye hid the window without muting. Real cached ASR; browser/TTS playback simulated."
            )
            if enrolled:
                print(
                    "PASS: the actual first saved wake take reached the Qt window through personal detection and local ASR without swallowing the following command."
                )
        finally:
            listener.engine.stop()
            listener.wait()
            window.quit_application()
            app.processEvents()
            core.close()


if __name__ == "__main__":
    main()

"""Local stop-word ASR and muted native SAPI cancellation; no PC actions."""

import os
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
from time import monotonic, sleep
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
from faster_whisper.audio import decode_audio

from nisha.listening import ListenerEngine, WakeGate, output_control
from nisha.settings import load_settings
from nisha.speech_worker import BoundedSpeech
from nisha.voice import WindowsSpeech


def native_cancel(settings, directory, speech=None, audio=None, wake=False, quiet=False):
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    import pyttsx3
    from PySide6.QtWidgets import QApplication

    from nisha.core import NishaCore
    from nisha.ui.app import NishaWindow
    from nisha.ui.listener import ContinuousListener

    class Gateway:
        def stream(self, *_):
            yield "This is a disposable speech cancellation check. " * 100

        def close(self):
            pass

    app = QApplication.instance() or QApplication([])
    core = NishaCore(settings.model_copy(update={"data_dir": directory}), gateway=Gateway())
    window = NishaWindow(core, start_listener=False, background_enabled=True)
    unexpected_commands = []
    if audio is None:
        listener = ListenerEngine(
            settings.voice, lambda _: None, lambda _: None, lambda: None, lambda _: None
        )
        window.listener = SimpleNamespace(engine=listener, isRunning=lambda: False)
    else:
        window.listener = ContinuousListener(settings.voice)
        listener = window.listener.engine
        listener.speech = speech

        class SyntheticMic:
            offset = 0

            def __enter__(self):
                return self

            def __exit__(self, *_):
                pass

            def read(self, frames):
                sleep(0.1)  # Actual capture cadence, not accelerated test audio.
                if not listener.output_active.is_set():
                    return np.zeros((frames, 1), dtype=np.float32), False
                block = audio[self.offset : self.offset + frames]
                self.offset += frames
                return np.pad(block, (0, frames - len(block))).reshape(-1, 1), False

        mic = SyntheticMic()
        listener.stream_factory = lambda **kwargs: mic
        window.listener.interrupted.connect(window.interrupt_reply)
        window.listener.wake.connect(window.wake_received)
        window.listener.dismissed.connect(window.close_requested)
        window.listener.quiet_requested.connect(window.quiet_requested)
        window.listener.command.connect(unexpected_commands.append)
        window.listener.start()
    window.show()
    session = window.session
    if audio is not None:
        deadline = monotonic() + 20
        while not listener.ready.is_set() and monotonic() < deadline:
            app.processEvents()
            sleep(0.01)
        assert listener.ready.is_set(), "Local speech model did not become ready before playback."
    started = Event()
    native_done = []
    original_init = pyttsx3.init

    def muted_engine():
        engine = original_init()
        engine.setProperty("volume", 0)  # Check the real engine without audible playback.
        engine.connect("started-utterance", lambda **kwargs: started.set())
        original_end = engine.endLoop

        def end_loop():
            engine.endLoop = original_end
            original_end()
            native_done.append(bool(engine.proxy._driver._tts.WaitUntilDone(500)))

        engine.endLoop = end_loop
        return engine

    try:
        with patch("pyttsx3.init", muted_engine):
            window.start_turn("Explain this cancellation check", voice=True)
            deadline = monotonic() + 10
            while not started.is_set() and monotonic() < deadline:
                app.processEvents()
                sleep(0.01)
            assert started.is_set(), "Native SAPI did not start."
            assert listener.output_active.is_set() and not listener.blocked()
            start = monotonic()
            if audio is None:
                window.close()
            else:
                deadline = start + 5
                while window.busy() and monotonic() < deadline:
                    app.processEvents()
                    sleep(0.01)
            assert window.worker.wait(2000), "Native speech did not stop promptly."
            elapsed = monotonic() - start
            app.processEvents()
            assert native_done == [True], "SAPI still had queued speech."
            assert not listener.output_active.is_set() and not listener.blocked()
            if audio is None:
                assert not listener.gate.awake and window.in_background
                print(
                    f"PASS: window close purged actual muted SAPI playback in {elapsed:.2f}s; background listener retained.",
                    flush=True,
                )
            else:
                assert window.isVisible() and (
                    not listener.gate.awake if quiet else listener.gate.awake
                )
                if quiet:
                    assert core.interaction.quiet and not window.voice_awake
                assert window.session == session
                assert not unexpected_commands
                assert elapsed < 3, elapsed
                control_name = "Don't disturb" if quiet else "Hey Nisha" if wake else "Enough"
                print(
                    f"PASS: {control_name} through rolling capture, actual local ASR, Qt signal and native SAPI stopped output in {elapsed:.2f}s; same conversation retained.",
                    flush=True,
                )
    finally:
        if window.busy():
            window.worker.requestInterruption()
            window.worker.wait(3000)
        window.quit_application()
        if audio is not None:
            assert window.listener.wait(3000), "Test listener did not stop."
        app.processEvents()
        core.close()


def main():
    settings = load_settings()
    with TemporaryDirectory(prefix="interrupt-test-", dir=settings.data_dir) as directory:
        root = Path(directory)
        clips = []
        for index, phrase in enumerate(
            [
                "Stop.",
                "Enough.",
                "That's enough.",
                "Hey Nisha stop speaking.",
                "Be quiet.",
                "Don't disturb me.",
                "Hey Nisha.",
            ]
        ):
            path = root / f"control-{index}.wav"
            WindowsSpeech(settings.voice.rate).save(phrase, path)
            clips.append((phrase, decode_audio(str(path), sampling_rate=16000)))
        speech = BoundedSpeech(settings.voice)
        if "--debug" in sys.argv:
            original_transcribe = speech.transcribe_control

            def transcribe_control(audio):
                started = monotonic()
                text = original_transcribe(audio)
                print(
                    f"Decoded control in {monotonic() - started:.2f}s: {text!r}; {speech.last_metrics}",
                    flush=True,
                )
                return text

            speech.transcribe_control = transcribe_control
        try:
            speech.prepare()
            for phrase, audio in clips:
                start = monotonic()
                text = speech.transcribe_control(np.pad(audio, (3200, 4800)))
                control = output_control(
                    text, "This is a detailed explanation about planets.", WakeGate()
                )
                confident = not speech.last_uncertain or speech.last_metrics.get(
                    "control_confident"
                )
                if control == "wake":
                    confident = not speech.last_uncertain or speech.last_wake_confident
                assert control and confident, (phrase, text, speech.last_metrics)
                print(
                    f"PASS: local control {phrase!r} recognized in {monotonic() - start:.2f}s.",
                    flush=True,
                )
            if "--quiet-only" not in sys.argv:
                native_cancel(settings, root)
                native_cancel(settings, root, speech, np.pad(clips[1][1], (3200, 32000)))
                native_cancel(
                    settings, root, speech, np.pad(clips[-1][1], (3200, 32000)), wake=True
                )
            native_cancel(settings, root, speech, np.pad(clips[5][1], (3200, 32000)), quiet=True)
        finally:
            speech.close()


if __name__ == "__main__":
    main()

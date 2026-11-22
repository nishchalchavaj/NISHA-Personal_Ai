"""Real cached local ASR -> listener controls -> Qt context reset; no live microphone."""

import os
from pathlib import Path
from queue import Queue
from tempfile import TemporaryDirectory
from threading import Thread
from time import monotonic, sleep

os.environ["QT_QPA_PLATFORM"] = "offscreen"

import numpy as np
from faster_whisper.audio import decode_audio
from PySide6.QtWidgets import QApplication

from nisha.core import NishaCore
from nisha.settings import load_settings
from nisha.ui.app import NishaWindow
from nisha.ui.listener import ContinuousListener
from nisha.voice import WindowsSpeech


class Gateway:
    def stream(self, *_):
        yield "I'm here, Boss."

    def close(self):
        pass


def main():
    settings = load_settings()
    app = QApplication([])
    with TemporaryDirectory(prefix="fresh-check-", dir=settings.data_dir) as directory:
        root = Path(directory)
        core = NishaCore(settings.model_copy(update={"data_dir": root}), Gateway())
        window = NishaWindow(core, start_listener=False, background_enabled=True)
        listener = ContinuousListener(settings.voice)
        engine = listener.engine
        engine.audio_queue = Queue()
        window.listener = listener
        listener.fresh_requested.connect(window.start_fresh_requested)
        listener.wake.connect(window.wake_received)
        errors, commands = [], []
        listener.error.connect(errors.append)

        def command(text):
            commands.append((window.session, text))
            core.chat(text, window.session)
            engine.resume(follow_up=True)

        listener.command.connect(command)
        phrases = [
            "Start fresh.",
            "Start a new conversation.",
            "Let's talk new.",
            "Let's talk about a different topic.",
            "Have some other conversation than this.",
            "Hey Nisha.",
            "Hello there.",
        ]
        clips = []
        for index, phrase in enumerate(phrases):
            path = root / f"phrase-{index}.wav"
            WindowsSpeech(settings.voice.rate).save(phrase, path)
            clips.append(np.pad(decode_audio(str(path), sampling_rate=16000), (3200, 4800)))
        decoder = Thread(target=engine.decode_loop)
        decoder.start()

        def wait_for(predicate, timeout=20):
            deadline = monotonic() + timeout
            while not predicate() and monotonic() < deadline:
                app.processEvents()
                sleep(0.01)
            assert predicate(), f"Pipeline timed out; errors={errors}, commands={commands}"
            app.processEvents()

        try:
            wait_for(engine.ready.is_set)
            window.bring_forward()
            window.wake_received()
            for output in [False, True]:
                for phrase, audio in zip(phrases[:5], clips[:5]):
                    old = window.session
                    core.store.exchange(old, "Old topic", "Old response", cloud_allowed=False)
                    if output:
                        engine.begin_output("A detailed explanation about planets.")
                    else:
                        engine.resume(
                            follow_up=True, wake_only=True
                        )  # Thinking also accepts reset.
                    engine.audio_queue.put((audio, engine.epoch, None, output))
                    wait_for(lambda old=old: window.session != old)
                    assert not core.store.history(window.session)[1]
                    assert core.store.history(old)[1]
                    assert engine.gate.awake and not engine.output_active.is_set()
                    print(
                        f"PASS: {phrase!r} reset context during {'output' if output else 'thinking'}.",
                        flush=True,
                    )
            session = window.session
            engine.audio_queue.put((clips[-2], engine.epoch, None, False))
            wait_for(lambda: window.pending_wake_ack)
            assert window.session == session
            engine.audio_queue.put((clips[-1], engine.epoch, None, False))
            wait_for(lambda: bool(commands))
            assert commands[-1][0] == session
            assert len(core.store.history(session)[1]) == 2
            assert not errors
            print(
                "PASS: calling NISHA kept the fresh session; the next unprefixed question used it."
            )
        finally:
            engine.stop()
            decoder.join(5)
            assert not decoder.is_alive()
            window.quit_application()
            app.processEvents()
            core.close()


if __name__ == "__main__":
    main()

"""Real local wake/follow-up STT with synthetic audio; no microphone or playback."""

from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np
from faster_whisper.audio import decode_audio

from nisha.actions import WebsiteActions
from nisha.core import NishaCore
from nisha.listening import ListenerEngine
from nisha.settings import load_settings
from nisha.voice import WindowsSpeech


class SyntheticStream:
    def __init__(self, audio):
        self.audio = audio
        self.offset = 0

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def read(self, frames):
        from time import sleep

        sleep(0.01)
        end = self.offset + frames
        block = self.audio[self.offset : end]
        self.offset = end
        if len(block) < frames:
            block = np.pad(block, (0, frames - len(block)))
        return block.reshape(-1, 1), False


def main():
    settings = load_settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix="wake-test-", dir=settings.data_dir) as directory:
        root = Path(directory).resolve()
        browser_calls, commands, errors = [], [], []
        core = NishaCore(
            settings.model_copy(update={"data_dir": root}),
            actions=WebsiteActions(lambda url, new: browser_calls.append(url) or True),
        )
        session = core.new_session()
        clips = []
        for index, phrase in enumerate(
            [
                "This is a background conversation about the weather.",
                "Nisha, open YouTube.",
                "What website did you just open?",
            ]
        ):
            wav = root / f"phrase-{index}.wav"
            WindowsSpeech(settings.voice.rate).save(phrase, wav)
            audio = decode_audio(str(wav), sampling_rate=16000)
            clips.append(
                np.concatenate(
                    [np.zeros(4800, dtype=np.float32), audio, np.zeros(16000, dtype=np.float32)]
                )
            )

        engine = None

        def command(text):
            commands.append(text)
            reply = core.chat(text, session)
            print(f"You: {text}\nNISHA: {reply}", flush=True)
            if len(commands) == 2:
                engine.stop()
            else:
                engine.resume(follow_up=True)

        engine = ListenerEngine(
            settings.voice,
            command,
            lambda state: None,
            lambda: None,
            errors.append,
            stream_factory=lambda **kw: SyntheticStream(
                np.concatenate([clips.pop(0), clips.pop(0)]) if len(clips) == 3 else clips.pop(0)
            ),
        )
        try:
            engine.run()
            assert not errors, errors
            assert len(commands) == 2, commands
            assert browser_calls == ["https://www.youtube.com/"], browser_calls
            history = core.store.history(session)[1]
            assert len(history) == 4  # background audio was discarded
            assert "youtube" in history[-1]["content"].lower()
            print(
                "PASS: cached Whisper wake word, ignored background, browser action and local follow-up context."
            )
        finally:
            core.close()


if __name__ == "__main__":
    main()

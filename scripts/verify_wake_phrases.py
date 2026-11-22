"""Check short wakes through the installed VAD and cached local ASR, without a mic."""

from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np
from faster_whisper.audio import decode_audio

from nisha.listening import SpeechDetector, UtteranceBuffer, WakeGate
from nisha.settings import load_settings
from nisha.voice import WhisperSpeech, WindowsSpeech


def main():
    settings = load_settings().voice
    speech = WhisperSpeech(settings)
    speech.prepare()
    with TemporaryDirectory(prefix="nisha-wake-phrases-") as directory:
        for index, phrase in enumerate(["Hey Nisha", "Nisha", "Hey Neesha", "Neesha", "Goodbye"]):
            wav = Path(directory) / f"phrase-{index}.wav"
            WindowsSpeech(settings.rate).save(phrase, wav)
            source = decode_audio(str(wav), sampling_rate=16000)
            source = np.concatenate([np.zeros(8000), source, np.zeros(32000)]).astype(np.float32)
            detector, buffer = SpeechDetector(settings.vad_threshold), UtteranceBuffer(settings)
            utterances = []
            for offset in range(0, len(source) - 1599, 1600):
                block = source[offset : offset + 1600]
                utterance = buffer.feed(block, detector.feed(block))
                if utterance is not None:
                    utterances.append(speech.transcribe(utterance))
            gate = WakeGate(aliases=settings.wake_aliases)
            if phrase == "Goodbye":
                gate.extend()
            accepted = [gate.accept(text) for text in utterances]
            print(
                f"{phrase!r}: {utterances!r}, accepted={accepted!r}, uncertain={speech.last_uncertain}",
                flush=True,
            )
            assert utterances, f"VAD dropped {phrase!r}"
            assert not speech.last_uncertain, f"Low-confidence {phrase!r}"
            assert gate.sleep_requested if phrase == "Goodbye" else gate.awake
    print("PASS: short wake and close phrases passed real segmentation and local ASR.")


if __name__ == "__main__":
    main()

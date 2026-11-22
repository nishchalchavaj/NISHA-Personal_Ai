"""Local synthetic STT -> Core -> LLM -> TTS check, without microphone or playback."""

from pathlib import Path
from tempfile import TemporaryDirectory

from nisha.core import NishaCore
from nisha.settings import load_settings
from nisha.voice import WhisperSpeech, WindowsSpeech


def main():
    settings = load_settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix="voice-test-", dir=settings.data_dir) as directory:
        root = Path(directory).resolve()
        assert root.is_relative_to(settings.data_dir.resolve())
        core = NishaCore(settings.model_copy(update={"data_dir": root}))
        try:
            speech = WindowsSpeech(settings.voice.rate)
            stt = WhisperSpeech(settings.voice)
            input_wav, output_wav = root / "question.wav", root / "answer.wav"
            speech.save("What is two plus two?", input_wav)
            assert input_wav.stat().st_size > 1000
            print("PASS: Windows TTS created synthetic question audio.", flush=True)
            text = stt.transcribe(str(input_wav))
            assert "plus" in text.lower(), "Whisper failed to transcribe the synthetic question."
            print("PASS: cached local Whisper transcribed the question.", flush=True)
            reply = core.chat(text, core.new_session())
            assert "four" in reply.lower() or "4" in reply
            speech.save(reply, output_wav)
            assert output_wav.stat().st_size > 1000
            print("PASS: local Core/model answered and Windows TTS synthesized the response.")
        finally:
            core.close()


if __name__ == "__main__":
    main()

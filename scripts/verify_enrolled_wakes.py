"""Check the user's previously saved wake takes through the real local decoder."""

from nisha.listening import WakeGate, resembles_standalone_wake
from nisha.settings import load_settings
from nisha.speech_worker import BoundedSpeech
from nisha.voice_profile import PersonalWakeModel, VoiceProfile


def main():
    settings = load_settings()
    profile = VoiceProfile(settings.data_dir)
    model = PersonalWakeModel.load(profile.model_path)
    entries = [entry for entry in profile.entries() if entry["kind"] == "wake"]
    speech = BoundedSpeech(settings.voice)
    gate = WakeGate(settings.voice.wake_word, aliases=settings.voice.wake_aliases)
    accepted = 0
    try:
        speech.prepare()
        for index, entry in enumerate(entries, 1):
            audio = profile.audio(entry)
            personal = model.matches(audio)
            text = speech.transcribe(audio)
            explicit = bool(gate.pattern.search(text))
            trusted = not speech.last_uncertain or speech.last_wake_confident or personal
            ok = bool(
                explicit and trusted or personal and resembles_standalone_wake(text, settings.voice)
            )
            accepted += ok
            if not ok:
                print(f"Unrecognized wake transcript for take {index}: {text!r}", flush=True)
            print(
                f"Take {index}: accepted={ok}; ASR wake={explicit}; acoustic match={personal}",
                flush=True,
            )
        assert entries and accepted == len(entries), (
            f"Only {accepted}/{len(entries)} saved wake takes detected."
        )
        print(
            f"PASS: {accepted}/{len(entries)} existing personal wake recordings detected locally. No recordings changed or microphone opened."
        )
    finally:
        speech.close()


if __name__ == "__main__":
    main()

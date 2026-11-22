"""Evaluate optional local vocabulary on saved clips without changing configuration."""

import json

from nisha.settings import load_settings
from nisha.speech_worker import BoundedSpeech
from nisha.voice_profile import VoiceProfile


def main():
    settings = load_settings()
    baseline = settings.data_dir / "reports/full-check-2026-10-11/personal-speech-details.json"
    old = {row["sample"]: row for row in json.loads(baseline.read_text(encoding="utf-8"))}
    vocabulary = settings.voice.hotwords + ", Wikipedia, wikipedia.org, dot org, reply, shorter"
    speech = BoundedSpeech(settings.voice.model_copy(update={"hotwords": vocabulary}))
    profile = VoiceProfile(settings.data_dir)
    rows = []
    try:
        speech.prepare()
        for entry in profile.entries():
            if entry["kind"] != "command":
                continue
            text = speech.transcribe(profile.audio(entry))
            rows.append(
                {
                    "sample": entry["audio"],
                    "expected": entry["text"],
                    "baseline": old[entry["audio"]]["transcript"],
                    "candidate": text,
                }
            )
    finally:
        speech.close()
    output = baseline.with_name("vocabulary-experiment.json")
    output.write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
    for row in rows:
        if row["candidate"] != row["baseline"]:
            print(json.dumps(row, ensure_ascii=True), flush=True)
    print("Experiment complete. No configuration, audio, or model weights changed.")


if __name__ == "__main__":
    main()

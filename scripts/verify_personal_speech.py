"""Audit saved command/non-wake takes locally, without actions or changing recordings."""

import json
import re
from datetime import datetime
from time import monotonic

from nisha.listening import WakeGate, resembles_standalone_wake
from nisha.settings import load_settings
from nisha.speech_worker import BoundedSpeech
from nisha.voice_profile import PersonalWakeModel, VoiceProfile


def words(text):
    return re.findall(r"\w+", text.casefold())


def edit_distance(left, right):
    previous = list(range(len(right) + 1))
    for row, word in enumerate(left, 1):
        current = [row]
        for column, other in enumerate(right, 1):
            current.append(
                min(current[-1] + 1, previous[column] + 1, previous[column - 1] + (word != other))
            )
        previous = current
    return previous[-1]


def main():
    settings = load_settings()
    profile = VoiceProfile(settings.data_dir)
    model = PersonalWakeModel.load(profile.model_path)
    speech = BoundedSpeech(settings.voice)
    gate = WakeGate(settings.voice.wake_word, aliases=settings.voice.wake_aliases)
    rows = []
    try:
        speech.prepare()
        for entry in profile.entries():
            if entry["kind"] not in {"command", "negative"}:
                continue
            start = monotonic()
            audio = profile.audio(entry)
            transcript = speech.transcribe(audio)
            explicit = bool(gate.pattern.search(transcript))
            personal = model.matches(audio)
            trusted = not speech.last_uncertain or speech.last_wake_confident or personal
            wake = bool(
                explicit
                and trusted
                or personal
                and resembles_standalone_wake(transcript, settings.voice)
            )
            reference = words(entry["text"])
            row = {
                "kind": entry["kind"],
                "expected": entry["text"],
                "transcript": transcript,
                "word_error_rate": round(
                    edit_distance(reference, words(transcript)) / max(1, len(reference)), 3
                ),
                "uncertain": speech.last_uncertain,
                "wake_detected": wake,
                "seconds": round(monotonic() - start, 2),
                "sample": entry["audio"],
            }
            rows.append(row)
            print(
                f"Take {len(rows)}: kind={entry['kind']}; WER={row['word_error_rate']}; uncertain={row['uncertain']}; wake={wake}",
                flush=True,
            )
    finally:
        speech.close()
    folder = (
        settings.data_dir
        / "reports"
        / ("full-check-" + datetime.now().astimezone().date().isoformat())
    )
    folder.mkdir(parents=True, exist_ok=True)
    output = folder / "personal-speech-details.json"
    output.write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
    negatives = [row for row in rows if row["kind"] == "negative"]
    commands = [row for row in rows if row["kind"] == "command"]
    false_wakes = [row for row in negatives if row["wake_detected"]]
    print(
        f"Saved-take audit: {len(commands)} commands; {len(negatives)} non-wakes; {len(false_wakes)} false wakes. Details: {output}",
        flush=True,
    )
    assert not false_wakes, (
        "A saved non-wake take would falsely activate NISHA. See local detailed report."
    )
    mean = sum(row["word_error_rate"] for row in commands) / max(1, len(commands))
    print(
        f"Command mean word-error rate: {mean:.1%}. Labels are user-entered and may not exactly match recorded words; no actions executed or ASR weights retrained.",
        flush=True,
    )


if __name__ == "__main__":
    main()

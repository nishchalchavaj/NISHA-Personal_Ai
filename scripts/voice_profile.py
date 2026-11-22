"""Inspect/train a local personal wake profile, or evaluate labeled command clips."""

import argparse
import json
import re

from nisha.settings import load_settings
from nisha.speech_worker import BoundedSpeech
from nisha.voice_profile import VoiceProfile


def word_errors(expected, actual):
    left, right = [re.findall(r"\w+", text.casefold()) for text in [expected, actual]]
    previous = list(range(len(right) + 1))
    for index, word in enumerate(left, 1):
        current = [index]
        for column, candidate in enumerate(right, 1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[column] + 1,
                    previous[column - 1] + (word != candidate),
                )
            )
        previous = current
    return previous[-1], len(left)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["status", "train", "train-neural", "evaluate"])
    args = parser.parse_args()
    settings = load_settings()
    profile = VoiceProfile(settings.data_dir)
    entries = profile.entries()
    if args.action == "status":
        print(
            json.dumps(
                {
                    "directory": str(profile.root),
                    "samples": {
                        kind: sum(e["kind"] == kind for e in entries)
                        for kind in ["wake", "negative", "command"]
                    },
                    "personal_model_present": profile.model_path.exists(),
                    "neural_model_present": profile.neural_model_path.exists(),
                    "whisper_weights_retrained": False,
                },
                indent=2,
            )
        )
    elif args.action == "train":
        print(json.dumps(profile.train(), indent=2))
    elif args.action == "train-neural":
        print(json.dumps(profile.train_neural(), indent=2))
    else:
        samples = [e for e in entries if e["kind"] == "command"]
        if not samples:
            raise ValueError("No labeled command recordings yet. Use Ctrl+R to save some first.")
        speech = BoundedSpeech(settings.voice)
        results, total_errors, total_words = [], 0, 0
        try:
            for entry in samples:
                actual = speech.transcribe(profile.audio(entry))
                errors, words = word_errors(entry["text"], actual)
                total_errors += errors
                total_words += words
                results.append(
                    {
                        "audio": entry["audio"],
                        "expected": entry["text"],
                        "recognized": actual,
                        "word_errors": errors,
                        "reference_words": words,
                        "uncertain": speech.last_uncertain,
                    }
                )
            report = {
                "word_error_rate": total_errors / max(1, total_words),
                "samples": results,
                "whisper_weights_retrained": False,
            }
            destination = profile.root / "command-evaluation.json"
            destination.write_text(
                json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            print(
                f"Local evaluation saved: {destination}\nWord error rate: {report['word_error_rate']:.1%}"
            )
        finally:
            speech.close()


if __name__ == "__main__":
    main()

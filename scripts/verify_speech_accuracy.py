"""Check real local ASR on synthetic commands, including a confusable phrase."""

import json
import re
from pathlib import Path
from tempfile import TemporaryDirectory
from time import monotonic

from nisha.actions import WebsiteActions
from nisha.listening import WakeGate
from nisha.settings import load_settings
from nisha.voice import WhisperSpeech, WindowsSpeech


def main():
    settings = load_settings()
    cases = [
        ("Open YouTube.", ["youtube"]),
        ("Open your book.", ["book"]),
        ("Hey Nisha, open example dot org.", ["example", "org"]),
        ("Write Python code to add two numbers.", ["python", "code"]),
        ("Write a note in Notepad about solar power.", ["notepad", "solar"]),
        ("Write an email to Alex about tomorrow's meeting.", ["email", "alex"]),
    ]
    recognizer = WhisperSpeech(settings.voice)
    rows = []
    with TemporaryDirectory(prefix="speech-check-", dir=settings.data_dir) as folder:
        for index, (phrase, required) in enumerate(cases):
            path = Path(folder) / f"command-{index}.wav"
            WindowsSpeech(settings.voice.rate).save(phrase, path)
            start = monotonic()
            transcript = recognizer.transcribe(str(path))
            normalized = re.sub(r"[^a-z0-9]", "", transcript.casefold())
            assert all(word in normalized for word in required), (phrase, transcript)
            if "your book" in phrase.casefold():
                assert "youtube" not in normalized
            if index in {0, 2}:
                calls = []

                class Audit:
                    def audit(self, *args):
                        pass

                request = WakeGate().accept(transcript) if index == 2 else transcript
                WebsiteActions(lambda url, new, calls=calls: calls.append(url) or True).handle(
                    request, [], Audit()
                )
                assert calls == [
                    "https://www.youtube.com/" if index == 0 else "https://example.org"
                ], (phrase, transcript, calls)
            row = {
                "spoken": phrase,
                "heard": transcript,
                "uncertain": recognizer.last_uncertain,
                "seconds": round(monotonic() - start, 2),
            }
            rows.append(row)
            print(json.dumps(row), flush=True)
    output = settings.data_dir / "speech-verification.json"
    output.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    print("PASS: six real large-v3 local ASR cases. Report:", output, flush=True)


if __name__ == "__main__":
    main()

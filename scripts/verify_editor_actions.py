"""Opt-in real editor launches with fresh synthetic files; no email is sent."""

import argparse

from nisha.core import NishaCore
from nisha.settings import load_settings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--launch", action="store_true", help="Open Notepad, Word and VS Code")
    args = parser.parse_args()
    if not args.launch:
        parser.error("Use --launch to explicitly open the real editor applications.")
    settings = load_settings()
    settings = settings.model_copy(update={"data_dir": settings.data_dir / "editor-verification"})
    core = NishaCore(settings)
    session = core.new_session()
    cases = [
        (
            "Write a note in Notepad",
            "NISHA editor check\nThis file was written locally and opened in Notepad.",
        ),
        (
            "Write a short note in Word",
            "# NISHA editor check\nThis document was written locally and opened in Microsoft Word.",
        ),
        ("Write Python code to add two numbers", "def add(a, b):\n    return a + b\n"),
    ]
    try:
        for command, content in cases:
            core.generate_content = lambda *args, content=content: content
            reply = core.chat(command, session)
            assert "and opened it in" in reply, reply
            print(reply.split("\n", 1)[0], flush=True)
        print(
            "PASS: real editor launch requests. Check their windows for the synthetic files.",
            flush=True,
        )
    finally:
        core.close()


if __name__ == "__main__":
    main()

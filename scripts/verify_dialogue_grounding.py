"""Exercise real local conversation and safe action follow-ups without touching user apps."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from time import monotonic

from nisha.core import NishaCore
from nisha.settings import load_settings


def main():
    settings = load_settings()
    results = []
    with TemporaryDirectory(prefix="dialogue-check-", dir=settings.data_dir) as folder:
        settings = settings.model_copy(update={"data_dir": Path(folder), "online_visuals": False})
        core = NishaCore(settings)
        try:
            opened = []
            core.workflows.desktop.app_path = lambda name: "test.exe" if name == "chrome" else None
            core.workflows.desktop.open_app = opened.append
            session = core.new_session()
            for prompt in (
                "Hey Nisha, how are you?",
                "I'm a bit frustrated because opening Chrome failed before.",
                "What did I just tell you was frustrating?",
                "Open Chrome",
                "Open",
            ):
                start = monotonic()
                reply = core.chat(prompt, session)
                results.append({"prompt": prompt, "reply": reply, "seconds": round(monotonic() - start, 2)})
            assert opened == ["chrome", "chrome"]
            assert "chrome" in results[2]["reply"].casefold()
            assert "chrome" in results[4]["reply"].casefold()
            assert "haven't" not in results[3]["reply"].casefold()
        finally:
            core.close()
    output = Path("data/reports/dialogue-live-results.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(results, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()

"""Real local model checks for persistent style learning and reference retrieval."""

from pathlib import Path
from tempfile import TemporaryDirectory

from nisha.core import NishaCore
from nisha.settings import load_settings


def main():
    settings = load_settings()
    with TemporaryDirectory(prefix="learning-check-", dir=settings.data_dir) as directory:
        local = settings.model_copy(update={"data_dir": Path(directory)})
        core = NishaCore(local)
        core.chat("Tell me short", core.new_session())
        core.close()
        core = NishaCore(local)
        try:
            session = core.new_session()
            brief = core.chat("What is photosynthesis?", session)
            print("Brief:", brief, flush=True)
            assert len(brief.split()) <= 75, len(brief.split())
            detailed = core.chat("Explain photosynthesis in detail with examples", session)
            print("Detail words:", len(detailed.split()), flush=True)
            assert len(detailed.split()) > len(brief.split())
            assert core.preferences.style("What is friction?")[1]
            core.knowledge.add_text(
                "Synthetic Zephyr notes",
                "The Zephyr prototype uses a 48 volt motor and a carbon frame.",
            )
            answer = core.chat(
                "What voltage does the Zephyr prototype motor use?", core.new_session()
            )
            print("Reference answer:", answer, flush=True)
            assert "48" in answer
            assert core.preferences.all()["verbosity"]["value"] == "brief"
        finally:
            core.close()
    print(
        "PASS: preferences survived restart; brief/detail control and local knowledge retrieval verified."
    )


if __name__ == "__main__":
    main()

"""Exercise real local review in a windowless worker, using synthetic data only."""

from pathlib import Path
from tempfile import TemporaryDirectory

from nisha.conversation_learning import ConversationLearning
from nisha.core import NishaCore
from nisha.settings import load_settings
from nisha.storage import Store


def main():
    settings = load_settings()
    with TemporaryDirectory(
        prefix="conversation-review-check-", dir=settings.data_dir
    ) as directory:
        local = settings.model_copy(update={"data_dir": Path(directory)})
        core = NishaCore(local)
        session = core.new_session()
        for statement, prior in [
            ("My mother's name is Maya. Rahul is my college friend.", ""),
            ("Today Rahul and I argued at college about our project.", ""),
            ("I prefer that you call me Boss during our conversations.", ""),
            (
                "That is wrong. Search for Dr Bro inside YouTube instead of Google.",
                "I searched Google.",
            ),
        ]:
            core.learning.observe(session, statement, prior)
        core.end_conversation(session)
        # Launch independently of the desktop's event loop or microphone.
        core.learning.launch()
        worker = core.learning.process
        assert worker is not None
        assert worker.wait(timeout=240) == 0
        restored = Store(core.store.path)
        print("Synthetic learned memories:", [m["text"] for m in restored.memories()], flush=True)
        categories = {m["category"] for m in restored.memories()}
        assert {
            "personal_profile",
            "personal_event",
            "conversation_preference",
            "user_correction",
        } <= categories, categories
        assert all(not m["cloud_allowed"] for m in restored.memories())
        assert not ConversationLearning(local, restored).pending()
        mother = core.chat("What is my mother's name?", core.new_session())
        friend = core.chat("Who is my college friend?", core.new_session())
        print("Synthetic recall:", mother, "|", friend, flush=True)
        assert "Maya" in mother
        assert "Rahul" in friend
        core.learning.forget_learned()
        assert not any(m["source"] == "local_conversation_review" for m in restored.memories())
        # Avoid starting a new review as this synthetic temporary database is removed.
        core._touched_sessions.clear()
        core.close()
    print(
        "PASS: local background review learned family, friends, dated events, preferences and corrections; restart retrieval and deletion verified.",
        flush=True,
    )


if __name__ == "__main__":
    main()

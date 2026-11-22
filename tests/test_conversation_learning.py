import json
from io import BytesIO
from types import SimpleNamespace

import pytest

from nisha.context import token_bound
from nisha.conversation_learning import ConversationLearning, grounded_memory
from nisha.errors import ModelUnavailable
from nisha.storage import Store


class Reviewer:
    def __init__(self, category="personal_profile", key="friend_rahul", topic="friend Rahul"):
        self.category, self.key, self.topic = category, key, topic
        self.calls = []

    def generate(self, alias, messages, schema, **kwargs):
        self.calls.append((alias, messages, schema))
        rows = json.loads(messages[-1]["content"])["user_statements"]
        return json.dumps(
            {
                "items": [
                    {
                        "observation_id": row["observation_id"],
                        "category": self.category,
                        "key": self.key,
                        "topic": self.topic,
                        "quote": row["content"],
                    }
                    for row in rows
                ]
            }
        )


def test_local_review_rejects_unrelated_personal_claims():
    assert not grounded_memory("personal_profile", "user_name", "I saved my male friends, female friends, my best friend, all those names.")
    assert not grounded_memory("personal_profile", "mother_name", "What's up baby?")
    assert not grounded_memory("personal_event", "friend_name", "Nothing, just chilling.")
    assert not grounded_memory("personal_profile", "assistant_instruction", "Thank you for watching.")
    assert grounded_memory("personal_profile", "friend_vishal", "My friend name is Vishal.")


def review(core, text, reviewer=None, session=None):
    session = session or core.new_session()
    core.learning.observe(session, text)
    core.end_conversation(session)
    reviewer = reviewer or Reviewer()
    while core.learning.step(reviewer):
        pass
    return reviewer


def test_personal_relationships_persist_with_actual_evidence_and_reach_next_chat(core):
    review(core, "Rahul is my college friend.")
    restored = Store(core.store.path)
    item = restored.memories()[0]
    assert "Rahul is my college friend." in item["text"]
    assert item["source"] == "local_conversation_review" and not item["cloud_allowed"]
    with restored.connect() as db:
        assert (
            db.execute("SELECT quote FROM memory_evidence").fetchone()[0]
            == "Rahul is my college friend."
        )
    core.chat("Tell me about my friend Rahul", core.new_session())
    assert "Rahul is my college friend." in str(core.gateway.calls[-1][1])


def test_latest_personal_correction_updates_same_slot_across_sessions(core):
    review(core, "Rahul is my college friend.")
    first_id = core.store.memories()[0]["id"]
    review(core, "Rahul and I are no longer friends.")
    memories = core.store.memories()
    assert len(memories) == 1 and memories[0]["id"] == first_id
    assert "no longer friends" in memories[0]["text"]


def test_daily_events_remain_separate_and_dated(core):
    reviewer = Reviewer("personal_event", "college_event", "college life")
    review(core, "Today I had a fight with Rahul at college.", reviewer)
    review(core, "Today Rahul and I made up.", reviewer)
    assert len(core.store.memories()) == 2
    assert all("User account (20" in m["text"] for m in core.store.memories())
    assert len(core.interaction.profile()) == 2


def test_correction_retrieval_contains_user_replacement_and_labels_old_answer(core):
    session = core.new_session()
    core.store.exchange(session, "Search Dr Bro", "Searching Google", False)
    core.learning.observe(
        session, "No, search Dr Bro inside YouTube instead of Google.", "Searching Google"
    )
    core.end_conversation(session)
    reviewer = Reviewer("user_correction", "youtube_search", "YouTube search")

    # Ignore the unrelated imported legacy question in the simulated extraction.
    def generate(alias, messages, schema, **kwargs):
        row = json.loads(messages[-1]["content"])["user_statements"][-1]
        return json.dumps(
            {
                "items": [
                    {
                        "observation_id": row["observation_id"],
                        "category": "user_correction",
                        "key": "youtube_search",
                        "topic": "YouTube search",
                        "quote": row["content"],
                    }
                ]
            }
        )

    reviewer.generate = generate
    assert core.learning.step(reviewer)
    item = core.store.search("YouTube search")[0]
    assert "inside YouTube" in item["text"]
    assert "context only, may be wrong" in item["text"]
    assert "Searching Google" in item["text"]


def test_generic_lasting_preference_is_used_without_keyword_match(core):
    review(
        core,
        "I prefer to be called Boss when we chat.",
        Reviewer("conversation_preference", "address_as", "addressing user"),
    )
    core.chat("What is gravity?", core.new_session())
    assert "called Boss" in str(core.gateway.calls[-1][1])


def test_interrupted_generation_keeps_trusted_input_for_review(core):
    session = core.new_session()
    stream = core.stream("Rahul is my college friend.", session)
    next(stream)
    stream.close()
    assert core.store.history(session)[1] == []
    core.end_conversation(session)
    assert core.learning.step(Reviewer())
    assert "Rahul" in core.store.memories()[0]["text"]


@pytest.mark.parametrize("bad", ["not json", '{"items": null}', '{"items": [false]}'])
def test_bad_extraction_retains_cursor_and_original_input_for_retry(core, bad):
    session = core.new_session()
    core.learning.observe(session, "Rahul is my college friend.")
    core.end_conversation(session)
    reviewer = Reviewer()
    reviewer.generate = lambda *args, **kwargs: bad
    assert not core.learning.step(reviewer)
    with core.store.connect() as db:
        job = db.execute("SELECT * FROM conversation_reviews").fetchone()
        assert job["cursor"] == 0 and job["status"] == "pending" and job["lease_until"] == 0
        db.execute("UPDATE conversation_reviews SET retry_after=0")
    restarted = ConversationLearning(core.settings, Store(core.store.path))
    assert restarted.step(Reviewer())
    assert restarted.store.memories()


def test_invented_or_assistant_only_evidence_is_discarded(core):
    session = core.new_session()
    core.learning.observe(session, "Hello", "Rahul is my college friend.")
    core.end_conversation(session)
    reviewer = Reviewer()
    reviewer.generate = lambda *args, **kwargs: json.dumps(
        {
            "items": [
                {
                    "observation_id": 1,
                    "category": "personal_profile",
                    "key": "friend_rahul",
                    "topic": "friend Rahul",
                    "quote": "Rahul is my college friend.",
                }
            ]
        }
    )
    assert core.learning.step(reviewer)
    assert core.store.memories() == []


def test_one_invented_memory_does_not_block_verified_memory(core):
    session = core.new_session()
    core.learning.observe(session, "Rahul is my college friend.")
    core.end_conversation(session)
    reviewer = Reviewer()

    def generate(*args, **kwargs):
        row = json.loads(args[1][-1]["content"])["user_statements"][0]
        return json.dumps({"items": [
            {"observation_id": row["observation_id"], "category": "personal_profile",
             "key": "friend_rahul", "topic": "friend Rahul", "quote": row["content"]},
            {"observation_id": row["observation_id"], "category": "personal_profile",
             "key": "invented_fact", "topic": "invented fact", "quote": "My unspoken secret is Mars."},
        ]})

    reviewer.generate = generate
    assert core.learning.step(reviewer)
    assert len(core.store.memories()) == 1
    assert "Rahul is my college friend." in core.store.memories()[0]["text"]


@pytest.mark.parametrize(
    "text",
    [
        "My password is secret123.",
        "Write an email about my family.",
        "Suppose Rahul is my friend.",
        "Don't remember my sister's name is Maya.",
        "Approved standalone task to Gemini: My family is from Mars.",
    ],
)
def test_secrets_artifacts_optout_and_provider_output_are_not_learned(core, text):
    reviewer = review(core, text)
    assert not reviewer.calls and not core.store.memories()


def test_quoted_personal_example_is_not_saved(core):
    review(core, 'Someone said "Rahul is my college friend."')
    assert not core.store.memories()


def test_reviews_are_idempotent_bounded_and_cover_long_inputs(core):
    reviewer = Reviewer("personal_event", "life_event", "daily life")
    session = core.new_session()
    text = "Today I worked on my project. " * 110
    core.learning.observe(session, text)
    core.end_conversation(session)
    while core.learning.step(reviewer):
        pass
    covered = "".join(
        row["content"]
        for _, messages, _ in reviewer.calls
        for row in json.loads(messages[-1]["content"])["user_statements"]
    )
    assert covered == text
    assert all(
        alias == "local_fast" and token_bound(messages) <= core.settings.models[alias].input_budget
        for alias, messages, _ in reviewer.calls
    )
    before = len(core.store.memories())
    core.end_conversation(session)
    assert not core.learning.step(reviewer)
    assert len(core.store.memories()) == before


def test_deleting_learning_cancels_pending_reviews_but_allows_future_learning(core):
    session = core.new_session()
    core.learning.observe(session, "Rahul is my college friend.")
    core.end_conversation(session)
    core.learning.forget_learned()
    assert not core.learning.step(Reviewer())
    core.learning.observe(session, "Arjun is my new friend.")
    core.end_conversation(session)
    assert core.learning.step(Reviewer(key="friend_arjun", topic="friend Arjun"))
    assert "Arjun" in core.store.memories()[0]["text"]
    assert "Rahul" not in str(core.store.memories())


def test_deletion_during_review_cannot_resurrect_learning(core):
    session = core.new_session()
    core.learning.observe(session, "Rahul is my college friend.")
    core.end_conversation(session)
    reviewer = Reviewer()
    generate = reviewer.generate

    def deleting(*args, **kwargs):
        result = generate(*args, **kwargs)
        core.learning.forget_learned()
        return result

    reviewer.generate = deleting
    assert core.learning.step(reviewer)
    assert not core.store.memories()


def test_forget_personal_details_clears_reviewed_relations_and_events(core):
    review(core, "Rahul is my college friend.")
    core.chat("forget my personal details", core.new_session())
    assert not core.interaction.profile()
    assert not core.learning.pending()


def test_pending_review_retains_old_transcript_until_review_is_complete(core):
    session = core.new_session()
    core.store.exchange(session, "Rahul is my college friend.", "Okay", False)
    core.end_conversation(session)
    with core.store.connect() as db:
        db.execute("UPDATE turns SET created_at='2000-01-01T00:00:00+00:00'")
    core.store.prune_transcripts(30)
    assert core.store.history(session)[1]
    assert core.learning.step(Reviewer())
    core.store.prune_transcripts(30)
    with pytest.raises(ValueError):
        core.store.history(session)
    assert core.store.search("Rahul")


def test_model_failure_does_not_change_quiet_or_launch_actions(core):
    core.interaction.set_quiet(True)
    session = core.new_session()
    core.learning.observe(session, "My mother is named Maya.")
    core.end_conversation(session)
    reviewer = Reviewer()

    def unavailable(*args, **kwargs):
        raise ModelUnavailable("Offline")

    reviewer.generate = unavailable
    assert not core.learning.step(reviewer)
    assert core.interaction.quiet and not core.store.memories()


def test_consoleless_desktop_launches_hidden_worker_with_readable_stdin(core, monkeypatch):
    session = core.new_session()
    core.learning.observe(session, "Rahul is my college friend.")
    core.end_conversation(session)
    from nisha import conversation_learning

    monkeypatch.setattr(
        conversation_learning.sys, "executable", r"E:\NISHA\.venv\Scripts\pythonw.exe"
    )
    calls = []
    child = SimpleNamespace(stdin=BytesIO(), poll=lambda: None)

    def spawn(args, **kwargs):
        calls.append((args, kwargs))
        return child

    monkeypatch.setattr(conversation_learning.subprocess, "Popen", spawn)
    core.learning.launch()
    core.learning.launch()
    assert len(calls) == 1
    assert calls[0][0][0].endswith("python.exe")
    assert calls[0][1]["creationflags"] == conversation_learning.subprocess.CREATE_NO_WINDOW


def test_individual_forget_blocks_inflight_recreation_but_accepts_new_statement(core):
    review(core, "Rahul is my college friend.")
    memory = core.store.memories()[0]
    # Reset cursor to simulate recovery of an older in-flight extraction.
    with core.store.connect() as db:
        db.execute("UPDATE conversation_reviews SET cursor=0,status='pending'")
    core.store.forget(memory["id"])
    assert core.learning.step(Reviewer())
    assert not core.store.memories()
    review(core, "Rahul and I are friends again.")
    assert "friends again" in core.store.memories()[0]["text"]


def test_correction_after_interruption_receives_partial_answer_as_context_only(core):
    session = core.new_session()
    stream = core.stream("Hello", session)
    next(stream)
    stream.close()
    core.chat("That is wrong, instead say good morning.", session)
    with core.store.connect() as db:
        row = db.execute(
            "SELECT prior_reply FROM user_observations ORDER BY id DESC LIMIT 1"
        ).fetchone()
    assert row["prior_reply"] == "Hello "


def test_personal_recall_search_excludes_unrelated_correction_and_life_events(core):
    review(core, "My mother's name is Maya.", Reviewer(key="mother_name", topic="mother name"))
    review(
        core,
        "That is wrong, search YouTube instead.",
        Reviewer("user_correction", "youtube", "YouTube search"),
    )
    review(
        core,
        "Today Rahul and I argued at college.",
        Reviewer("personal_event", "college_event", "college life"),
    )
    core.chat("What is my mother's name?", core.new_session())
    prompt = str(core.gateway.calls[-1][1])
    assert "Maya" in prompt and "search YouTube instead" not in prompt and "argued" not in prompt


def test_wrong_model_id_is_recovered_only_from_unique_exact_user_evidence(core):
    session = core.new_session()
    core.learning.observe(session, "My mother's name is Maya.")
    core.learning.observe(session, "Rahul is my college friend.")
    core.end_conversation(session)
    reviewer = Reviewer()
    reviewer.generate = lambda *args, **kwargs: json.dumps(
        {
            "items": [
                {
                    "observation_id": 1,
                    "category": "personal_profile",
                    "key": "friend_rahul",
                    "topic": "friend Rahul",
                    "quote": "Rahul is my college friend.",
                }
            ]
        }
    )
    assert core.learning.step(reviewer)
    with core.store.connect() as db:
        assert db.execute("SELECT observation_id FROM memory_evidence").fetchone()[0] == 2


def test_uncertain_legacy_audio_is_not_imported_as_personal_evidence(core):
    session = core.new_session()
    core.store.exchange(
        session,
        "My friend is imaginary",
        "I heard 'My friend is imaginary', but the audio wasn't clear. Repeat.",
        False,
    )
    core.store.exchange(session, "Rahul is my college friend.", "Okay", False)
    core.learning.queue(session)
    with core.store.connect() as db:
        observations = [row[0] for row in db.execute("SELECT content FROM user_observations")]
    assert observations == ["Rahul is my college friend."]

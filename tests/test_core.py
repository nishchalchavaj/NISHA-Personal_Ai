import pytest

from nisha.context import token_bound
from nisha.errors import ContextTooLarge, ModelUnavailable, PrivacyError


def test_local_conversation_persists_complete_exchange(core):
    session = core.new_session()
    assert core.chat("Hello", session) == "Hello Nishchal."
    _, history = core.store.history(session)
    assert [t["role"] for t in history] == ["user", "assistant"]
    assert all(not t["cloud_allowed"] for t in history)
    assert core.gateway.calls[0][0] == "local_fast"


def test_cloud_requires_explicit_approval_before_any_request(core):
    with pytest.raises(PrivacyError):
        core.chat("Hi", core.new_session(), "cloud")
    assert core.gateway.calls == []


def test_local_only_history_cannot_be_exported_even_after_approval(core):
    session = core.new_session()
    core.chat("Private health details", session)
    with pytest.raises(PrivacyError):
        core.chat("Continue", session, "cloud")
    assert len(core.gateway.calls) == 1


def test_external_task_never_receives_memories_or_base_conversation(core):
    core.store.remember("My project NISHA has a secret password.")
    session = core.new_session()
    core.chat("My private appointment is Tuesday", session)
    captured = []

    def complete(alias, messages):
        captured.append(messages)
        return "Completed task"

    core.gateway.complete = complete
    core.run_task("Explain sorting algorithms", "cloud", approved=True)
    prompt = str(captured[-1])
    assert "secret password" not in prompt
    assert "Tuesday" not in prompt
    assert "sorting algorithms" in prompt


def test_external_tasks_require_per_task_approval(core):
    with pytest.raises(PrivacyError):
        core.run_task("Explain sorting", "cloud")
    assert core.gateway.calls == []


def test_external_tasks_disabled_in_local_installation(core):
    core.settings.external_tasks_enabled = False
    with pytest.raises(PrivacyError):
        core.run_task("Explain sorting", "cloud", approved=True)


def test_failed_stream_does_not_save_partial_exchange(core):
    session = core.new_session()
    core.gateway.fail = True
    with pytest.raises(ModelUnavailable):
        core.chat("Hi", session)
    assert core.store.history(session)[1] == []


def test_message_over_budget_is_rejected_without_request(core):
    with pytest.raises(ContextTooLarge):
        core.chat("x" * 4000, core.new_session())
    assert core.gateway.calls == []


def test_summary_failure_keeps_transcript_and_cursor(core):
    session = core.new_session()
    for i in range(5):
        core.store.exchange(session, f"Fact {i}", "Acknowledged", False)
    core.gateway.summary_fail = True
    core.chat("Continue", session)
    state, history = core.store.history(session)
    assert len(history) == 12
    assert state["summarized_until"] == 0
    assert token_bound(core.gateway.calls[-1][1]) <= core.settings.models["local_fast"].input_budget


def test_successful_summary_is_persisted_without_deleting_turns(core):
    session = core.new_session()
    for i in range(5):
        core.store.exchange(session, f"Fact {i}", "Acknowledged", False)
    core.chat("Continue", session)
    state, history = core.store.history(session)
    assert state["summary"] == "The user is developing NISHA."
    assert state["summarized_until"] > 0
    assert len(history) == 12


def test_correcting_keyed_memory_replaces_old_value(core):
    first = core.store.remember("My name is Nick", key="name")
    second = core.store.remember("My name is Nishchal", key="name")
    assert first == second
    assert len(core.store.memories()) == 1
    assert core.store.memories()[0]["text"] == "My name is Nishchal"
    assert core.store.search("name")[0]["text"] == "My name is Nishchal"


def test_memory_deduplication_deletion_and_durable_backup(core, tmp_path):
    from nisha.storage import Store

    first = core.store.remember("I enjoy coding")
    assert core.store.remember("I enjoy coding") == first
    core.store.backup(tmp_path / "backup.sqlite3")
    restored = Store(tmp_path / "backup.sqlite3")
    assert restored.memories()[0]["id"] == first
    assert core.store.forget(first)
    assert core.store.search("coding") == []
    assert len(restored.memories()) == 1


def test_inactive_transcripts_expire_but_memories_remain(core):
    session = core.new_session()
    core.store.exchange(session, "Old conversation", "Old answer", False)
    core.store.remember("Keep selected preference")
    with core.store.connect() as db:
        db.execute("UPDATE turns SET created_at='2000-01-01T00:00:00+00:00'")
    core.store.prune_transcripts(30)
    with pytest.raises(ValueError):
        core.store.history(session)
    assert len(core.store.memories()) == 1

import pytest

from nisha.interaction import IdleCheckIns, Interaction
from nisha.listening import WakeGate, output_control
from nisha.storage import Store


def test_direct_personal_facts_correct_and_persist_locally(core):
    session = core.new_session()
    core.chat("My name is Arun. My favorite color is blue and I enjoy robotics", session)
    core.chat("Actually, my favorite color is green", session)
    learned = Interaction(Store(core.store.path)).profile()
    assert len(learned) == 3
    assert all(not item["cloud_allowed"] for item in learned)
    assert not any("blue" in item["text"] for item in learned)
    core.chat("What color do I like?", core.new_session())
    assert "green" in str(core.gateway.calls[-1][1])
    assert "Arun" in core.chat("what do you know about me", core.new_session())
    core.chat("forget my personal details", session)
    assert not core.interaction.profile()


def test_named_friends_are_kept_separately_and_recalled_without_model(core):
    for statement in (
        "My friend name is Vishal.",
        "One more friend is Kaif.",
        "Aishwarya is my female friend.",
        "Then Sri Lakshmi is also my female friend.",
        "Barthesh is my best friend.",
    ):
        core.interaction.observe(statement)
    reply = core.chat("Tell all my friends name", core.new_session())
    assert all(name in reply for name in ("Vishal", "Kaif", "Aishwarya", "Sri Lakshmi", "Barthesh"))
    assert not core.gateway.calls
    assert len([m for m in core.store.memories() if (m["key"] or "").startswith("profile:friend:")]) == 5


@pytest.mark.parametrize("question", [
    "Tell all my friends there",
    "Tell my all friends name",
    "Just tell all friends name",
])
def test_recent_friend_list_phrases_never_turn_into_a_draft(core, question):
    for statement in ("Vishal is my friend.", "Barthesh is my best friend.", "Altaf is also my best friend."):
        core.interaction.observe(statement)
    reply = core.chat(question, core.new_session())
    assert all(name in reply for name in ("Vishal", "Barthesh", "Altaf"))
    assert "draft" not in reply.casefold()
    assert not core.gateway.calls


def test_best_and_male_friend_roles_are_not_conflated(core):
    for statement in (
        "Lakshmi Putra is my male friend.",
        "Barthesh is my best friend.",
        "Altaf is also my best friend.",
    ):
        core.interaction.observe(statement)
    reply = core.chat("To know my male best friends", core.new_session())
    assert "Barthesh" in reply and "Altaf" in reply
    assert "Lakshmi Putra" in reply and "male friend" in reply
    assert "genders" in reply and not core.gateway.calls


def test_misheard_name_fragment_cannot_overwrite_actual_name(core):
    core.interaction.observe("My name is Nishchal.")
    assert core.interaction.observe("My name is mine not my name just") == []
    assert core.chat("what is my name", core.new_session()) == "Nishchal."


@pytest.mark.parametrize(
    "text",
    [
        'Here is an example: "My name is Alex"',
        "Write an email: My name is Alex",
        "Suppose my name is Alex",
        "My password is blue and my name is Alex",
        "My favorite color is blue?",
        "If I live in Delhi",
        "Learn this: my name is Alex",
    ],
)
def test_documents_questions_and_secrets_do_not_become_personal_facts(core, text):
    assert not core.interaction.observe(text)
    assert not core.interaction.profile()


def test_quiet_survives_restart_and_wake_until_explicit_resume(core):
    session = core.new_session()
    assert "when you're free" in core.chat("don't disturb me", session)
    assert Interaction(Store(core.store.path)).quiet
    core.new_session()
    assert core.interaction.quiet
    assert "Take your time" in core.chat("just thinking", session)
    core.chat("you can talk now", session)
    assert not core.interaction.quiet


def test_idle_two_checkins_then_quiet_without_inventing_emotions():
    time = [0]
    idle = IdleCheckIns(
        clock=lambda: time[0], first=60, second=120, chooser=lambda options: options[0]
    )
    time[0] = 59
    assert idle.due(True, False) is None
    time[0] = 60
    assert idle.due(False, False) is None
    assert idle.due(True, True) is None
    first = idle.due(True, False)
    assert first == "Hey Boss, what's up?"
    time[0] = 180
    assert idle.due(True, False) != first
    time[0] = 10000
    assert idle.due(True, False) is None
    idle.activity()
    time[0] += 60
    assert idle.due(True, False)
    idle.suppress()
    time[0] += 1000
    assert idle.due(True, False) is None


def test_do_not_disturb_is_distinct_from_hide_and_speaker_echo():
    gate = WakeGate()
    assert output_control("don't disturb me", "Gravity attracts objects", gate) == "quiet"
    assert output_control("Nisha, do not disturb me", "Gravity attracts objects", gate) == "quiet"
    assert output_control("don't disturb me", "don't disturb me", gate) is None

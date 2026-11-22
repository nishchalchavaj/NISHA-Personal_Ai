import pytest


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def test_teacher_dialog_review_comparison_and_delete(app, core):
    from nisha.ui.reinforcement_dialog import ReinforcementDialog

    session = core.new_session()
    core.chat("What is gravity?", session)
    dialog = ReinforcementDialog(core, session)
    dialog.rate(1)
    assert core.reinforcement.latest(session)["reward"] == 1
    dialog.provider.setText("Synthetic teacher")
    dialog.compare.setChecked(True)
    assert dialog.prompt.toPlainText() == "What is gravity?"
    assert "Hello Nishchal." in dialog.preview.toPlainText()
    literal = '<script>alert("not executed")</script> Gravity is an interaction.'
    dialog.answer.setHtml(literal)
    dialog.add_teacher()
    assert len(dialog.rows) == 1 and not dialog.rows[0]["reviewed"]
    assert not core.knowledge.sources()
    dialog.items.setCurrentRow(0)
    assert literal in dialog.preview.toPlainText()
    assert "Hello Nishchal." in dialog.preview.toPlainText()
    dialog.accept_selected()
    assert len(core.reinforcement.preference_pairs()) == 1
    dialog.export()
    assert len(list((core.settings.data_dir / "learning_exports").glob("*.jsonl"))) == 1
    dialog.items.setCurrentRow(0)
    dialog.forget_selected()
    assert not core.reinforcement.teachers() and not core.knowledge.sources()
    dialog.enabled.setChecked(False)
    assert not core.reinforcement.enabled()
    dialog.close()


def test_negative_feedback_reduces_arm_probability(core):
    import random

    policy = core.reinforcement
    for index in range(30):
        session = core.new_session()
        turn = core.store.exchange(session, "Why?", "Example", False)
        policy.record(session, turn, ("explanation", "example"), "Why?", "Example")
        policy.feedback(session, 0)
    rng = random.Random(51)
    chosen = [policy.choose("Why is this useful?", {}, rng)[1] for _ in range(200)]
    assert chosen.count("example") < 5


def test_review_dialog_accepts_a_conversation_teacher(app, core):
    from nisha.ui.reinforcement_dialog import ReinforcementDialog

    teacher = core.reinforcement.propose_teacher("Teacher", "Hello", "Hey! Good to hear from you.")
    dialog = ReinforcementDialog(core, core.new_session())
    dialog.items.setCurrentRow(0)
    dialog.use_as.setCurrentIndex(dialog.use_as.findData("warm"))
    dialog.accept_selected()
    assert core.reinforcement.teachers()[0]["id"] == teacher
    assert core.reinforcement.teachers()[0]["conversation_style"] == "warm"
    assert not core.knowledge.search("Hello")
    dialog.items.setCurrentRow(0)
    assert dialog.use_as.currentData() == "warm"
    dialog.forget_selected()
    assert not core.reinforcement.conversation_examples("Hello", ("social_greeting", "warm"))
    dialog.close()

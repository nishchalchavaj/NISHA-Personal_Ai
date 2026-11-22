import threading
from time import monotonic, sleep

import pytest
from PySide6.QtWidgets import QApplication

from nisha.ui.app import NishaWindow


@pytest.fixture
def window(core, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    core.settings.background_actions = True
    window = NishaWindow(core, start_listener=False)
    window.show()
    app.processEvents()
    yield window
    window.worker = None
    window.quit_application()
    app.processEvents()


def spin_until(condition):
    deadline = monotonic() + 4
    while not condition() and monotonic() < deadline:
        QApplication.processEvents()
        sleep(0.005)
    assert condition()


def test_background_queue_fifo_without_interrupting_chat(window, core, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    calls = []

    def action(text, *args):
        calls.append(text)
        entered.set()
        assert release.wait(3)
        return "Completed synthetic task."

    monkeypatch.setattr(core, "handle_action", action)
    monkeypatch.setattr(window, "busy", lambda: True)
    window.current_reply = "Still explaining"
    window.chat_panel.begin_turn()
    pair = window.chat_panel.current_pair
    assert window.queue_action("Open synthetic one")
    assert entered.wait(2)
    assert window.queue_action("Open synthetic two")
    assert window.current_reply == "Still explaining"
    assert window.chat_panel.current_pair is pair
    release.set()
    spin_until(lambda: window.action_job is None and not window.action_queue)
    assert calls == ["Open synthetic one", "Open synthetic two"]
    assert len(window.action_results) == 2
    assert window.current_reply == "Still explaining"
    monkeypatch.setattr(window, "busy", lambda: False)
    spoken = []
    monkeypatch.setattr(window, "start_speech", lambda text, mode: spoken.append((text, mode)))
    monkeypatch.setattr(
        window.visual_panel, "set_response", lambda *_: pytest.fail("Action receipt opened glass")
    )
    window.show_action_results()
    assert len(window.action_results) == 1
    window.show_action_results()
    assert not window.action_results
    assert spoken == [("Completed synthetic task.", "action")] * 2


def test_action_result_is_spoken_briefly_and_logged_fully_without_glass(window, monkeypatch):
    spoken = []
    monkeypatch.setattr(window, "start_speech", lambda text, mode: spoken.append((text, mode)))
    monkeypatch.setattr(
        window.visual_panel, "set_response", lambda *_: pytest.fail("Action receipt opened glass")
    )
    details = "Asked Explorer to open C: in the same window.\nAdditional details stay in chat."
    window.action_completed(window.session, "Go to local disk C", details)
    assert spoken == [("Asked Explorer to open C: in the same window.", "action")]
    assert window.chat_panel.messages[-1]["content"] == details


def test_status_notice_uses_chat_and_speech_not_glass(window, monkeypatch):
    spoken = []
    monkeypatch.setattr(window, "start_speech", lambda text, mode: spoken.append((text, mode)))
    monkeypatch.setattr(
        window.visual_panel, "set_response", lambda *_: pytest.fail("Notice opened glass")
    )
    window.show_notice("Local connections saved. Open setup for details.")
    QApplication.processEvents()
    assert window.chat_panel.messages[-1]["content"] == "Local connections saved. Open setup for details."
    assert spoken == [("Local connections saved.", "action")]


def test_background_queue_bound_cancel_and_ui_controls(window, monkeypatch):
    monkeypatch.setattr(window, "start_next_action", lambda: None)
    for i in range(10):
        assert window.queue_action(f"Open synthetic {i}")
    assert len(window.action_queue) == 8
    assert window.queue_action("cancel background tasks")
    assert not window.action_queue
    for command in ["open learning", "open my CCTV camera", "close visuals", "close nisha window"]:
        assert not window.queue_action(command)
    opened = []
    monkeypatch.setattr(window, "learning_dialog", lambda: opened.append(True))
    window.input.setText("open learning")
    window.submit()
    assert opened == [True]


def test_queued_voice_action_has_no_spoken_filler(window, monkeypatch):
    spoken, states, notices = [], [], []
    monkeypatch.setattr(window, "start_next_action", lambda: None)
    monkeypatch.setattr(window, "start_speech", lambda *args: spoken.append(args))
    monkeypatch.setattr(window, "set_state", states.append)
    monkeypatch.setattr(window.chat_panel, "record_background", lambda *args: notices.append(args))
    window.voice_awake = True
    window.heard_command("Open Chrome")
    assert not spoken
    assert states == ["Working in background"]
    assert notices == [("Open Chrome", "Queued.")]


def test_new_conversation_discards_queued_tasks_and_late_results(window, monkeypatch):
    monkeypatch.setattr(window, "start_next_action", lambda: None)
    old = window.session
    window.queue_action("Open synthetic")
    window.new_conversation()
    window.action_completed(old, "Open synthetic", "Old result")
    assert not window.action_queue and not window.action_results


def test_typed_messages_are_fifo_even_when_microphone_muted(window, monkeypatch):
    window.muted = True
    monkeypatch.setattr(window, "busy", lambda: True)
    for text in ["First thought", "Second thought"]:
        window.input.setText(text)
        window.submit()
    assert [item[1] for item in window.pending_typed] == ["First thought", "Second thought"]
    monkeypatch.setattr(window, "busy", lambda: False)
    dispatched = []
    monkeypatch.setattr(window, "start_turn", lambda text: dispatched.append(text))
    window.input.setText("unfinished draft")
    window.finish_turn()
    assert dispatched == ["First thought"]
    assert window.input.text() == "unfinished draft"
    window.finish_turn()
    assert dispatched == ["First thought", "Second thought"]


def test_queued_action_keeps_reference_history_from_enqueue(window, core, monkeypatch):
    monkeypatch.setattr(window, "start_next_action", lambda: None)
    core.store.exchange(window.session, "Earlier", "Original context", False)
    window.queue_action("Open that website")
    core.store.exchange(window.session, "Later", "Different context", False)
    assert window.action_queue[0][3][-1]["content"] == "Original context"

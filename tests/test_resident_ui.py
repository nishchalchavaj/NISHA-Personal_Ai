from types import SimpleNamespace

import pytest
from PySide6.QtCore import QEventLoop, QPoint, QRect, Qt, QTimer
from PySide6.QtWidgets import QApplication

from nisha.listening import ListenerEngine
from nisha.media import MediaAsset
from nisha.settings import VoiceSettings
from nisha.ui.app import NishaWindow
from nisha.ui.resident import DesktopInstance, LoginStartup
from nisha.ui.window import center_monitor


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(core, app, monkeypatch):
    from nisha.voice import WindowsSpeech

    # Keep UI regression runs silent while still exercising speech-worker flow.
    monkeypatch.setattr(WindowsSpeech, "speak", lambda *_args, **_kwargs: None)
    window = NishaWindow(core, start_listener=False, background_enabled=True)
    engine = ListenerEngine(
        VoiceSettings(), lambda _: None, lambda _: None, lambda: None, lambda _: None
    )
    window.listener = SimpleNamespace(engine=engine, isRunning=lambda: not engine.stopped.is_set())
    window.show()
    app.processEvents()
    yield window
    if (
        window.worker
        and hasattr(window.worker, "isRunning")
        and hasattr(window.worker, "wait")
        and window.worker.isRunning()
    ):
        window.worker.wait(2000)
    window.worker = None
    window.quit_application()
    app.processEvents()


def test_wake_prefixed_stop_control_interrupts_current_response(window):
    interrupted = []
    window.interrupt_reply = lambda: interrupted.append(True)
    assert window.ui_command("Hey Neesha, stop") and interrupted == [True]


def test_busy_submit_accepts_wake_prefixed_stop(window):
    interrupted = []
    window.interrupt_reply = lambda: interrupted.append(True)
    original_busy = window.busy
    window.busy = lambda: True
    window.input.setText("Hey NISHA, enough")
    window.submit()
    window.busy = original_busy
    assert interrupted == [True] and not window.input.text()


def test_disabled_external_tasks_do_not_open_approval_dialog(window, core):
    core.settings.external_tasks_enabled = False
    notices = []
    window.show_notice = notices.append
    window.external_task_dialog()
    assert notices and "disabled" in notices[0].casefold()


def test_close_hides_and_wake_resumes_existing_conversation(window, core, app):
    previous = window.session
    core.store.exchange(previous, "Old question", "Old answer", cloud_allowed=False)
    window.current_user, window.current_reply = "Old question", "Old answer"
    window.render()
    window.listener.engine.gate.extend()
    window.close()
    app.processEvents()
    assert not window.isVisible() and window.in_background and not window.closing
    assert not window.listener.engine.stopped.is_set() and not window.listener.engine.gate.awake
    window.wake_received()
    assert window.isVisible() and not window.in_background
    assert not window.voice_awake and not window.listener.engine.gate.awake
    assert not window.pending_wake_ack
    assert window.session == previous and window.current_reply == "Old answer"
    assert core.store.history(previous)[1][1]["content"] == "Old answer"
    assert len(core.store.history(window.session)[1]) == 2
    assert window.session_file.read_text() == window.session
    assert core.learning.pending()


def test_bye_and_fresh_queue_reviews_without_resetting_profile_or_quiet(window, core):
    session = window.session
    core.store.exchange(session, "Rahul is my college friend.", "Okay", False)
    core.interaction.set_quiet(True)
    window.ui_command("bye")
    assert core.learning.pending() and window.in_background
    window.bring_forward()
    window.new_conversation()
    assert window.session != session and core.interaction.quiet


def test_restart_queues_previous_desktop_transcript_without_displaying_it(core, app):
    old = core.new_session()
    core.store.exchange(old, "Rahul is my college friend.", "Okay", False)
    (core.settings.data_dir / "desktop-session.txt").write_text(old)
    window = NishaWindow(core, start_listener=False)
    assert core.learning.pending() and window.session != old
    assert not window.current_user and not window.current_reply
    window.close()


def test_combined_wake_command_and_followup_preserve_session(window):
    previous = window.session
    calls = []
    window.start_turn = lambda text, **kwargs: calls.append((window.session, text))
    window.hide_to_background()
    window.wake_received()
    window.wake_received()
    new = window.session
    window.heard_command("open YouTube")
    window.heard_command("what next?")
    assert new == previous
    assert calls == [(new, "open YouTube"), (new, "what next?")]
    window.wake_received()
    assert window.session == new


def test_muted_wake_does_not_show_window_or_reset_session(window):
    window.toggle_mute()
    assert window.muted and window.mute_action.isChecked()
    window.hide_to_background()
    previous = window.session
    window.wake_received()
    assert not window.isVisible() and window.session == previous


def test_quit_stops_listener_and_closes_resident(window):
    window.quit_application()
    assert window.closing and window.listener.engine.stopped.is_set()
    assert not window.isVisible() and not window.device_poll_timer.isActive()


def test_failed_listener_recovers_without_turning_manual_mute_off(window):
    calls = []
    window.spoken_wake_enabled = True
    window.listener.isRunning = lambda: False
    window.start_listening = lambda: calls.append(True)
    window.listener_error("Microphone disconnected")
    assert not window.muted
    window.recover_background()
    assert calls == [True]
    window.toggle_mute()
    window.recover_background()
    assert calls == [True] and window.muted


def test_completed_speech_restores_unmuted_listener(window, app, monkeypatch):
    from nisha.voice import WindowsSpeech

    monkeypatch.setattr(WindowsSpeech, "speak", lambda *_args, **_kwargs: None)
    window.voice_awake = True
    window.start_speech("Done.", "action")
    assert window.worker.wait(2000)
    app.processEvents()
    assert not window.muted
    assert not window.listener.engine.muted.is_set()
    assert not window.listener.engine.paused.is_set()
    assert not window.listener.engine.output_active.is_set()


def test_model_error_removes_unrelated_media_and_cancels_visual_tour(window):
    window.current_user = "Tell me about Saturn"
    window.result_turn = True
    window.visual_panel.assets = [MediaAsset("image", "unrelated robot", "bad.png")]
    previous = window.visual_generation
    window.show_error("Local service unavailable")
    assert not window.visual_panel.assets and window.turn_failed
    assert window.visual_generation != previous
    assert window.visual_panel.isVisible()
    assert "Local service unavailable" in window.visual_panel.response.toPlainText()


def test_background_work_completion_does_not_reopen_followup_gate(window):
    window.voice_turn = True
    window.listener.engine.gate.extend()
    window.hide_to_background()
    window.finish_turn()
    assert not window.listener.engine.gate.awake and not window.isVisible()


def test_new_wake_during_thinking_queues_command_in_current_session(window):
    interrupted = []
    window.worker = SimpleNamespace(
        isRunning=lambda: True, requestInterruption=lambda: interrupted.append(True)
    )
    old = window.session
    window.hide_to_background()
    window.wake_received()
    window.wake_received()
    assert interrupted and window.session == old
    window.heard_command("new question")
    assert window.pending_voice == (window.session, "new question", False)
    assert window.listener.engine.wake_only.is_set()
    calls = []
    window.worker = None
    window.start_turn = lambda text, **kwargs: calls.append((window.session, text))
    window.finish_turn()
    assert calls == [(window.session, "new question")]


def test_local_single_instance_channel_has_only_show_and_quit(app, tmp_path):
    owner = DesktopInstance(tmp_path, app)
    calls = []
    owner.window = SimpleNamespace(
        open_fresh=lambda: calls.append("show"), quit_application=lambda: calls.append("quit")
    )
    assert owner.acquire()
    second = DesktopInstance(tmp_path, app)
    assert not second.acquire()
    assert second.notify("show")
    loop = QEventLoop()
    QTimer.singleShot(100, loop.quit)
    loop.exec()
    assert calls == ["show"]
    assert second.notify("arbitrary")
    QTimer.singleShot(100, loop.quit)
    loop.exec()
    assert calls == ["show"]
    assert second.notify("quit")
    QTimer.singleShot(100, loop.quit)
    loop.exec()
    assert calls == ["show", "quit"]
    owner.close()


def test_startup_initialization_enables_wake_on_login_and_respects_saved_opt_out(tmp_path):
    startup = LoginStartup(tmp_path)
    calls = []
    startup.set_enabled = lambda enabled: calls.append(enabled)
    startup.initialize()
    assert calls == [True]
    startup.marker.write_text('{"initialized": true}')
    calls.clear()
    startup.initialize()
    assert not calls
    command = startup.command()
    assert "-WindowStyle Hidden" in command and "-Background" in command


def test_voice_close_clears_pending_work_hides_and_can_wake_again(window):
    interrupted = []
    old = window.session
    window.pending_voice = (old, "open something", False)
    window.wake_during_turn = True
    window.worker = SimpleNamespace(
        isRunning=lambda: True, requestInterruption=lambda: interrupted.append(True)
    )
    window.listener.engine.gate.extend()
    window.close_requested()
    assert interrupted and window.pending_voice is None and not window.wake_during_turn
    assert not window.isVisible() and not window.listener.engine.gate.awake
    assert not window.listener.engine.stopped.is_set() and not window.muted
    window.worker = None
    window.wake_received()
    assert window.isVisible() and window.session == old


def test_typed_close_alias_hides_without_model_turn(window):
    assert window.ui_command("Just be quite!")
    assert not window.isVisible() and not window.listener.engine.stopped.is_set()


def test_manual_open_keeps_context_but_waits_for_wake(window, core):
    old = window.session
    core.store.exchange(old, "Old question", "Old answer", cloud_allowed=False)
    window.current_user, window.current_reply = "Old question", "Old answer"
    window.render()
    window.hide_to_background()
    window.open_fresh()
    assert window.isVisible() and window.session == old
    assert window.current_reply == "Old answer"
    assert len(core.store.history(old)[1]) == 2
    assert not window.listener.engine.gate.awake
    assert not window.listener.engine.blocked()
    assert not window.listener.engine.wake_only.is_set()
    assert window.listener.engine.gate.accept("open YouTube") is None
    window.wake_received()
    assert window.listener.engine.gate.accept("open YouTube") == "open YouTube"


def test_unmuting_idle_window_still_requires_wake_then_restores_active_followups(window):
    window.toggle_mute()
    assert not window.listener.engine.gate.awake
    window.toggle_mute()
    assert not window.listener.engine.gate.awake
    window.wake_received()
    window.toggle_mute()
    window.toggle_mute()
    assert window.listener.engine.gate.awake
    window.hide_to_background()
    window.toggle_mute()
    window.toggle_mute()
    assert not window.listener.engine.gate.awake


def test_initial_window_does_not_restore_previous_display(core, app):
    old = core.new_session()
    core.store.exchange(old, "Yesterday", "Old text", cloud_allowed=False)
    (core.settings.data_dir / "desktop-session.txt").write_text(old)
    fresh = NishaWindow(core, start_listener=False)
    assert fresh.session != old and not fresh.current_reply
    assert not fresh.wall_widget.conversation_label.text()
    fresh.close()


@pytest.mark.parametrize(
    "action",
    ["close", "hide_to_background", "interrupt_reply", "quit_application", "quiet_requested"],
)
def test_ui_actions_cancel_active_playback_promptly(window, core, app, monkeypatch, action):
    from threading import Event
    from time import monotonic, sleep

    from nisha.voice import WindowsSpeech

    started, stopped = Event(), Event()

    def speaking(self, text, cancelled=None):
        started.set()
        deadline = monotonic() + 3
        while monotonic() < deadline and not cancelled():
            sleep(0.01)
        if cancelled():
            stopped.set()

    monkeypatch.setattr(WindowsSpeech, "speak", speaking)
    old_session = window.session
    window.start_turn("Explain photosynthesis in detail", voice=True)
    deadline = monotonic() + 3
    while not started.is_set() and monotonic() < deadline:
        app.processEvents()
        sleep(0.01)
    assert started.is_set() and window.listener.engine.output_active.is_set()
    assert not window.listener.engine.blocked()
    getattr(window, action)()
    assert window.worker.wait(1000), "Playback did not stop promptly."
    app.processEvents()
    assert stopped.is_set() and not window.listener.engine.output_active.is_set()
    if action == "interrupt_reply":
        assert window.isVisible() and window.session == old_session
        assert window.listener.engine.gate.awake
    elif action == "quiet_requested":
        assert window.isVisible() and not window.voice_awake and core.interaction.quiet
        assert not window.listener.engine.gate.awake
    elif action != "quit_application":
        assert not window.isVisible() and not window.listener.engine.blocked()
        assert not window.listener.engine.gate.awake


def test_information_uses_left_glass_without_moving_orb(window, app):
    original_orb = window.wall_widget.orb.pos()
    window.current_user = "Explain the schematic"
    window.current_reply = "A full answer. " * 100
    window.render()
    app.processEvents()
    panel = window.visual_panel
    assert panel.isVisible() and panel.response.toPlainText() == window.current_reply
    assert "You: Explain the schematic" in window.wall_widget.conversation_label.text()
    assert window.current_reply in window.wall_widget.conversation_label.text()
    assert "local" in window.wall_widget.models_label.text().casefold()
    assert window.wall_widget.orb.pos() == original_orb
    assert panel.x() == window.screen().availableGeometry().left() + 24
    orb = QRect(
        window.wall_widget.orb.mapToGlobal(QPoint(0, 0)),
        window.wall_widget.orb.size(),
    )
    assert not panel.geometry().intersects(orb)
    panel.dismiss()
    app.processEvents()
    assert window.wall_widget.orb.pos() == original_orb
    window.append_chunk(" More text from the old response.")
    assert not panel.isVisible()
    window.new_conversation()
    assert not panel.response.toPlainText() and not panel.assets


def test_normal_dialogue_stays_below_fixed_orb_and_memory_receipts_do_not_reopen_results(window):
    original_orb = window.wall_widget.orb.pos()
    window.current_user, window.current_reply = "How are you?", "I'm here, Boss."
    window.render()
    assert (
        window.wall_widget.conversation_label.text() == "You: How are you?\nNISHA: I'm here, Boss."
    )
    assert not window.visual_panel.isVisible()
    window.result_turn = True
    window.current_user, window.current_reply = "Explain robotics", "An information result."
    window.render()
    assert window.visual_panel.isVisible()
    window.input.setText("/remember favorite_color=green")
    window.submit()
    assert "Saved" in window.wall_widget.conversation_label.text()
    assert not window.visual_panel.isVisible()
    assert window.wall_widget.orb.pos() == original_orb


def test_unclear_information_request_uses_conversation_for_clarification(window, app):
    window.find_visuals = lambda text: None
    window.start_turn("Explain the image", uncertain=True)
    assert not window.visual_panel.isVisible()
    assert window.worker.wait(2000)
    app.processEvents()
    assert not window.visual_panel.isVisible()
    assert "You: Explain the image" in window.wall_widget.conversation_label.text()


@pytest.mark.parametrize(
    "status, color_state",
    [
        ("Waiting for NISHA", "idle"),
        ("Listening", "listening"),
        ("Thinking", "thinking"),
        ("Speaking", "speaking"),
    ],
)
def test_status_signals_change_orb_color_without_moving_it(window, status, color_state):
    original = window.wall_widget.orb.pos()
    window.set_state(status)
    assert window.wall_widget.orb.state == color_state
    assert window.wall_widget.orb.pos() == original


def test_idle_checkins_are_quiet_during_approval_and_after_optout(window, core, monkeypatch):
    time = [0]
    window.idle_checkins.clock = lambda: time[0]
    window.idle_checkins.activity()
    window.idle_enabled = True
    spoken = []
    window.start_speech = lambda text, mode: spoken.append((text, mode))
    time[0] = 300
    core.interaction.set_quiet(True)
    window.check_idle()
    assert not spoken
    core.interaction.set_quiet(False)
    monkeypatch.setattr(core.store, "pending_email", lambda session: {"token": "pending"})
    window.check_idle()
    assert not spoken
    monkeypatch.setattr(core.store, "pending_email", lambda session: None)
    window.check_idle()
    assert len(spoken) == 1
    assert spoken[0][0] in window.wall_widget.conversation_label.text()
    assert not window.visual_panel.isVisible()
    time[0] = 900
    window.check_idle()
    window.check_idle()
    assert len(spoken) == 2
    time[0] = 9999
    window.check_idle()
    assert len(spoken) == 2
    window.quiet_requested()
    assert core.interaction.quiet and not window.tour_enabled
    assert window.idle_checkins.count == 2


def test_image_results_describe_then_advance_automatically_without_fake_user_memory(
    window, core, app, monkeypatch
):
    import io

    from PIL import Image

    data = io.BytesIO()
    Image.new("RGB", (60, 40), "blue").save(data, format="PNG")
    window.media_service.image_bytes = lambda asset: data.getvalue()
    window.vision.describe = lambda payload: "A blue rectangle is visible."
    spoken = []
    monkeypatch.setattr(
        "nisha.voice.WindowsSpeech.speak", lambda self, text, cancelled=None: spoken.append(text)
    )
    assets = [
        MediaAsset("image", "First example", "example1.png"),
        MediaAsset("image", "Second example", "example2.png"),
    ]
    window.tour_enabled = True
    window.visual_panel.present(assets, window.load_visual_image)
    loop = QEventLoop()
    timer = QTimer()
    timer.setInterval(25)
    timer.timeout.connect(
        lambda: (
            loop.quit()
            if len(spoken) == 2 and not window.busy() and not window.background_jobs
            else None
        )
    )
    timer.start()
    QTimer.singleShot(5000, loop.quit)
    loop.exec()
    timer.stop()
    assert len(spoken) == 2
    assert "First example" in spoken[0] and "Second example" in spoken[1]
    assert window.visual_panel.index == 1
    assert "blue rectangle" in window.visual_panel.caption.text()
    assert not core.store.history(window.session)[1]
    assert not core.interaction.profile()


def test_interrupted_visual_tour_does_not_restart(window):
    interrupted = []
    window.worker = SimpleNamespace(
        mode="visual", isRunning=lambda: True, requestInterruption=lambda: interrupted.append(True)
    )
    window.tour_enabled = True
    window.interrupt_reply()
    assert interrupted and not window.tour_enabled
    window.next_tour_visual()
    assert not window.tour_enabled


def test_chat_icon_opens_right_glass_and_moves_only_orb_then_restores_it(window, app):
    class Screen:
        def availableGeometry(self):
            return QRect(0, 0, 1920, 1080)

    window.screen = lambda: Screen()
    window.resize(1824, 1026)
    app.processEvents()
    dashboard = window.wall_widget
    fixed = [
        dashboard.time_label,
        dashboard.date_label,
        dashboard.mic_label,
        dashboard.input_bar,
        dashboard.conversation_label,
        dashboard.devices_label,
        dashboard.models_label,
        dashboard.knowledge_label,
    ]
    original = [widget.geometry() for widget in fixed]
    orb, title = dashboard.orb.pos(), dashboard.title_label.pos()
    session = window.session
    window.listener.engine.resume(follow_up=True)
    dashboard.chat_button.click()
    app.processEvents()
    assert window.chat_panel.isVisible() and dashboard.chat_button.isChecked()
    assert not window.chat_panel.testAttribute(Qt.WA_TranslucentBackground)
    assert window.chat_panel.geometry().right() == 1920 - 25
    mic = dashboard.mic_label.mapToGlobal(dashboard.mic_label.rect().topLeft())
    assert window.chat_panel.geometry().bottom() < mic.y()
    orb_center = dashboard.orb.mapTo(dashboard, dashboard.orb.rect().center())
    assert orb_center.x() > dashboard.nav_bar.geometry().right()
    assert orb_center.x() < dashboard.activity_feed.geometry().left()
    assert dashboard.orb.y() == orb.y()
    assert [widget.geometry() for widget in fixed] == original
    assert window.session == session and window.listener.engine.gate.awake
    window.chat_panel.close()
    app.processEvents()
    assert not window.chat_panel.isVisible() and not dashboard.chat_button.isChecked()
    assert dashboard.orb.pos() == orb and dashboard.title_label.pos() == title
    assert window.session == session and window.listener.engine.gate.awake


def test_chat_keeps_turns_updates_stream_and_separates_artifacts(window, app):
    chat = window.chat_panel
    window.current_user, window.current_reply = "Hello", "Hi"
    window.render()
    window.append_chunk(", Boss.")
    assert chat.messages == [
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Hi, Boss."},
    ]
    window.current_user, window.current_reply = "How are you?", "Ready to help."
    window.render()
    assert len(chat.messages) == 4
    window.current_user = "Write an email to my supplier"
    window.current_reply = "A private email draft with many paragraphs."
    window.render()
    assert len(chat.messages) == 6
    assert chat.messages[-1]["content"] == window.current_reply
    assert window.visual_panel.response.toPlainText() == window.current_reply
    original_results = window.visual_panel.pos()
    window.toggle_conversation()
    app.processEvents()
    assert window.visual_panel.pos() == original_results and window.visual_panel.isVisible()
    user, assistant = chat.bubbles[0], chat.bubbles[1]
    assert (
        user.mapTo(chat.canvas, user.rect().topLeft()).x()
        > assistant.mapTo(chat.canvas, assistant.rect().topLeft()).x()
    )
    window.toggle_conversation()
    window.toggle_conversation()
    assert len(chat.messages) == 6
    window.new_conversation()
    app.processEvents()
    assert not chat.messages and not chat.bubbles and chat.empty.isVisible()


def test_front_page_navigation_is_visible_and_wired(window, app, monkeypatch):
    from PySide6.QtTest import QSignalSpy

    bar = window.wall_widget.nav_bar
    assert bar.isVisible()
    assert set(bar.buttons) == {
        "overview", "conversation", "tasks", "learning", "tools", "devices",
        "media", "voice", "email", "new", "mute", "settings"
    }
    # Observe the real button signal without opening the modal Connections dialog.
    bar.requested.disconnect()
    destinations = QSignalSpy(bar.requested)
    bar.buttons["devices"].click()
    assert destinations.count() == 1
    assert destinations.at(0)[0] == "devices"
    titles = {action.text() for action in bar.settings_menu.actions() if not action.isSeparator()}
    assert {"Preferences, memories & learning", "Keyboard shortcuts", "Gmail account setup"} <= titles
    opened = []
    monkeypatch.setattr(window, "setup_connections", lambda: opened.append("devices"))
    window.navigate_frontpage("devices")
    assert opened == ["devices"]


def test_center_monitor_selection_and_nisha_window_controls(window, app):
    from types import SimpleNamespace

    screens = [
        SimpleNamespace(geometry=lambda: QRect(0, 0, 1920, 1080)),
        SimpleNamespace(geometry=lambda: QRect(1920, 0, 1920, 1080)),
        SimpleNamespace(geometry=lambda: QRect(3840, -420, 1080, 1920)),
    ]
    assert center_monitor(screens) is screens[1]
    screen_geometry = window.screen().geometry()
    assert window.minimize_button.accessibleName() == "Minimize NISHA to compact orbit view"
    assert window.full_button.accessibleName() == "Toggle full-window mode"
    assert window.close_button.accessibleName() == "Close NISHA"
    dashboard = window.wall_widget
    dashboard.set_conversation("Question " * 20, "Answer " * 60)
    window.toggle_compact_mode()
    app.processEvents()
    assert window.compact_mode and dashboard.compact_mode
    assert window.width() <= 420 and window.height() <= 320
    assert dashboard.hero_card.isVisible() and dashboard.orbit_canvas.isVisible()
    assert dashboard.conversation_label.isVisible()
    assert not dashboard.nav_bar.isVisible() and not dashboard.activity_feed.isVisible()
    assert not dashboard.voice_dock.isVisible() and not window.full_button.isVisible()
    assert len(dashboard.conversation_label.text()) < len(dashboard.conversation_label.toolTip())
    window.toggle_compact_mode()
    app.processEvents()
    assert not window.compact_mode and dashboard.nav_bar.isVisible()
    window.toggle_full_window()
    app.processEvents()
    assert window.full_window and window.geometry() == screen_geometry
    window.toggle_full_window()
    app.processEvents()
    assert not window.full_window and window.geometry().center() == screen_geometry.center()


def test_panels_are_opaque_and_chat_always_scrolls_to_latest(window, app):
    assert not window.visual_panel.testAttribute(Qt.WA_TranslucentBackground)
    assert not window.chat_panel.testAttribute(Qt.WA_TranslucentBackground)
    chat = window.chat_panel
    chat.open()
    for i in range(30):
        chat.begin_turn()
        chat.record(f"Question {i}", (f"Answer {i}. " * 12))
    app.processEvents()
    bar = chat.scroll.verticalScrollBar()
    bar.setValue(0)
    chat.begin_turn()
    chat.record("Newest question", "Newest answer. " * 30)
    app.processEvents()
    assert bar.value() == bar.maximum()
    assert window.speak_responses is True


def test_main_window_has_full_opaque_hud_backdrop_and_responsive_footer(window, app):
    image = window.grab().toImage()
    corner = image.pixelColor(4, 4)
    assert not window.testAttribute(Qt.WA_TranslucentBackground)
    assert corner.alpha() == 255 and corner.red() < 32 and corner.blue() > corner.red()
    for width, height in ((1366, 768), (1920, 1080)):
        window.wall_widget.resize(width, height)
        app.processEvents()
        dashboard = window.wall_widget
        assert not dashboard.nav_bar.geometry().intersects(dashboard.voice_dock.geometry())
        assert not dashboard.activity_feed.geometry().intersects(dashboard.voice_dock.geometry())
        assert dashboard.header.geometry().right() < dashboard.width() - 120
        assert dashboard.hero_card.rect().contains(dashboard.orb.geometry())
        assert dashboard.core_card.isVisible() and dashboard.quick_card.isVisible()


def test_reference_style_dashboard_controls_have_real_targets(window, app):
    from PySide6.QtTest import QSignalSpy

    dashboard = window.wall_widget
    assert dashboard.search_input.accessibleName() == "Search recent NISHA activity"
    assert dashboard.send_button.accessibleName() == "Send message to NISHA"
    assert dashboard.header_status.text().startswith("●")
    assert set(dashboard.quick_buttons) == {
        "/new", "show open windows", "list installed apps",
        "what's the status of the devices?"
    }
    commands = QSignalSpy(dashboard.command_requested)
    dashboard.quick_buttons["list installed apps"].click()
    assert commands.count() == 1
    assert commands.at(0)[0] == "list installed apps"
    feed = dashboard.activity_feed
    feed.add_event("Local search target", "A real recent activity entry.")
    app.processEvents()
    dashboard.search_input.setText("local search target")
    app.processEvents()
    feed._refresh()
    assert "Local search target" in feed.output.toPlainText()
    dashboard.search_input.setText("not present")
    feed._refresh()
    assert feed.output.toPlainText() == ""


def test_orbit_animation_tracks_nisha_state_and_nodes_navigate(window, app):
    from PySide6.QtTest import QSignalSpy, QTest

    dashboard = window.wall_widget
    orbit = dashboard.orbit_canvas
    assert orbit.timer.isActive()
    first_phase = orbit.phase
    QTest.qWait(120)
    assert orbit.phase != first_phase
    dashboard.set_runtime_state("Thinking")
    assert orbit.state == "Thinking"
    assert len(dashboard.orbit_buttons) == 3
    dashboard.nav_bar.requested.disconnect()
    actions = QSignalSpy(dashboard.nav_bar.requested)
    dashboard.orbit_buttons[0].click()
    assert actions.count() == 1 and actions.at(0)[0] == "tasks"


def test_orbit_overlay_has_no_ring_pixels(window, app):
    from PySide6.QtGui import QImage

    orbit = window.wall_widget.orbit_canvas
    app.processEvents()
    image = orbit.grab().toImage().convertToFormat(QImage.Format_ARGB32)
    assert image.width() > 0 and image.height() > 0
    assert image.pixelColor(image.width() // 2, image.height() // 2).alpha() == 0


def test_repeated_identical_questions_get_separate_chat_bubbles(window, app):
    window.find_visuals = lambda text: None
    for _ in range(2):
        window.start_turn("Hello")
        assert window.worker.wait(2000)
        app.processEvents()
    assert [message["role"] for message in window.chat_panel.messages] == [
        "user",
        "assistant",
        "user",
        "assistant",
    ]


def test_chat_hide_restores_orb_and_user_text_is_not_interpreted_as_markup(window, app):
    original = window.wall_widget.orb.pos()
    window.current_user, window.current_reply = (
        "<img src='https://example.invalid/private'>",
        "<b>literal text</b>",
    )
    window.render()
    window.toggle_conversation()
    app.processEvents()
    assert all(bubble.body.textFormat() == Qt.PlainText for bubble in window.chat_panel.bubbles)
    window.hide_to_background()
    app.processEvents()
    assert not window.chat_panel.isVisible()
    assert window.wall_widget.orb.pos() == original
    assert not window.wall_widget.chat_button.isChecked()
    assert not window.listener.engine.gate.awake


def test_chat_keyboard_shortcut_closes_panel_without_resetting_session(window, app):
    from PySide6.QtTest import QTest

    session = window.session
    window.toggle_conversation()
    window.chat_panel.activateWindow()
    app.processEvents()
    QTest.keyClick(window.chat_panel, Qt.Key_J, Qt.ControlModifier)
    app.processEvents()
    assert not window.chat_panel.isVisible()
    assert window.session == session and not window.wall_widget.chat_open


def test_visible_wake_acknowledges_without_resetting_history_or_pausing_mic(window, core):
    session = window.session
    core.store.exchange(session, "My project is NISHA", "I remember", cloud_allowed=False)
    calls = []
    window.spoken_wake_enabled = True
    window.start_turn = lambda text, **kwargs: calls.append((text, kwargs))
    window.wake_received()
    window.acknowledge_wake()
    assert calls == [("Hey", {"voice": True})] and window.session == session
    assert len(core.store.history(session)[1]) == 2
    assert window.listener.engine.gate.awake and not window.listener.engine.blocked()
    assert not window.listener.engine.wake_only.is_set()
    assert not window.conversation_engaged


def test_combined_command_cancels_delayed_wake_acknowledgment(window):
    cues, calls = [], []
    window.spoken_wake_enabled = True
    window.start_speech = lambda *args: cues.append(args)
    window.start_turn = lambda text, **kwargs: calls.append(text)
    window.wake_received()
    window.heard_command("open YouTube")
    window.acknowledge_wake()
    assert calls == ["open YouTube"] and not cues
    assert not window.pending_wake_ack


def test_personal_wake_waits_for_combined_audio_before_speaking(window):
    spoken, calls = [], []
    window.spoken_wake_enabled = True
    window.start_speech = lambda *args: spoken.append(args)
    window.start_turn = lambda text, **kwargs: calls.append(text)
    window.listener.engine.decoding.set()
    window.wake_received()
    window.acknowledge_wake()
    assert window.pending_wake_ack and not spoken
    assert not window.listener.engine.blocked()
    window.listener.engine.decoding.clear()
    window.heard_command("open YouTube")
    window.acknowledge_wake()
    assert calls == ["open YouTube"] and not spoken


def test_initial_manual_visibility_does_not_activate_voice(window):
    window.bring_forward()
    assert window.isVisible() and not window.voice_awake
    assert not window.listener.engine.gate.awake and not window.listener.engine.blocked()
    assert "Waiting for NISHA" in window.table_status.text()
    assert window.listener.engine.gate.accept("open YouTube") is None


def test_five_minute_idle_checkin_does_not_require_previous_conversation(window, core):
    time = [0]
    window.idle_checkins.clock = lambda: time[0]
    window.idle_checkins.activity()
    window.idle_enabled = True
    spoken = []
    window.start_speech = lambda text, mode: spoken.append(text)
    window.open_fresh()
    time[0] = 299
    window.check_idle()
    assert not spoken
    time[0] = 300
    window.check_idle()
    assert len(spoken) == 1
    assert not window.voice_awake and not core.store.history(window.session)[1]


def test_wake_during_thinking_keeps_context_and_ignores_late_old_reply(window, core, app):
    from threading import Event
    from time import monotonic, sleep

    ready, release = Event(), Event()
    greetings = []

    def stream(*_):
        yield "An older response."
        ready.set()
        release.wait(3)
        yield " Older tail."

    core.gateway.stream = stream
    window.find_visuals = lambda _: None
    session = window.session
    core.store.exchange(session, "We are building NISHA", "Understood", cloud_allowed=False)
    window.start_turn("Explain context")
    previous = window.worker
    window.start_turn = lambda text, **kwargs: greetings.append((text, kwargs))
    try:
        deadline = monotonic() + 2
        while not ready.is_set() and monotonic() < deadline:
            app.processEvents()
            sleep(0.01)
        assert ready.is_set()
        window.wake_received()
        window.acknowledge_wake()
        previous.chunk.emit("Unwanted queued tail.")
        app.processEvents()
        assert "Unwanted queued tail" not in window.current_reply
        assert window.pending_wake_ack
        assert window.session == session
        assert window.listener.engine.gate.awake and not window.listener.engine.wake_only.is_set()
        assert len(core.store.history(session)[1]) == 2
    finally:
        release.set()
        assert previous.wait(2000)
        app.processEvents()
    assert greetings == [("Hey", {"voice": False})]


def test_name_call_uses_local_model_then_keeps_followups(
    window, core, app, monkeypatch
):
    from nisha.voice import WindowsSpeech

    session = window.session
    core.store.exchange(session, "My project is NISHA", "Understood", cloud_allowed=False)
    spoken = []

    def speak(self, text, cancelled=None):
        spoken.append(text)
        assert window.listener.engine.output_active.is_set()
        assert not window.listener.engine.blocked()

    monkeypatch.setattr(WindowsSpeech, "speak", speak)
    window.spoken_wake_enabled = True
    window.wake_received()
    window.acknowledge_wake()
    assert window.worker.wait(2000)
    app.processEvents()
    assert spoken == ["Hello Nishchal."]
    assert window.session == session and len(core.store.history(session)[1]) == 4
    assert window.listener.engine.gate.awake and not window.listener.engine.wake_only.is_set()
    assert window.conversation_engaged
    calls = []
    window.start_turn = lambda text, **kwargs: calls.append((window.session, text))
    window.heard_command("How are you?")
    assert calls == [(session, "How are you?")]


def test_manual_open_while_cancelling_reply_remains_idle_after_worker_finishes(window):
    cancelled = []
    window.voice_awake = True
    window.listener.engine.gate.extend()
    window.worker = SimpleNamespace(
        isRunning=lambda: True,
        requestInterruption=lambda: cancelled.append(True),
        isInterruptionRequested=lambda: bool(cancelled),
    )
    window.open_fresh()
    window.worker.isRunning = lambda: False
    window.finish_turn()
    assert cancelled and window.isVisible() and not window.voice_awake
    assert not window.listener.engine.gate.awake and not window.listener.engine.blocked()
    assert window.listener.engine.gate.accept("open YouTube") is None


@pytest.mark.parametrize(
    "phrase",
    [
        "start fresh",
        "start new conversation",
        "lets talk new",
        "lets talk different topic",
        "have some other conversation then this",
    ],
)
def test_fresh_intent_starts_empty_context_and_keeps_followups_awake(window, core, phrase):
    old = window.session
    core.store.exchange(old, "Old subject", "Old reply", cloud_allowed=False)
    window.current_user, window.current_reply = "Old subject", "Old reply"
    window.render()
    assert window.ui_command(phrase)
    new = window.session
    window.acknowledge_wake()
    assert new != old and not core.store.history(new)[1]
    assert len(core.store.history(old)[1]) == 2
    assert window.current_user == phrase and "What's on your mind?" in window.current_reply
    assert window.listener.engine.gate.awake and not window.listener.engine.blocked()
    assert len(window.chat_panel.bubbles) == 2
    calls = []
    window.start_turn = lambda text, **kwargs: calls.append((window.session, text))
    window.heard_command("How are you?")
    assert calls == [(new, "How are you?")]
    window.wake_received()
    assert window.session == new


def test_fresh_request_cancels_busy_reply_and_discards_queued_old_command(window, core):
    interrupted, spoken = [], []
    old = window.session
    core.store.exchange(old, "Old subject", "Old reply", cloud_allowed=False)
    window.worker = SimpleNamespace(
        isRunning=lambda: True,
        requestInterruption=lambda: interrupted.append(True),
        isInterruptionRequested=lambda: bool(interrupted),
    )
    window.pending_voice = (old, "old queued command", False)
    window.spoken_wake_enabled = True
    window.start_speech = lambda text, mode: spoken.append(text)
    window.start_fresh_requested("start fresh")
    assert interrupted and window.session != old and window.pending_voice is None
    window.acknowledge_wake()
    assert not spoken and window.pending_wake_ack
    window.worker.isRunning = lambda: False
    window.finish_turn()
    assert spoken == ["Sure, Boss. What's on your mind?"]
    assert not core.store.history(window.session)[1] and len(core.store.history(old)[1]) == 2
    assert window.listener.engine.gate.awake


def test_typed_fresh_request_while_muted_preserves_mute(window):
    window.toggle_mute()
    old = window.session
    window.input.setText("start fresh")
    window.submit()
    assert window.session != old and window.muted and window.listener.engine.muted.is_set()
    assert "What's on your mind?" in window.current_reply and not window.pending_wake_ack


def test_background_first_wake_opens_quietly_second_gets_attention(window, core):
    old = window.session
    core.store.exchange(old, "Our topic", "Our answer", cloud_allowed=False)
    spoken, commands = [], []
    window.spoken_wake_enabled = True
    window.start_speech = lambda *args: spoken.append(args)
    window.start_turn = lambda *args, **kwargs: commands.append(args)
    window.hide_to_background()
    window.wake_received()
    window.acknowledge_wake()
    window.heard_command("open YouTube")
    assert window.isVisible() and not window.voice_awake and not spoken and not commands
    assert not window.listener.engine.gate.awake and not window.listener.engine.blocked()
    window.listener_state("Transcribing")
    assert window.wall_widget.orb.state == "idle"
    assert "Waiting for NISHA" in window.table_status.text()
    window.wake_received()
    window.acknowledge_wake()
    assert window.voice_awake and window.listener.engine.gate.awake
    assert not spoken and commands == [("Hey",)]
    assert window.session == old and len(core.store.history(old)[1]) == 2


def test_two_minutes_silence_returns_idle_without_hiding_or_losing_context(window, core):
    time = [1000.0]
    window.conversation_clock = lambda: time[0]
    window.listener.engine.gate.clock = lambda: time[0]
    window.start_turn = lambda *_args, **_kwargs: None
    old = window.session
    core.store.exchange(old, "Our topic", "Our answer", cloud_allowed=False)
    window.wake_received()
    window.acknowledge_wake()
    time[0] += 119.9
    window.check_idle()
    assert window.voice_awake
    time[0] += 0.1
    window.check_idle()
    assert window.isVisible() and not window.voice_awake and not window.in_background
    assert not window.listener.engine.gate.awake and not window.listener.engine.blocked()
    assert window.listener.engine.gate.accept("continue") is None
    assert window.session == old and len(core.store.history(old)[1]) == 2
    assert "Waiting for NISHA" in window.table_status.text()
    window.wake_received()
    assert window.voice_awake and window.session == old


def test_long_reply_finishes_before_inactivity_countdown_begins(window):
    time = [1000.0]
    window.conversation_clock = lambda: time[0]
    window.listener.engine.gate.clock = lambda: time[0]

    def begin_wake_reply(*_args, **_kwargs):
        window.pending_wake_ack = False
        window.last_conversation_activity = time[0]

    window.start_turn = begin_wake_reply
    window.wake_received()
    window.worker = SimpleNamespace(isRunning=lambda: True, isInterruptionRequested=lambda: False)
    time[0] += 300
    window.check_idle()
    assert window.voice_awake
    window.worker.isRunning = lambda: False
    window.finish_turn()
    time[0] += 119
    window.check_idle()
    assert window.voice_awake
    time[0] += 1
    window.check_idle()
    assert not window.voice_awake


def test_unsolicited_checkin_cannot_extend_two_minute_conversation_timer(window):
    time, cancelled = [1000.0], []
    window.conversation_clock = lambda: time[0]
    window.wake_received()
    window.pending_wake_ack = False
    window.worker = SimpleNamespace(
        mode="idle",
        isRunning=lambda: True,
        requestInterruption=lambda: cancelled.append(True),
        isInterruptionRequested=lambda: bool(cancelled),
    )
    window.listener.engine.begin_output("Can I help you?")
    time[0] += 120
    window.check_idle()
    assert cancelled and not window.voice_awake and window.isVisible()
    assert not window.listener.engine.output_active.is_set()
    window.worker.isRunning = lambda: False
    window.finish_turn()
    assert not window.listener.engine.gate.awake


def test_checkin_reply_window_accepts_unprefixed_answer_and_supplies_local_context(
    window, core, app, monkeypatch
):
    time = [1000.0]
    window.conversation_clock = lambda: time[0]
    window.listener.engine.gate.clock = lambda: time[0]
    window.idle_checkins.clock = lambda: time[0]
    window.idle_checkins.activity()
    window.idle_enabled = True
    monkeypatch.setattr("nisha.voice.WindowsSpeech.speak", lambda *args, **kwargs: None)
    session = window.session
    time[0] += 300
    window.check_idle()
    assert window.worker.wait(2000)
    app.processEvents()
    greeting = window.idle_prompt
    assert greeting and window.idle_reply_until == time[0] + 30
    assert not window.voice_awake and window.listener.engine.gate.awake
    assert not core.store.history(session)[1]
    window.find_visuals = lambda _: None
    window.heard_command("Yes, let's talk about my day")
    assert window.worker.wait(2000)
    app.processEvents()
    messages = core.gateway.calls[-1][1]
    assert messages[-2] == {"role": "assistant", "content": greeting}
    assert messages[-1]["content"] == "Yes, let's talk about my day"
    assert window.voice_awake and not window.idle_reply_until
    assert len(core.store.history(session)[1]) == 2
    assert all(turn["content"] != greeting for turn in core.store.history(session)[1])


def test_unanswered_checkin_reply_window_expires_without_resetting_schedule(window, core):
    time = [1000.0]
    window.conversation_clock = lambda: time[0]
    window.listener.engine.gate.clock = lambda: time[0]
    window.idle_checkins.clock = lambda: time[0]
    window.idle_checkins.activity()
    window.idle_checkins.count = 1
    window.idle_prompt = "Hey Boss, what's up?"
    window.worker = SimpleNamespace(
        mode="idle", isRunning=lambda: False, isInterruptionRequested=lambda: False
    )
    window.finish_turn()
    time[0] += 30
    window.check_idle()
    assert not window.idle_reply_until and not window.voice_awake
    assert not window.listener.engine.gate.awake and window.idle_checkins.count == 1
    assert not core.store.history(window.session)[1]


@pytest.mark.parametrize("phrase", ["Don't disturb", "Dont disturb", "Don’t disturb me"])
def test_quiet_request_acknowledges_then_stays_idle_and_suppresses_checkins(window, core, phrase):
    spoken = []
    window.spoken_wake_enabled = True
    window.start_speech = lambda text, mode: spoken.append((text, mode))
    window.voice_awake = True
    window.listener.engine.gate.extend()
    assert window.ui_command(phrase)
    window.acknowledge_quiet()
    assert spoken == [("I'll be here. Talk to me when you're free.", "quiet")]
    assert core.interaction.quiet and not window.voice_awake and window.isVisible()
    assert not window.listener.engine.gate.awake and not window.idle_reply_until
    assert window.idle_checkins.due(True, core.interaction.quiet) is None


def test_silent_request_stops_speech_without_acknowledgement(window, core):
    spoken = []
    window.spoken_wake_enabled = True
    window.start_speech = lambda text, mode: spoken.append((text, mode))
    window.voice_awake = True
    window.listener.engine.gate.extend()
    assert window.ui_command("Don't say any word")
    window.acknowledge_quiet()
    assert not spoken and core.interaction.quiet and not window.voice_awake


def test_checkins_wait_five_minutes_after_two_minute_idle_transition(window):
    time, spoken = [1000.0], []
    window.conversation_clock = lambda: time[0]
    window.idle_checkins.clock = lambda: time[0]
    window.idle_checkins.activity()
    window.idle_enabled = True
    window.start_speech = lambda text, mode: spoken.append(text)
    window.wake_received()
    time[0] += 120
    window.check_idle()
    assert not window.voice_awake and not spoken
    time[0] += 299
    window.check_idle()
    assert not spoken
    time[0] += 1
    window.check_idle()
    assert len(spoken) == 1

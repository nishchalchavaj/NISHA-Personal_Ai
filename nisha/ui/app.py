import logging
import re
import sys
from pathlib import Path
from time import monotonic

from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMenu,
    QPushButton,
    QSystemTrayIcon,
    QVBoxLayout,
)

from nisha.errors import NishaError, OperationCancelled
from nisha.ui.text_security import PlainTextEdit, plain_warning
from nisha.ui.window import DashboardWindow

ASSETS = Path(__file__).parent / "assets"


class TurnWorker(QThread):
    chunk = Signal(str)
    state = Signal(str)
    error = Signal(str)

    def __init__(
        self,
        core,
        session,
        alias,
        text,
        speak=False,
        audio_idle=None,
        uncertain=False,
        before_speak=None,
        after_speak=None,
        assistant_prompt=None,
    ):
        super().__init__()
        self.core, self.session, self.alias = core, session, alias
        self.text = text
        self.speak = speak
        self.audio_idle = audio_idle
        self.uncertain = uncertain
        self.before_speak = before_speak
        self.after_speak = after_speak
        self.assistant_prompt = assistant_prompt

    def run(self):
        try:
            text = self.text
            if self.isInterruptionRequested():
                return
            if self.audio_idle is not None and not self.audio_idle.wait(3):
                raise NishaError("Microphone is still closing. Try the question again.")
            if self.isInterruptionRequested():
                return
            self.state.emit("Thinking")
            reply = []
            hints = {"assistant_prompt": self.assistant_prompt} if self.assistant_prompt else {}
            if hasattr(self.core, "check_cancelled"):
                hints["cancelled"] = self.isInterruptionRequested
            for chunk in self.core.stream(
                text, self.session, self.alias, uncertain=self.uncertain, **hints
            ):
                if self.isInterruptionRequested():
                    return
                reply.append(chunk)
                self.chunk.emit(chunk)
            if self.speak and not self.isInterruptionRequested():
                from nisha.voice import WindowsSpeech

                spoken = "".join(reply)
                if spoken.startswith(("Saved ", "Email draft ")):
                    spoken = spoken.split("\n", 1)[0] + ". The content is on screen for review."
                try:
                    if self.before_speak:
                        self.before_speak(spoken)
                    if not self.isInterruptionRequested():
                        self.state.emit("Speaking")
                        WindowsSpeech(self.core.settings.voice.rate, self.core.settings.voice.voice_locale).speak(
                            spoken, cancelled=self.isInterruptionRequested
                        )
                finally:
                    if self.after_speak:
                        self.after_speak()
        except OperationCancelled:
            return
        except (NishaError, ValueError) as exc:
            self.error.emit(str(exc))
        except Exception:
            logging.getLogger("nisha").exception("Desktop component failed")
            self.error.emit("This component failed. Check its configuration and try again.")


class SpeechWorker(TurnWorker):
    """Narration/check-ins never become synthetic user requests or learned facts."""

    def __init__(self, core, text, mode, before_speak=None, after_speak=None, audio_idle=None):
        super().__init__(
            core,
            "",
            "",
            text,
            before_speak=before_speak,
            after_speak=after_speak,
            audio_idle=audio_idle,
        )
        self.mode = mode

    def run(self):
        from nisha.voice import WindowsSpeech

        try:
            if self.audio_idle and not self.audio_idle.wait(3):
                return
            if self.isInterruptionRequested():
                return
            if self.before_speak:
                self.before_speak(self.text)
            self.state.emit("Speaking")
            WindowsSpeech(self.core.settings.voice.rate, self.core.settings.voice.voice_locale).speak(
                self.text, cancelled=self.isInterruptionRequested
            )
        except Exception:
            logging.getLogger("nisha").exception("Local narration unavailable")
        finally:
            if self.after_speak:
                self.after_speak()


class NishaWindow(DashboardWindow):
    def __init__(self, core, start_listener=True, background_enabled=None, on_demand=False):
        super().__init__()
        self.core = core
        self.session_file = core.settings.data_dir / "desktop-session.txt"
        if self.session_file.exists():
            try:
                previous = self.session_file.read_text(encoding="utf-8").strip()
                core.store.history(previous)
                core.end_conversation(previous)
            except (OSError, ValueError):
                logging.getLogger("nisha").info(
                    "Previous desktop session is unavailable for review."
                )
        self.session = core.new_session()
        self.save_session(self.session)
        self.alias = "local_fast"
        self.worker = None
        self.listener = None
        self.muted = not core.settings.voice.continuous_listening
        self.closing = False
        self.background_enabled = (
            start_listener if background_enabled is None else background_enabled
        )
        self.on_demand = on_demand
        self.in_background = False
        self.quit_requested = False
        self.exit_on_close = False
        self.tray = None
        self.voice_turn = False
        self.speak_responses = False
        self.current_user = ""
        self.current_reply = ""
        self.result_turn = None
        self.pending_voice = None
        self.pending_typed = []
        self.wake_during_turn = False
        self.pending_wake_ack = False
        self.pending_quiet_ack = False
        self.idle_reply_until = 0
        self.idle_prompt = None
        self.acknowledgment_user = "Hey NISHA"
        self.acknowledgment_reply = "Yes, Boss?"
        self.turn_generation = 0
        self.conversation_engaged = False
        self.voice_awake = False
        self.conversation_clock = monotonic
        self.last_conversation_activity = self.conversation_clock()
        self.spoken_wake_enabled = start_listener
        self.listener_failed = False
        from nisha.media import MediaService
        from nisha.ui.conversation_panel import ConversationPanel
        from nisha.ui.visual_panel import VisualPanel

        self.media_service = MediaService(core.settings.data_dir)
        self.visual_panel = VisualPanel(self)
        self.chat_panel = ConversationPanel(self)
        self.chat_panel.closed.connect(self.conversation_closed)
        self.visual_generation = 0
        self.visual_panel.closed.connect(self.invalidate_visuals)
        self.visual_panel.closed.connect(self.results_closed)
        self.visual_panel.image_displayed.connect(self.describe_visual)
        self.visual_panel.asset_changed.connect(self.visual_changed)
        self.visual_panel.review_requested.connect(self.review_youtube)
        from nisha.interaction import IdleCheckIns
        from nisha.vision import LocalVision

        self.vision = LocalVision(core.settings.ollama_url, core.settings.vision_model)
        self.idle_checkins = IdleCheckIns(
            first=core.settings.idle_checkin_seconds, second=core.settings.idle_checkin_seconds * 2
        )
        self.idle_enabled = start_listener and core.settings.idle_checkins
        self.tour_enabled = False
        self.tour_done = set()
        self.visual_descriptions = {}
        self.visual_reviewing = set()
        self.results_dismissed = False
        self.idle_timer = QTimer(self)
        self.idle_timer.setInterval(1000)
        self.idle_timer.timeout.connect(self.check_idle)
        self.idle_timer.start()
        self.background_jobs = []
        self.action_job = None
        self.action_queue = []
        self.action_results = []
        self.recovery_timer = QTimer(self)
        self.recovery_timer.setInterval(10000)
        self.recovery_timer.timeout.connect(self.recover_background)
        self.recovery_timer.start()
        QTimer.singleShot(100, self.recover_background)
        self.learning_timer = QTimer(self)
        self.learning_timer.setInterval(30000)
        self.learning_timer.timeout.connect(self.review_closed_conversations)
        self.learning_timer.start()
        self.last_visual_topic = ""
        self.setWindowIcon(QIcon(str(ASSETS / "nisha.ico")))
        self.input = self.wall_widget.input_bar
        self.input.returnPressed.connect(self.submit)
        self.input.textEdited.connect(lambda _: self.idle_checkins.activity())
        self.wall_widget.mic_label.clicked.connect(self.toggle_mute)
        self.wall_widget.chat_button.clicked.connect(self.toggle_conversation)
        self.bind_shortcut("Ctrl+J", self.toggle_conversation)
        self.bind_shortcut("Ctrl+Space", self.toggle_mute)
        self.bind_shortcut("Ctrl+N", self.new_conversation)
        self.bind_shortcut("Ctrl+Shift+S", self.toggle_speech)
        self.bind_shortcut("Ctrl+G", self.setup_gmail)
        self.bind_shortcut("Ctrl+E", self.review_email)
        self.bind_shortcut("Ctrl+L", self.learning_dialog)
        self.bind_shortcut("Ctrl+K", self.setup_worker)
        self.bind_shortcut("Ctrl+T", self.external_task_dialog)
        self.bind_shortcut("Ctrl+I", self.choose_media)
        self.bind_shortcut("Ctrl+Shift+G", self.open_gesture_studio)
        self.bind_shortcut("Ctrl+D", self.setup_connections)
        self.bind_shortcut("Ctrl+H", self.hide_to_background)
        self.bind_shortcut("Ctrl+Q", self.quit_application)
        self.bind_shortcut("Ctrl+R", self.voice_samples)
        if self.background_enabled:
            self.setup_tray()
        self.device_poll_timer = QTimer(self)
        self.device_poll_timer.setInterval(30000)
        self.device_poll_timer.timeout.connect(self.poll_devices)
        self.device_poll_timer.start()
        self.wall_widget.devices_label.setToolTip(
            "Ctrl+D · configure devices, projects and saved routines"
        )
        QTimer.singleShot(2000, self.poll_devices)
        self.wall_widget.email_button.clicked.connect(self.review_email)
        self.input.setToolTip("Enter to send · /remember KEY=TEXT · /use local_smart · /new")
        _, history = core.store.history(self.session)
        if history:
            self.current_user, self.current_reply = history[-2]["content"], history[-1]["content"]
            self.render()
        self.wall_widget.mic_label.set_muted(self.muted)
        if start_listener and not self.muted:
            self.start_listening()

    def restore_session(self):
        try:
            session = self.session_file.read_text(encoding="utf-8").strip()
            self.core.store.history(session)
            return session
        except (OSError, ValueError):
            session = self.core.new_session()
            self.save_session(session)
            return session

    def save_session(self, session):
        temporary = self.session_file.with_suffix(".tmp")
        temporary.write_text(session, encoding="utf-8")
        temporary.replace(self.session_file)

    def start_listening(self):
        if self.closing:
            return
        from nisha.ui.listener import ContinuousListener

        if self.listener and not self.listener.isRunning():
            self.listener.engine.speech.model = None
            self.listener.setParent(None)
            self.listener.deleteLater()

        self.listener = ContinuousListener(self.core.settings.voice, self.core.settings.data_dir)
        self.listener.setParent(self)
        self.listener.command.connect(self.heard_command)
        self.listener.state.connect(self.listener_state)
        self.listener.wake.connect(self.wake_received)
        self.listener.error.connect(self.listener_error)
        self.listener.uncertain.connect(self.heard_uncertain)
        self.listener.dismissed.connect(self.close_requested)
        self.listener.interrupted.connect(self.interrupt_reply)
        self.listener.quiet_requested.connect(self.quiet_requested)
        self.listener.silent_requested.connect(self.silent_requested)
        self.listener.fresh_requested.connect(self.start_fresh_requested)
        self.listener.opened.connect(self.open_from_wake)
        if self.in_background:
            self.listener.engine.background.set()
        else:
            self.listener.engine.resume(follow_up=self.voice_awake)
        if self.busy():
            self.listener.engine.pause()
        self.listener.start()

    def toggle_mute(self):
        if self.closing:
            return
        self.muted = not self.muted
        self.wall_widget.mic_label.set_muted(self.muted)
        if self.tray:
            self.mute_action.setChecked(self.muted)
            self.tray.setToolTip(
                "NISHA · " + ("microphone muted" if self.muted else "listening for your wake word")
            )
        if self.listener:
            self.listener.engine.set_muted(self.muted)
            if not self.muted and not self.busy():
                self.listener.engine.resume(follow_up=self.voice_awake and not self.in_background)
        if not self.muted and (self.listener is None or not self.listener.isRunning()):
            self.start_listening()
        if not self.busy():
            self.set_state(
                "Muted"
                if self.muted
                else "Listening"
                if self.voice_awake and not self.in_background
                else "Waiting for NISHA"
            )

    def listener_state(self, state):
        if not self.busy() and not self.muted and not self.closing:
            if (
                state in {"Listening", "Transcribing"}
                and not self.voice_awake
                and self.idle_reply_until <= self.conversation_clock()
            ):
                state = "Waiting for NISHA"
            self.set_state(state)

    def wake_received(self):
        if not self.muted and not self.closing:
            self.pending_quiet_ack = False
            self.idle_reply_until = 0
            self.idle_prompt = None
            if self.in_background or not self.isVisible():
                self.open_from_wake()
                return
            running = self.busy()
            if running:
                self.worker.requestInterruption()
                self.turn_generation += 1
            self.stop_visual_tour()
            self.pending_voice = None
            self.wake_during_turn = running
            self.conversation_engaged = False
            self.voice_awake = True
            self.last_conversation_activity = self.conversation_clock()
            self.bring_forward()
            if self.listener:
                self.listener.engine.resume(follow_up=True)
            self.set_state("Listening")
            self.wall_widget.mic_label.setToolTip(
                "I'm listening. Ask your question · click to mute"
            )
            self.pending_wake_ack = True
            self.acknowledgment_user = "Hey NISHA"
            self.acknowledgment_reply = "Yes, Boss?"
            QTimer.singleShot(100, self.acknowledge_wake)

    def open_from_wake(self):
        if self.muted or self.closing:
            return
        if self.busy():
            self.worker.requestInterruption()
        self.pending_voice = None
        self.pending_wake_ack = False
        self.wake_during_turn = False
        self.conversation_engaged = False
        self.voice_awake = False
        self.stop_visual_tour()
        if self.listener:
            if self.listener.engine.background.is_set():
                self.listener.engine.wait_for_wake()
            self.listener.engine.background.clear()
        self.bring_forward()
        self.set_state("Waiting for NISHA")
        logging.getLogger("nisha").info("Background wake opened the window; waiting for attention.")

    def start_fresh_requested(self, text="Start fresh"):
        if self.closing:
            return
        running = self.busy()
        if running:
            self.worker.requestInterruption()
        self.new_conversation(force=True)
        if self.listener:
            self.listener.engine.end_output()
        self.voice_awake = True
        self.last_conversation_activity = self.conversation_clock()
        self.wake_during_turn = running
        self.bring_forward()
        if self.listener and not self.muted:
            self.listener.engine.resume(follow_up=True)
        self.acknowledgment_user = text
        self.acknowledgment_reply = "Sure, Boss. What's on your mind?"
        if self.muted:
            self.current_user, self.current_reply = text, self.acknowledgment_reply
            self.result_turn = False
            self.render()
            return
        self.pending_wake_ack = True
        QTimer.singleShot(100, self.acknowledge_wake)

    def acknowledge_wake(self):
        if not self.pending_wake_ack or self.muted or self.closing or self.in_background:
            return
        if self.busy():
            return  # A cancelled reply must finish before the short spoken acknowledgment.
        engine = self.listener.engine if self.listener else None
        if engine and (
            engine.decoding.is_set()
            or engine.dispatching.is_set()
            or (hasattr(engine, "audio_queue") and not engine.audio_queue.empty())
        ):
            # An early personal wake may still be transcribing a combined command.
            # Speaking now would invalidate that audio and swallow the command.
            QTimer.singleShot(100, self.acknowledge_wake)
            return
        self.pending_wake_ack = False
        self.chat_panel.begin_turn()
        self.result_turn = False
        self.current_user, self.current_reply = self.acknowledgment_user, self.acknowledgment_reply
        self.render()
        if self.spoken_wake_enabled:
            self.start_speech(self.current_reply, "wake")
        logging.getLogger("nisha").info("Wake acknowledged in the current conversation.")

    def bring_forward(self):
        if self.closing:
            return
        self.in_background = False
        self.idle_checkins.activity()
        self.showNormal()
        self.raise_()
        self.activateWindow()
        self.input.setFocus()
        if self.listener and not self.muted:
            self.listener.engine.background.clear()
            self.listener.engine.resume(follow_up=self.voice_awake, wake_only=self.busy())
            self.set_state("Listening" if self.voice_awake else "Waiting for NISHA")

    def open_fresh(self):
        if self.closing:
            return
        running = self.busy()
        if running:
            self.worker.requestInterruption()
        self.turn_generation += 1
        self.pending_voice = None
        self.pending_wake_ack = False
        self.pending_quiet_ack = False
        self.idle_reply_until = 0
        self.idle_prompt = None
        self.conversation_engaged = False
        self.voice_awake = False
        self.stop_visual_tour()
        if self.listener:
            self.listener.engine.end_output()
            self.listener.engine.wait_for_wake()
        self.wake_during_turn = False
        self.bring_forward()
        logging.getLogger("nisha").info("Manual opening is idle until a wake word.")

    def hide_to_background(self):
        if self.closing:
            return
        if self.on_demand:
            self.quit_application()
            return
        self.pending_voice = None
        self.pending_wake_ack = False
        self.pending_quiet_ack = False
        self.idle_reply_until = 0
        self.idle_prompt = None
        self.conversation_engaged = False
        self.voice_awake = False
        self.wake_during_turn = False
        if self.busy():
            self.worker.requestInterruption()
        self.core.end_conversation(self.session)
        QTimer.singleShot(500, self.review_closed_conversations)
        self.in_background = True
        self.visual_panel.dismiss()
        self.chat_panel.dismiss()
        self.hide()
        if self.listener:
            self.listener.engine.end_output()
            self.listener.engine.wait_for_wake()
            self.listener.engine.resume(wake_only=self.busy())
            self.listener.engine.background.set()
        self.set_state("Muted" if self.muted else "Waiting for NISHA")

    def close_requested(self):
        if self.closing:
            return
        if self.on_demand:
            self.quit_application()
            return
        self.hide_to_background()

    def interrupt_reply(self):
        if self.closing:
            return
        self.pending_wake_ack = False
        self.pending_voice = None
        self.tour_enabled = False
        self.idle_checkins.suppress()
        self.wake_during_turn = False
        if self.busy():
            self.worker.requestInterruption()
        if self.listener:
            self.listener.engine.end_output()
            self.listener.engine.resume(follow_up=True, wake_only=self.busy())
        self.set_state("Muted" if self.muted else "Listening")

    def quit_application(self):
        self.quit_requested = True
        self.close()

    def setup_tray(self):
        from nisha.ui.resident import LoginStartup

        self.login_startup = LoginStartup(self.core.settings.data_dir)
        self.tray = QSystemTrayIcon(self.windowIcon(), self)
        self.tray.setToolTip("NISHA · listening for your wake word")
        menu = QMenu(self)
        show = menu.addAction("Open NISHA")
        show.triggered.connect(self.open_fresh)
        new = menu.addAction("New conversation")
        new.triggered.connect(lambda: (self.new_conversation(), self.bring_forward()))
        if not self.on_demand:
            hide = menu.addAction("Hide window · keep listening")
            hide.triggered.connect(self.hide_to_background)
        self.mute_action = QAction("Mute microphone", menu)
        self.mute_action.setCheckable(True)
        self.mute_action.setChecked(self.muted)
        self.mute_action.triggered.connect(self.toggle_mute)
        menu.addAction(self.mute_action)
        self.startup_action = QAction("Start with Windows", menu)
        self.startup_action.setCheckable(True)
        self.startup_action.setChecked(self.login_startup.enabled())
        self.startup_action.triggered.connect(self.change_login_startup)
        menu.addAction(self.startup_action)
        menu.addSeparator()
        menu.addAction("Personal voice samples · Ctrl+R").triggered.connect(self.voice_samples)
        quit_action = menu.addAction("Quit NISHA · stop listening")
        quit_action.triggered.connect(self.quit_application)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(
            lambda reason: (
                self.open_fresh()
                if reason in {QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick}
                else None
            )
        )
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray.show()

    def change_login_startup(self, enabled):
        try:
            self.login_startup.set_enabled(enabled)
        except NishaError as exc:
            plain_warning(self, "Windows startup", str(exc))
        self.startup_action.setChecked(self.login_startup.enabled())

    def heard_command(self, text):
        if self.in_background or (
            not self.voice_awake and self.idle_reply_until <= self.conversation_clock()
        ):
            return
        hint = self.accept_checkin_reply()
        self.last_conversation_activity = self.conversation_clock()
        self.pending_wake_ack = False
        if not self.muted and not self.closing and self.queue_action(text):
            if self.listener and not self.busy():
                self.listener.engine.resume(follow_up=True)
            return
        if not self.muted and not self.closing and self.busy():
            if self.wake_during_turn:
                self.pending_voice = (self.session, text, False)
            if self.listener:
                self.listener.engine.resume(wake_only=True)
            return
        if not self.muted and not self.busy() and not self.closing:
            if self.ui_command(text):
                self.listener.engine.resume(follow_up=self.voice_awake)
                return
            if text.casefold().strip(".! ") in {"setup gmail", "connect gmail", "gmail setup"}:
                self.setup_gmail()
                self.listener.engine.resume(follow_up=True)
                return
            if text.casefold().strip(".! ") in {
                "review email",
                "send email",
                "send it",
            } and self.core.store.pending_email(self.session):
                self.review_email()
                self.listener.engine.resume(follow_up=True)
                return
            self.start_turn(text, voice=True, assistant_prompt=hint)

    def heard_uncertain(self, text):
        if self.in_background or (
            not self.voice_awake and self.idle_reply_until <= self.conversation_clock()
        ):
            return
        hint = self.accept_checkin_reply()
        self.last_conversation_activity = self.conversation_clock()
        self.pending_wake_ack = False
        if not self.muted and not self.closing and self.busy():
            if self.wake_during_turn:
                self.pending_voice = (self.session, text, True)
            if self.listener:
                self.listener.engine.resume(wake_only=True)
            return
        if not self.muted and not self.busy() and not self.closing:
            self.start_turn(text, voice=True, uncertain=True, assistant_prompt=hint)

    def accept_checkin_reply(self):
        hint = self.idle_prompt if self.idle_reply_until > self.conversation_clock() else None
        self.idle_reply_until = 0
        self.idle_prompt = None
        if hint:
            self.voice_awake = True
            self.idle_checkins.activity()
        return hint

    def listener_error(self, text):
        self.listener_failed = True
        self.wall_widget.mic_label.set_muted(self.muted)
        self.chat_panel.record_background("", text)
        if not self.busy():
            self.set_state("Listening unavailable")

    def recover_background(self):
        from nisha.gateway import Gateway
        from nisha.ui.jobs import ServiceJob

        if self.closing:
            return
        if (
            self.spoken_wake_enabled
            and not self.muted
            and self.listener
            and not self.listener.isRunning()
        ):
            logging.getLogger("nisha").info(
                "Restarting failed microphone listener; following Windows default input."
            )
            self.listener_failed = False
            self.start_listening()
        if isinstance(self.core.gateway, Gateway) and not any(
            isinstance(job, ServiceJob) and job.isRunning() for job in self.background_jobs
        ):
            self.track_job(ServiceJob(self.core.settings))

    def busy(self):
        return self.worker is not None and self.worker.isRunning()

    def render(self):
        from nisha.ui.presentation import uses_results

        results = (
            self.result_turn if self.result_turn is not None else uses_results(self.current_user)
        )
        self.chat_panel.record(self.current_user, self.current_reply, results)
        self.wall_widget.set_conversation(
            self.current_user,
            "The result is in the glass panel."
            if results and self.current_reply
            else self.current_reply,
        )
        if results and not self.in_background and not self.closing and not self.results_dismissed:
            self.visual_panel.set_response(self.current_user, self.current_reply)
            youtube = getattr(self.core.actions, "youtube", None)
            self.visual_panel.review_button.setVisible(bool(youtube and youtube.pending))
        self.wall_widget.email_button.setVisible(bool(self.core.store.pending_email(self.session)))

    def set_state(self, state):
        self.table_status.setText("● " + state)
        orb_state = {
            "Listening": "listening",
            "Transcribing": "thinking",
            "Thinking": "thinking",
            "Speaking": "speaking",
        }.get(state, "idle")
        self.wall_widget.orb.set_state(orb_state)
        self.wall_widget.set_listening(
            state in {"Listening", "Waiting for NISHA"} and not self.muted
        )
        self.wall_widget.mic_label.setToolTip(
            ("Muted · click to unmute" if self.muted else state + " · click to mute")
            + " (Ctrl+Space)"
        )

    def toggle_speech(self):
        self.speak_responses = not self.speak_responses
        self.table_status.setText("● Speech " + ("on" if self.speak_responses else "off"))

    def new_conversation(self, force=False):
        if (self.busy() and not force) or self.closing:
            return
        self.pending_voice = None
        self.action_queue.clear()
        self.action_results.clear()
        self.pending_typed.clear()
        if self.action_job:
            self.action_job.requestInterruption()
        self.turn_generation += 1
        self.pending_wake_ack = False
        self.pending_quiet_ack = False
        self.idle_reply_until = 0
        self.idle_prompt = None
        self.conversation_engaged = False
        self.voice_awake = False
        self.wake_during_turn = False
        self.core.end_conversation(self.session)
        self.session = self.core.new_session()
        self.save_session(self.session)
        self.current_user = self.current_reply = ""
        self.invalidate_visuals()
        self.stop_visual_tour()
        self.chat_panel.clear()
        self.result_turn = None
        self.idle_checkins.activity()
        self.input.clear()
        self.wall_widget.conversation_label.clear()
        self.wall_widget.content_label.clear()
        self.wall_widget.email_button.hide()
        self.visual_panel.dismiss()
        self.visual_panel.clear()
        self.results_dismissed = False
        self.last_visual_topic = ""
        if self.listener:
            self.listener.engine.wait_for_wake()
        self.set_state("Muted" if self.muted else "Waiting for NISHA")

    def submit(self):
        text = self.control_text(self.input.text().strip())
        if not text or self.closing:
            return
        self.pending_wake_ack = False
        if self.queue_action(text):
            self.input.clear()
            return
        if self.busy():
            from nisha.interaction import is_quiet_request
            from nisha.listening import (
                is_close_phrase,
                is_fresh_conversation_phrase,
                is_stop_phrase,
            )

            if (
                is_close_phrase(text)
                or is_stop_phrase(text)
                or is_quiet_request(text)
                or is_fresh_conversation_phrase(text)
                or text == "/new"
            ):
                self.input.clear()
                self.ui_command(text)
            else:
                if len(self.pending_typed) >= 8:
                    self.show_notice("The conversation queue is full. Please wait for a reply.")
                    return
                self.pending_typed.append((self.session, text))
                self.input.clear()
            return
        self.input.clear()
        if text == "/new":
            self.start_fresh_requested(text)
            return
        if self.ui_command(text):
            return
        if text.casefold() in {"setup gmail", "connect gmail", "/gmail"}:
            self.setup_gmail()
            return
        if text.casefold().strip(".! ") in {
            "review email",
            "send email",
            "send it",
        } and self.core.store.pending_email(self.session):
            self.review_email()
            return
        if text.startswith("/use "):
            self.chat_panel.begin_turn()
            self.result_turn = False
            self.visual_panel.dismiss()
            alias = text[5:].strip()
            profile = self.core.settings.models.get(alias)
            if profile is None or not profile.local:
                self.current_user, self.current_reply = text, "Choose a configured local model."
            else:
                self.alias = alias
                self.current_user, self.current_reply = text, "Local model: " + alias
            self.render()
            return
        if text.startswith("/remember "):
            self.chat_panel.begin_turn()
            self.result_turn = False
            self.visual_panel.dismiss()
            fact = text[10:].strip()
            key, sep, value = fact.partition("=")
            try:
                self.core.memory.remember(value if sep else fact, key=key.strip() if sep else None)
                reply = "Saved as a local-only memory."
            except ValueError as exc:
                reply = str(exc)
            self.current_user, self.current_reply = text, reply
            self.render()
            return
        self.start_turn(text)

    def start_turn(self, text, voice=False, uncertain=False, assistant_prompt=None):
        from nisha.ui.presentation import uses_results

        if self.start_camera_vision(text, voice=voice):
            return
        self.pending_wake_ack = False
        self.pending_quiet_ack = False
        assistant_prompt = assistant_prompt or self.accept_checkin_reply()
        self.voice_awake = True
        self.last_conversation_activity = self.conversation_clock()
        self.turn_generation += 1
        self.result_turn = not uncertain and uses_results(text, previous=self.result_turn)
        self.chat_panel.begin_turn()
        self.results_dismissed = False
        self.invalidate_visuals()
        self.idle_checkins.activity()
        self.stop_visual_tour()
        self.visual_panel.dismiss()
        self.results_dismissed = False
        self.visual_panel.clear()
        self.visual_descriptions.clear()
        self.visual_reviewing.clear()
        self.tour_done.clear()
        self.tour_enabled = not uncertain
        self.visual_lookup_started = uncertain
        self.turn_failed = False
        self.voice_turn = voice
        if self.listener:
            self.listener.engine.pause()
        self.current_user, self.current_reply = text, ""
        self.render()
        self.input.setEnabled(True)
        self.input.setPlaceholderText("Type a command while NISHA responds…")
        self.worker = TurnWorker(
            self.core,
            self.session,
            self.alias,
            text,
            self.speak_responses or voice,
            self.listener.engine.quiet if self.listener else None,
            uncertain,
            self.listener.engine.begin_output if self.listener else None,
            self.listener.engine.end_output if self.listener else None,
            assistant_prompt=assistant_prompt,
        )
        session = self.session
        generation = self.turn_generation
        self.worker.chunk.connect(
            lambda text, session=session, generation=generation: (
                self.append_chunk(text)
                if session == self.session and generation == self.turn_generation
                else None
            )
        )
        self.worker.state.connect(
            lambda state, session=session, generation=generation: (
                self.turn_state(state)
                if session == self.session and generation == self.turn_generation
                else None
            )
        )
        self.worker.error.connect(
            lambda text, session=session, generation=generation: (
                self.show_error(text)
                if session == self.session and generation == self.turn_generation
                else None
            )
        )
        self.worker.finished.connect(self.finish_turn)
        self.worker.start()

    def start_camera_vision(self, text, voice=False):
        """Answer one explicit camera question from one fresh local snapshot."""
        import re

        from nisha.ui.jobs import CameraVisionJob

        normalized = self.control_text(text).casefold().strip(".!? ")
        request = re.fullmatch(
            r"(?:what do you see|what is visible)(?: in| through) (?:the )?(.+)|"
            r"what(?:'s| is) in (?:the )?(.+)|describe (?:the )?(.+)",
            normalized,
        )
        if normalized in {"what do you see", "what can you see"}:
            target = ""
        elif request:
            target = next((group for group in request.groups() if group), "")
        else:
            return False
        target = re.sub(r"\s+(?:feed|snapshot)$", "", target).strip()
        configured = self.core.connections.load().devices
        cameras = self.core.devices.matches(target, {"camera"}) if target else [d for d in configured if d.kind == "camera"]
        if not cameras:
            self.show_notice("No matching camera is configured. Add a camera snapshot endpoint in Ctrl+D.")
            return True
        if len(cameras) > 1:
            self.show_notice("Name one camera so I know which live snapshot to inspect.")
            return True
        device = cameras[0]
        if not device.snapshot:
            self.show_notice(f"{device.name} has a stream but no snapshot endpoint. Configure a snapshot to ask visual questions.")
            return True
        assets = self.core.devices.camera_assets(device.name)
        if not assets:
            self.show_notice(f"{device.name} has no usable snapshot endpoint.")
            return True
        self.pending_wake_ack = False
        self.voice_awake = True
        self.last_conversation_activity = self.conversation_clock()
        self.idle_checkins.activity()
        self.stop_visual_tour()
        self.turn_generation += 1
        generation, session = self.turn_generation, self.session
        self.voice_turn = voice
        self.chat_panel.begin_turn()
        self.result_turn = True
        self.current_user = text
        self.current_reply = f"Checking one current snapshot from {device.name} locally…"
        self.render()
        if self.listener:
            self.listener.engine.pause()
        job = CameraVisionJob(self.core.devices, self.vision, assets[0], text, generation)
        job.done.connect(lambda answer, gen, session=session: self.finish_camera_vision(answer, gen, session))
        self.track_job(job)
        return True

    def finish_camera_vision(self, answer, generation, session):
        if session != self.session or generation != self.turn_generation or self.closing:
            return
        self.current_reply = answer + "\n\nOne snapshot analyzed locally; no video was recorded."
        self.core.store.exchange(session, self.current_user, self.current_reply, cloud_allowed=False)
        self.render()
        if self.voice_turn and not self.muted:
            self.start_speech(self.current_reply, "camera")
        elif self.listener and not self.muted:
            self.listener.engine.resume(follow_up=True)

    def append_chunk(self, text):
        self.current_reply += text
        self.render()
        if text.strip() and not getattr(self, "visual_lookup_started", True):
            self.visual_lookup_started = True
            self.find_visuals(self.current_user)

    def turn_state(self, state):
        if self.in_background or self.closing:
            return
        if self.listener and state == "Thinking":
            # Accept only a new explicit wake while the current operation runs.
            self.listener.engine.resume(wake_only=True)
        self.set_state(state)

    def show_error(self, text):
        self.turn_failed = True
        dismissed_by_user = self.results_dismissed
        self.stop_visual_tour()
        self.invalidate_visuals()
        self.visual_panel.clear()
        self.visual_panel.dismiss()
        self.results_dismissed = dismissed_by_user
        self.current_reply += "\n[" + text + "]"
        self.render()

    def finish_turn(self):
        mode = getattr(self.worker, "mode", "reply")
        interrupted = bool(self.worker and self.worker.isInterruptionRequested())
        if self.voice_awake and not self.in_background and mode != "idle":
            self.last_conversation_activity = self.conversation_clock()
        if mode == "reply":
            self.idle_checkins.last_activity = self.idle_checkins.clock()
            if (
                not interrupted
                and not self.in_background
                and getattr(self.worker, "session", self.session) == self.session
            ):
                self.conversation_engaged = bool(self.core.store.history(self.session)[1])
        self.input.setEnabled(True)
        self.input.setPlaceholderText("Type a question…")
        while self.pending_typed and self.pending_typed[0][0] != self.session:
            self.pending_typed.pop(0)
        if self.pending_typed and not self.closing and not self.in_background:
            _, text = self.pending_typed.pop(0)
            # Preserve anything currently being typed in the composer.
            draft = self.input.text()
            self.input.setText(text)
            self.submit()
            self.input.setText(draft)
            if not self.busy():
                QTimer.singleShot(0, self.finish_turn)
            return
        pending = self.pending_voice
        self.pending_voice = None
        self.wake_during_turn = False
        if (
            pending
            and pending[0] == self.session
            and not self.closing
            and not self.muted
            and not self.in_background
        ):
            if pending[2]:
                self.heard_uncertain(pending[1])
            else:
                self.heard_command(pending[1])
            return
        inviting = (
            mode == "idle"
            and not interrupted
            and not self.voice_awake
            and not self.in_background
            and not self.closing
            and not self.core.interaction.quiet
        )
        if inviting:
            self.idle_reply_until = self.conversation_clock() + 30
        if self.listener and not self.closing:
            if inviting:
                self.listener.engine.invite_reply(30)
            elif self.in_background or not self.voice_awake:
                self.listener.engine.wait_for_wake()
                self.listener.engine.resume()
            else:
                self.listener.engine.resume(follow_up=self.isVisible())
        self.set_state(
            "Muted"
            if self.muted
            else "Listening"
            if self.listener
            and (self.voice_awake or inviting)
            and not self.in_background
            and self.isVisible()
            else "Waiting for NISHA"
        )
        self.input.setFocus()
        if self.pending_wake_ack:
            self.acknowledge_wake()
        if self.pending_quiet_ack:
            self.acknowledge_quiet()
        if mode == "visual" and not interrupted and self.tour_enabled and self.visual_panel.assets:
            index = self.visual_panel.index
            self.tour_done.add(index)
            if index + 1 < len(self.visual_panel.assets):
                QTimer.singleShot(1800, self.next_tour_visual)
        elif mode == "reply" and not interrupted and not getattr(self, "turn_failed", False):
            QTimer.singleShot(300, self.try_visual_tour)
        if not self.busy():
            self.show_action_results()

    def closeEvent(self, event):
        if self.background_enabled and not self.quit_requested and not self.on_demand:
            self.hide_to_background()
            event.ignore()
            return
        self.closing = True
        self.recovery_timer.stop()
        from nisha.ui.jobs import ActionJob, ServiceJob

        self.action_queue.clear()
        for job in self.background_jobs:
            if isinstance(job, (ServiceJob, ActionJob)):
                job.requestInterruption()
        self.core.end_conversation(self.session)
        self.learning_timer.stop()
        self.device_poll_timer.stop()
        self.idle_timer.stop()
        if self.listener:
            self.listener.engine.stop()
        if self.busy():
            self.worker.requestInterruption()
        self.visual_panel.dismiss()
        self.chat_panel.dismiss()
        if (
            self.busy()
            or (self.listener and self.listener.isRunning())
            or any(job.isRunning() for job in self.background_jobs)
        ):
            self.set_state("Finishing operation")
            event.ignore()
            QTimer.singleShot(100, self.close)
        else:
            if self.tray:
                self.tray.hide()
            event.accept()
            if self.exit_on_close:
                QApplication.instance().quit()

    def review_closed_conversations(self):
        # Tests with a supplied gateway never spawn a real model subprocess.
        from nisha.gateway import Gateway

        if (
            not self.closing
            and not self.busy()
            and not self.voice_awake
            and QApplication.activeModalWidget() is None
            and isinstance(self.core.gateway, Gateway)
        ):
            self.core.learning.launch()

    def control_text(self, text):
        from nisha.listening import WakeGate

        command = WakeGate(
            self.core.settings.voice.wake_word, aliases=self.core.settings.voice.wake_aliases
        ).accept(text)
        return command if command else text

    def ui_command(self, text):
        from nisha.interaction import is_quiet_request, is_silent_request
        from nisha.listening import (
            is_close_phrase,
            is_fresh_conversation_phrase,
            is_stop_phrase,
        )

        text = self.control_text(text)

        if text == "/new" or is_fresh_conversation_phrase(text):
            self.start_fresh_requested(text)
            return True

        if is_quiet_request(text):
            (self.silent_requested if is_silent_request(text) else self.quiet_requested)()
            return True

        if is_stop_phrase(text):
            self.interrupt_reply()
            return True
        if is_close_phrase(text):
            self.close_requested()
            return True
        normalized = text.casefold().strip(".! ")
        if normalized in {
            "/voice-samples",
            "record my voice",
            "train my voice",
            "personal voice samples",
        }:
            self.voice_samples()
            return True
        if normalized in {"hide nisha", "hide window", "close nisha window", "/hide"}:
            self.hide_to_background()
            return True
        if normalized in {
            "setup devices",
            "connect devices",
            "setup connections",
            "configure devices",
            "setup routines",
            "setup project",
            "/connections",
        }:
            self.setup_connections()
            return True
        camera = re.fullmatch(
            r"(?:show|view|open) (?:me )?(?:the |my )?(.+?)(?: visuals| feed)?", normalized
        )
        if camera and re.search(r"\bcctv\b|\bcameras?\b", camera[1]):
            self.chat_panel.begin_turn()
            assets = self.core.devices.camera_assets(camera[1])
            self.visual_panel.dismiss()
            if assets:
                self.present_assets(assets, self.load_visual_image, self.core.devices.stream_url)
                reply = (
                    "Connecting "
                    + ", ".join(asset.title for asset in assets)
                    + ". The panel shows the actual connection or snapshot status."
                )
            else:
                reply = "That camera isn't configured. Add its direct stream or snapshot endpoint in Ctrl+D."
            self.current_user, self.current_reply = text, reply
            self.result_turn = True
            self.results_dismissed = False
            self.core.store.exchange(self.session, text, reply, cloud_allowed=False)
            self.render()
            return True
        if normalized in {"learn from my data", "add knowledge", "open learning", "/learn"}:
            self.learning_dialog()
            return True
        if normalized in {"setup worker", "connect task model", "/worker"}:
            self.setup_worker()
            return True
        if normalized in {"external task", "use an external model", "/task"}:
            self.external_task_dialog()
            return True
        if normalized in {"hide visuals", "close visuals", "close image", "hide image"}:
            self.visual_panel.dismiss()
            return True
        if normalized.startswith("/show "):
            asset = self.media_service.local_file(text[len("/show ") :].strip().strip('"'))
            if asset:
                self.invalidate_visuals()
                self.present_assets([asset], self.load_visual_image)
            else:
                self.show_notice("Select an existing image or video with Ctrl+I.")
            return True
        return False

    def track_job(self, job):
        job.setParent(self)
        self.background_jobs.append(job)
        job.finished.connect(
            lambda job=job: (
                self.background_jobs.remove(job) if job in self.background_jobs else None
            )
        )
        job.finished.connect(job.deleteLater)
        job.start()

    def queue_action(self, text):
        from nisha.responsiveness import action_request

        if not self.core.settings.background_actions:
            return False
        if text.casefold().strip(" .!?") == "cancel background tasks":
            self.action_queue.clear()
            if self.action_job:
                self.action_job.requestInterruption()
            self.chat_panel.record_background(
                text, "Cancelling background work. Already completed actions are not undone."
            )
            return True
        if not action_request(text) and not self.core.automation.matches_trigger(text):
            return False
        if len(self.action_queue) >= 8:
            self.chat_panel.record_background(
                text, "The action queue is full. Wait for an action to finish."
            )
            return True
        _, history = self.core.store.history(self.session)
        self.action_queue.append((self.session, self.alias, text, history))
        self.chat_panel.record_background(text, "Queued.")
        if not self.busy():
            self.set_state("Working in background")
        self.start_next_action()
        return True

    def start_next_action(self):
        from nisha.ui.jobs import ActionJob

        if self.closing or self.action_job or not self.action_queue:
            return
        session, alias, text, history = self.action_queue.pop(0)
        if session != self.session:
            self.start_next_action()
            return
        job = ActionJob(self.core, session, alias, text, history)
        self.action_job = job
        job.done.connect(lambda reply: self.action_completed(session, text, reply))
        job.failed.connect(
            lambda error: self.action_completed(session, text, "Action failed: " + error)
        )
        job.finished.connect(self.action_finished)
        self.track_job(job)

    def action_completed(self, session, text, reply):
        if self.closing or session != self.session:
            return
        self.chat_panel.record_background(text, reply)
        self.action_results.append((text, reply))
        self.wall_widget.email_button.setVisible(bool(self.core.store.pending_email(self.session)))
        self.show_action_results()

    def action_finished(self):
        self.action_job = None
        self.start_next_action()

    def show_action_results(self):
        if self.busy() or self.closing or not self.action_results:
            return
        if self.in_background or self.muted or self.core.interaction.quiet:
            self.action_results.clear()  # Full receipts are already in the chat log.
            return
        from nisha.ui.action_reports import spoken_action_report

        _, reply = self.action_results.pop(0)
        self.start_speech(spoken_action_report(reply), "action")

    def invalidate_visuals(self):
        self.visual_generation += 1

    def show_notice(self, text):
        if not self.in_background and not self.closing:
            self.chat_panel.record_background("", text)
            self.action_results.append(("", text))
            QTimer.singleShot(0, self.show_action_results)

    def toggle_conversation(self):
        if self.closing or self.in_background:
            return
        self.idle_checkins.activity()
        if self.chat_panel.isVisible():
            self.chat_panel.dismiss()
        else:
            self.chat_panel.open()
            self.wall_widget.set_chat_open(True)

    def conversation_closed(self):
        self.wall_widget.set_chat_open(False)

    def stop_visual_tour(self):
        self.tour_enabled = False
        if self.busy() and getattr(self.worker, "mode", "") == "visual":
            self.worker.requestInterruption()

    def results_closed(self):
        self.stop_visual_tour()
        self.results_dismissed = True

    def quiet_requested(self):
        from nisha.interaction import QUIET_REPLY

        self.core.interaction.set_quiet(True)
        self.enter_voice_idle()
        self.idle_checkins.suppress()
        self.show_dialogue(QUIET_REPLY)
        self.pending_quiet_ack = True
        QTimer.singleShot(100, self.acknowledge_quiet)

    def silent_requested(self):
        self.core.interaction.set_quiet(True)
        self.enter_voice_idle()
        self.idle_checkins.suppress()
        self.pending_quiet_ack = False

    def acknowledge_quiet(self):
        from nisha.interaction import QUIET_REPLY

        if not self.pending_quiet_ack:
            return
        if self.closing or self.in_background or self.muted:
            self.pending_quiet_ack = False
            return
        if self.busy():
            return  # finish_turn delivers this after the cancelled speech has stopped.
        self.pending_quiet_ack = False
        if self.spoken_wake_enabled:
            self.start_speech(QUIET_REPLY, "quiet")

    def show_dialogue(self, text):
        self.chat_panel.begin_turn()
        self.result_turn = False
        self.current_user, self.current_reply = "", text
        self.render()

    def review_youtube(self):
        youtube = getattr(self.core.actions, "youtube", None)
        if self.busy() or not youtube or len(youtube.pending) != 1:
            return
        token, item = next(iter(youtube.pending.items()))
        if item.get("session") != self.session:
            return
        preview = item["preview"]
        if self.listener:
            self.listener.engine.pause()
        dialog = QDialog(self)
        dialog.setWindowTitle("Review YouTube account action")
        layout = QVBoxLayout(dialog)
        label = QLabel(
            f"{preview['action'].title()}: {preview['title']}\n{preview['url']}\nThis will use the account in your current browser. The page must still match after approval."
        )
        label.setTextFormat(Qt.PlainText)
        label.setWordWrap(True)
        layout.addWidget(label)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Approve action")
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        accepted = dialog.exec() == QDialog.Accepted
        if self.listener:
            self.listener.engine.resume(follow_up=True)
        if accepted:
            self.start_turn("approve youtube " + token)
        else:
            youtube.pending.clear()
            self.render()

    def start_speech(self, text, mode):
        if self.busy() or self.closing or self.muted or self.in_background:
            return
        if self.listener:
            self.listener.engine.pause()
        self.worker = SpeechWorker(
            self.core,
            text,
            mode,
            self.listener.engine.begin_output if self.listener else None,
            self.listener.engine.end_output if self.listener else None,
            self.listener.engine.quiet if self.listener else None,
        )
        generation = self.turn_generation
        self.worker.state.connect(
            lambda state, generation=generation: (
                self.turn_state(state) if generation == self.turn_generation else None
            )
        )
        self.worker.finished.connect(self.finish_turn)
        self.voice_turn = True
        self.worker.start()

    def check_idle(self):
        if (
            self.idle_reply_until
            and self.conversation_clock() >= self.idle_reply_until
            and not self.busy()
        ):
            self.idle_reply_until = 0
            self.idle_prompt = None
            if self.listener:
                self.listener.engine.wait_for_wake()
                self.listener.engine.resume()
            self.set_state("Muted" if self.muted else "Waiting for NISHA")
        if (
            self.voice_awake
            and not self.in_background
            and not self.closing
            and self.conversation_clock() - self.last_conversation_activity >= 120
            and (not self.busy() or getattr(self.worker, "mode", "") == "idle")
        ):
            self.enter_voice_idle()
            return
        youtube = getattr(self.core.actions, "youtube", None)
        pending_youtube = bool(
            youtube and any(item["expires"] > youtube.clock() for item in youtube.pending.values())
        )
        available = (
            self.idle_enabled
            and not self.voice_awake
            and not self.idle_reply_until
            and self.isVisible()
            and not self.in_background
            and not self.busy()
            and not self.muted
            and not self.closing
            and QApplication.activeModalWidget() is None
            and not self.core.store.pending_email(self.session)
            and not pending_youtube
        )
        message = self.idle_checkins.due(available, self.core.interaction.quiet)
        if message:
            self.idle_prompt = message
            self.show_dialogue(message)
            self.start_speech(message, "idle")

    def enter_voice_idle(self):
        if self.busy():
            self.worker.requestInterruption()
            self.turn_generation += 1
        self.pending_voice = None
        self.pending_wake_ack = False
        self.pending_quiet_ack = False
        self.idle_reply_until = 0
        self.idle_prompt = None
        self.voice_awake = False
        self.conversation_engaged = False
        self.stop_visual_tour()
        self.idle_checkins.activity()
        if self.listener:
            self.listener.engine.end_output()
            self.listener.engine.wait_for_wake()
            self.listener.engine.resume()
        self.set_state("Muted" if self.muted else "Waiting for NISHA")
        logging.getLogger("nisha").info(
            "Two minutes without conversation; waiting for a wake word."
        )

    def visual_changed(self, index):
        if self.busy() and getattr(self.worker, "mode", "") == "visual":
            self.worker.requestInterruption()
        if index in self.visual_descriptions:
            self.visual_panel.caption.setText(self.visual_descriptions[index])
            QTimer.singleShot(300, self.try_visual_tour)

    def describe_visual(self, data, index):
        from nisha.ui.jobs import VisionJob

        if (
            not self.visual_panel.assets
            or self.visual_panel.assets[index].kind not in {"image", "video"}
            or index in self.visual_reviewing
        ):
            return
        self.visual_reviewing.add(index)
        job = VisionJob(self.vision, data, index, self.visual_generation)
        job.done.connect(self.visual_described)
        self.track_job(job)

    def visual_described(self, description, index, generation):
        if generation != self.visual_generation or index >= len(self.visual_panel.assets):
            return
        asset = self.visual_panel.assets[index]
        topic = self.last_visual_topic or asset.title
        frame_note = (
            " From one sampled frame, not a full video analysis." if asset.kind == "video" else ""
        )
        explanation = f"Reference {index + 1}: {asset.title}. {description}{frame_note}\nShown as a related visual for {topic}."
        self.visual_descriptions[index] = explanation
        if index == self.visual_panel.index:
            self.visual_panel.caption.setText(explanation + "\n" + asset.caption)
        self.try_visual_tour()

    def try_visual_tour(self):
        if (
            not self.tour_enabled
            or self.core.interaction.quiet
            or self.busy()
            or not self.visual_panel.isVisible()
            or self.muted
            or self.in_background
            or self.closing
        ):
            return
        index = self.visual_panel.index
        if index in self.visual_descriptions and index not in self.tour_done:
            self.start_speech(self.visual_descriptions[index], "visual")

    def next_tour_visual(self):
        if (
            self.tour_enabled
            and not self.busy()
            and self.visual_panel.isVisible()
            and self.visual_panel.index in self.tour_done
            and self.visual_panel.index + 1 < len(self.visual_panel.assets)
        ):
            self.visual_panel.advance(1)

    def find_visuals(self, text):
        from nisha.media import public_topic
        from nisha.ui.jobs import VisualJob

        self.invalidate_visuals()
        if text.casefold().strip(".! ") in {
            "show me pictures of him",
            "show me pictures of her",
            "show me images of it",
            "show pictures",
        }:
            text = "show me pictures of " + self.last_visual_topic
        topic = public_topic(text)
        if topic:
            self.last_visual_topic = topic
        elif not self.media_service.local_matches(text):
            return
        # A local reference or personal identifier keeps the lookup on this PC.
        private = (
            not self.core.settings.online_visuals
            or bool(self.core.knowledge.search(text))
            or any(name.casefold() in text.casefold() for name in self.core.settings.contacts)
            or bool(self.core.memory.search(topic or text))
        )
        job = VisualJob(self.media_service, self.visual_generation, text=text, private=private)
        job.found.connect(self.show_visuals)
        job.failed.connect(self.visual_failure)
        self.track_job(job)

    def show_visuals(self, assets, generation):
        if (
            generation == self.visual_generation
            and assets
            and not self.closing
            and not self.in_background
            and not self.results_dismissed
        ):
            self.present_assets(assets, self.load_visual_image, auto_narrate=self.tour_enabled)

    def present_assets(self, assets, loader, stream_resolver=None, auto_narrate=True):
        self.stop_visual_tour()
        self.invalidate_visuals()
        self.visual_descriptions.clear()
        self.visual_reviewing.clear()
        self.tour_done.clear()
        self.results_dismissed = False
        self.tour_enabled = auto_narrate and any(
            asset.kind in {"image", "video"} for asset in assets
        )
        self.visual_panel.present(assets, loader, stream_resolver)

    def visual_failure(self, message, generation):
        if generation == self.visual_generation:
            logging.getLogger("nisha").info("Public visual lookup unavailable")
            self.wall_widget.mic_label.setToolTip(message + " · Ctrl+I opens local media")

    def load_visual_image(self, asset, index):
        from nisha.ui.jobs import VisualJob

        if asset.kind == "camera_snapshot" and any(
            getattr(job, "asset", None) and job.asset.kind == "camera_snapshot" and job.isRunning()
            for job in self.background_jobs
        ):
            return
        self.invalidate_visuals()
        service = self.core.devices if asset.kind == "camera_snapshot" else self.media_service
        job = VisualJob(service, self.visual_generation, asset=asset, index=index)
        job.image.connect(
            lambda data, index, generation: (
                self.visual_panel.image_ready(data, index)
                if generation == self.visual_generation
                else None
            )
        )
        job.failed.connect(
            lambda message, generation: (
                self.visual_panel.image_failed(message)
                if generation == self.visual_generation
                else None
            )
        )
        self.track_job(job)

    def open_gesture_studio(self):
        if self.busy() or self.closing:
            return
        from nisha.ui.gesture_studio import GestureStudioDialog

        if self.listener:
            self.listener.engine.pause()
        try:
            GestureStudioDialog(self).exec()
        finally:
            if self.listener and not self.closing:
                self.listener.engine.resume(follow_up=True)

    def setup_connections(self):
        if self.busy() or self.closing:
            return
        from nisha.ui.connections_dialog import ConnectionsDialog

        if self.listener:
            self.listener.engine.pause()
        try:
            dialog = ConnectionsDialog(self.core.connections, self)
            if dialog.exec() == QDialog.Accepted:
                self.visual_panel.dismiss()
                self.show_notice(
                    "Local connections saved. Say 'check devices', 'open my project folder' or 'do the usual setup' once configured."
                )
                self.poll_devices()
        finally:
            if self.listener:
                self.listener.engine.resume(follow_up=True)

    def poll_devices(self):
        from nisha.ui.jobs import DevicePollJob

        if self.closing or any(
            isinstance(job, DevicePollJob) and job.isRunning() for job in self.background_jobs
        ):
            return
        job = DevicePollJob(self.core.devices)
        job.done.connect(
            lambda status: (
                self.wall_widget.devices_label.setText(status.split("\n", 1)[0]),
                self.wall_widget.devices_label.setToolTip(status + "\nCtrl+D · setup"),
            )
        )
        self.track_job(job)

    def choose_media(self):
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "Show image or video",
            "",
            "Media (*.png *.jpg *.jpeg *.webp *.bmp *.gif *.mp4 *.webm *.mov *.mkv *.avi)",
        )
        if filename:
            self.ui_command("/show " + filename)

    def learning_dialog(self):
        if self.busy() or self.closing:
            return
        if self.listener:
            self.listener.engine.pause()
        dialog = QDialog(self)
        dialog.setWindowTitle("NISHA · Local learning")
        dialog.resize(720, 600)
        layout = QVBoxLayout(dialog)
        note = QLabel(
            "Response preferences learn from your feedback. Files and pasted information are indexed locally for future answers. Reviewed answer pairs can be used for a separate conversation-model fine-tuning workflow. Nothing is uploaded automatically."
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        prefs = QLabel(self.core.preferences.handle("/preferences"))
        prefs.setTextFormat(Qt.PlainText)
        prefs.setWordWrap(True)
        layout.addWidget(prefs)
        reinforcement = QPushButton("Response learning and teacher answers")

        def open_reinforcement():
            from nisha.ui.reinforcement_dialog import ReinforcementDialog

            ReinforcementDialog(self.core, self.session, dialog).exec()

        reinforcement.clicked.connect(open_reinforcement)
        layout.addWidget(reinforcement)
        reset = QPushButton("Reset response preferences")
        reset.clicked.connect(
            lambda: (
                self.core.learning_command("/reset-preferences"),
                prefs.setText(self.core.preferences.handle("/preferences")),
            )
        )
        layout.addWidget(reset)
        sources = QListWidget()
        rows = self.core.knowledge.sources()
        for row in rows:
            sources.addItem(f"{row['name']} · {row['kind']} · {row['id']}")
        layout.addWidget(sources)
        forget = QPushButton("Forget selected source")

        def forget_source():
            index = sources.currentRow()
            if index >= 0:
                self.core.knowledge.forget(rows[index]["id"])
                rows.pop(index)
                sources.takeItem(index)

        forget.clicked.connect(forget_source)
        layout.addWidget(forget)
        title = QLineEdit()
        title.setPlaceholderText("Source name (optional)")
        layout.addWidget(title)
        pasted = PlainTextEdit()
        pasted.setPlaceholderText("Paste facts, notes or reference output here")
        layout.addWidget(pasted)
        files = []
        add_files = QPushButton("Select files to learn from")

        def pick_files():
            selected, _ = QFileDialog.getOpenFileNames(
                dialog,
                "Choose local knowledge",
                "",
                "Knowledge (*.txt *.md *.csv *.json *.jsonl *.docx *.pdf)",
            )
            files.extend(selected)
            add_files.setText(f"{len(files)} files selected")

        add_files.clicked.connect(pick_files)
        layout.addWidget(add_files)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText("Learn locally")
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        accepted = dialog.exec() == QDialog.Accepted
        if self.listener:
            self.listener.engine.resume(follow_up=True)
        if accepted and (files or pasted.toPlainText().strip()):
            from nisha.ui.jobs import ImportJob

            job = ImportJob(
                self.core.knowledge, files, pasted.toPlainText(), title.text() or "Pasted reference"
            )
            job.done.connect(self.show_notice)
            self.track_job(job)

    def setup_worker(self):
        if self.busy() or self.closing:
            return
        if self.listener:
            self.listener.engine.pause()
        dialog = QDialog(self)
        dialog.setWindowTitle("Connect an optional task model")
        layout = QVBoxLayout(dialog)
        note = QLabel(
            "Your base assistant stays local. API credentials are saved in Windows Credential Manager. Each external task requires a separate review and approval."
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        provider = QComboBox()
        provider.addItems(["OpenAI", "Gemini", "Claude"])
        model, key = QLineEdit(), QLineEdit()
        model.setPlaceholderText("API model name available to your account")
        key.setEchoMode(QLineEdit.Password)
        previous = self.core.workers.settings()
        provider.setCurrentText(previous.get("provider", "OpenAI"))
        model.setText(previous.get("model", ""))
        form = QFormLayout()
        for label, field in [("Provider", provider), ("API model", model), ("API key", key)]:
            form.addRow(label, field)
        layout.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        try:
            if dialog.exec() == QDialog.Accepted:
                try:
                    self.core.workers.configure(
                        provider.currentText(), model.text().strip(), key.text()
                    )
                    self.show_notice(
                        "Task provider saved. Use Ctrl+T to review a task before sending it."
                    )
                except NishaError as exc:
                    plain_warning(self, "Task model setup", str(exc))
        finally:
            key.clear()
            if self.listener:
                self.listener.engine.resume(follow_up=True)

    def external_task_dialog(self):
        if self.busy() or self.closing:
            return
        if not self.core.settings.external_tasks_enabled:
            self.show_notice("External tasks are disabled in this local-only installation.")
            return
        settings = self.core.workers.settings()
        if not settings:
            self.setup_worker()
            settings = self.core.workers.settings()
            if not settings:
                return
        if self.listener:
            self.listener.engine.pause()
        dialog = QDialog(self)
        dialog.setWindowTitle("Approve standalone external task")
        dialog.resize(650, 450)
        layout = QVBoxLayout(dialog)
        note = QLabel(
            f"Provider: {settings['provider']} · Model: {settings['model']}\nOnly the task below is sent. Local conversations, preferences and files are not attached. The provider's retention policy still applies."
        )
        note.setWordWrap(True)
        note.setTextFormat(Qt.PlainText)
        layout.addWidget(note)
        task = PlainTextEdit()
        task.setPlaceholderText("Write the exact task you approve sending externally")
        layout.addWidget(task)
        learn = QCheckBox("Save the answer for local learning review (Ctrl+L)")
        learn.setChecked(True)
        layout.addWidget(learn)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Review exact task")
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        accepted = dialog.exec() == QDialog.Accepted
        approval = None
        if accepted:
            try:
                approval = self.core.workers.propose(
                    settings["provider"], settings["model"], task.toPlainText(), learn.isChecked()
                )
                review = QDialog(self)
                review.setWindowTitle("Confirm external task")
                review.resize(650, 400)
                review_layout = QVBoxLayout(review)
                exact = PlainTextEdit()
                exact.setPlainText(approval.text)
                exact.setReadOnly(True)
                review_layout.addWidget(
                    QLabel(f"Send this exact text to {approval.provider}/{approval.model}?")
                )
                review_layout.addWidget(exact)
                review_buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
                review_buttons.button(QDialogButtonBox.Ok).setText("Approve and run")
                review_buttons.accepted.connect(review.accept)
                review_buttons.rejected.connect(review.reject)
                review_layout.addWidget(review_buttons)
                if review.exec() != QDialog.Accepted:
                    self.core.workers.cancel(approval.token)
                    approval = None
            except NishaError as exc:
                plain_warning(self, "External task", str(exc))
        if self.listener:
            self.listener.engine.resume(follow_up=True)
        if approval:
            from nisha.ui.jobs import ExternalTaskJob

            job = ExternalTaskJob(self.core, approval)
            session = self.session
            job.done.connect(
                lambda result, session=session, approval=approval: self.external_result(
                    result, session, approval
                )
            )
            job.failed.connect(self.show_notice)
            self.track_job(job)

    def external_result(self, result, session, approval):
        user = f"Approved standalone task to {approval.provider}/{approval.model}: {approval.text}"
        reply = "External model result (reference output, not verified fact):\n" + result
        self.core.store.exchange(session, user, reply, cloud_allowed=False)
        if session == self.session:
            self.current_user, self.current_reply = user, reply
            self.render()

    def voice_samples(self):
        if self.busy() or self.closing:
            return
        from nisha.ui.voice_dialog import VoiceDialog

        if self.listener:
            self.listener.engine.pause()
        try:
            VoiceDialog(self).exec()
        except (NishaError, OSError) as exc:
            self.show_notice(str(exc))
        finally:
            if self.listener:
                self.listener.engine.resume()

    def setup_gmail(self):
        if self.busy() or self.closing:
            return
        if self.listener:
            self.listener.engine.pause()
        dialog = QDialog(self)
        dialog.setWindowTitle("Connect Gmail to NISHA")
        dialog.resize(540, 260)
        layout = QVBoxLayout(dialog)
        note = QLabel(
            "Enter your Gmail address and a Google app password, not your usual Google password. The app password stays in Windows Credential Manager."
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        form = QFormLayout()
        address, password = QLineEdit(), QLineEdit()
        password.setEchoMode(QLineEdit.Password)
        form.addRow("Gmail address", address)
        form.addRow("16-character app password", password)
        layout.addLayout(form)
        help_link = QLabel(
            '<a href="https://myaccount.google.com/apppasswords">Create a Google app password</a> (requires 2-Step Verification)'
        )
        help_link.setOpenExternalLinks(True)
        layout.addWidget(help_link)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        try:
            if dialog.exec() == QDialog.Accepted:
                try:
                    self.core.workflows.mailer.configure(address.text(), password.text())
                    self.core.workflows.inboxes.clear()
                    self.core.workflows.selected_messages.clear()
                    self.show_notice(
                        "Gmail setup saved locally. Sending still requires approval of a specific email draft."
                    )
                except NishaError as exc:
                    plain_warning(self, "Gmail setup", str(exc))
        finally:
            password.clear()
            if self.listener:
                self.listener.engine.resume(follow_up=True)

    def review_email(self):
        if self.busy() or self.closing:
            return
        pending = self.core.store.pending_email(self.session)
        if not pending:
            return
        import json

        try:
            path = self.core.workflows.workspace / f"email-{pending['token']}.json"
            draft = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            plain_warning(
                self, "Email review", "The draft is missing or unreadable. Ask for a new draft."
            )
            return
        if self.listener:
            self.listener.engine.pause()
        dialog = QDialog(self)
        dialog.setWindowTitle("Review email before sending through Gmail")
        dialog.resize(700, 520)
        layout = QVBoxLayout(dialog)
        header = QLabel(
            f"To: {draft.get('recipient') or 'recipient missing'}\nSubject: {draft['subject']}"
        )
        header.setTextFormat(Qt.PlainText)
        header.setWordWrap(True)
        layout.addWidget(header)
        body = PlainTextEdit()
        body.setPlainText(draft["body"])
        body.setReadOnly(True)
        layout.addWidget(body)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Approve and send")
        buttons.button(QDialogButtonBox.Ok).setEnabled(bool(draft.get("recipient")))
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        accepted = dialog.exec() == QDialog.Accepted
        if self.listener:
            self.listener.engine.resume(follow_up=True)
        if accepted:
            self.start_turn("approve email " + pending["token"])


def run_desktop(core, background=False, quit_running=False):
    from nisha.ui.resident import DesktopInstance

    app = QApplication.instance() or QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    instance = DesktopInstance(core.settings.data_dir, app)
    if quit_running:
        if not instance.notify("quit"):
            logging.getLogger("nisha").info("No running desktop to stop.")
        return 0
    if not instance.acquire():
        if not instance.notify("ping" if background else "show"):
            raise NishaError("NISHA is already starting. Wait a few seconds and try its tray icon.")
        return 0
    if not background:
        from nisha.process_lifetime import attach_child_lifetime

        attach_child_lifetime()
    window = NishaWindow(core, on_demand=not background)
    instance.window = window
    window.exit_on_close = True
    try:
        window.login_startup.initialize()
        window.startup_action.setChecked(window.login_startup.enabled())
    except NishaError:
        logging.getLogger("nisha").warning("Windows login startup unavailable; use the launcher.")
    if background and QSystemTrayIcon.isSystemTrayAvailable():
        window.hide_to_background()
    else:
        window.bring_forward()
    try:
        return app.exec()
    finally:
        instance.close()

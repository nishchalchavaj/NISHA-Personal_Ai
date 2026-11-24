"""Functional command-center layout for NISHA's existing local features."""

from datetime import datetime
from math import cos, radians, sin
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from nisha.ui.orb_gif_widget import OrbGifWidget

TEAL = "#2DE1C2"
DIM_TEAL = "#5FC9B8"
NISHA_TEAL = QColor(45, 225, 194)

# Orb is constructed with a single `size` value on purpose -> guarantees a
# perfect square widget, which is what keeps the gif rendering as a circle
# instead of an oval. Bumped up so the orb reads as "big" on a wall display.
ORB_SIZE = 420


class FrontPageBar(QFrame):
    """Vertical command-center rail whose entries navigate to real NISHA features."""

    requested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("frontPageBar")
        self.setFixedWidth(174)
        self.setStyleSheet(
            "QFrame#frontPageBar {background:rgba(3,11,23,242); border:1px solid rgba(45,190,218,105); border-radius:14px;} "
            "QLabel {background:transparent; border:none;} "
            "QToolButton {color:#A8C9D4; text-align:left; background:transparent; border:1px solid transparent; border-radius:8px; padding:9px 10px; font:12px 'Segoe UI';} "
            "QToolButton:hover {color:#E6FCFF; background:rgba(34,160,195,35); border-color:rgba(45,190,218,55);} "
            "QToolButton:checked {color:#8CF5FF; background:rgba(24,162,194,48); border:1px solid rgba(45,210,230,120);}"
        )
        self.layout_bar = QVBoxLayout(self)
        self.layout_bar.setContentsMargins(9, 12, 9, 10)
        self.layout_bar.setSpacing(3)
        logo = QLabel("◉  NISHA\n     COMMAND CENTER", self)
        logo.setFixedHeight(48)
        logo.setStyleSheet("color:#63E8F5; font:700 12px 'Segoe UI'; letter-spacing:1px; padding:3px 6px 8px;")
        logo.setAccessibleName("NISHA command center")
        self.layout_bar.addWidget(logo)
        divider = QFrame(self)
        divider.setFixedHeight(1)
        divider.setStyleSheet("background:rgba(45,190,218,80); border:none;")
        self.layout_bar.addWidget(divider)
        self.buttons = {}
        for key, label, hint in (
            ("overview", "⌂  Command center", "Show live NISHA status and configured local services"),
            ("conversation", "▤  Conversations", "Show the current conversation and recent turns"),
            ("tasks", "▣  Tasks", "Filter the feed to queued and completed actions"),
            ("learning", "◈  Memory", "Review local memories, knowledge and preferences"),
            ("tools", "⌘  Tools", "Inspect registered tools and their approval levels"),
            ("devices", "◇  Devices", "Configure connected devices, projects and routines"),
            ("media", "▧  Media", "Choose a local image or video to show"),
            ("voice", "◉  Voice", "Open voice samples and microphone settings"),
            ("email", "✉  Email", "Review a draft or configure Gmail"),
        ):
            button = QToolButton(self)
            button.setText(label)
            button.setToolTip(hint)
            button.setAccessibleName(label)
            button.setToolButtonStyle(Qt.ToolButtonTextOnly)
            button.setCheckable(True)
            button.setAutoExclusive(True)
            button.clicked.connect(lambda checked=False, key=key: self.requested.emit(key))
            self.layout_bar.addWidget(button)
            self.buttons[key] = button
        self.layout_bar.addStretch(1)
        self.buttons["new"] = QToolButton(self)
        self.buttons["new"].setText("＋  New chat")
        self.buttons["new"].setToolTip("Start a new conversation")
        self.buttons["new"].setAccessibleName("New conversation")
        self.buttons["new"].clicked.connect(lambda: self.requested.emit("new"))
        self.layout_bar.addWidget(self.buttons["new"])
        self.buttons["mute"] = QToolButton(self)
        self.buttons["mute"].setText("◉  Microphone")
        self.buttons["mute"].setToolTip("Mute or unmute microphone input")
        self.buttons["mute"].setAccessibleName("Microphone")
        self.buttons["mute"].setCheckable(True)
        self.buttons["mute"].clicked.connect(lambda: self.requested.emit("mute"))
        self.layout_bar.addWidget(self.buttons["mute"])
        self.buttons["settings"] = QToolButton(self)
        self.buttons["settings"].setText("⚙  Settings")
        self.buttons["settings"].setToolTip("Open NISHA settings and navigation")
        self.buttons["settings"].setAccessibleName("Settings")
        self.buttons["settings"].setToolButtonStyle(Qt.ToolButtonTextOnly)
        self.buttons["settings"].setPopupMode(QToolButton.InstantPopup)
        from PySide6.QtWidgets import QMenu

        self.settings_menu = QMenu(self.buttons["settings"])
        self.buttons["settings"].setMenu(self.settings_menu)
        self.layout_bar.addWidget(self.buttons["settings"])


class DashboardPanel(QFrame):
    """Consistent compact card with a real-data body and optional live badge."""

    def __init__(self, title, parent=None, badge="", accent="#57CFE1"):
        super().__init__(parent)
        self.setObjectName("dashboardPanel")
        self.setStyleSheet(
            "QFrame#dashboardPanel {background:rgba(7,20,36,226); border:1px solid rgba(74,137,175,85); border-radius:12px;} "
            "QLabel {background:transparent; border:none;}"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(7)
        header = QHBoxLayout()
        marker = QLabel("●", self)
        marker.setStyleSheet(f"color:{accent}; font:8px 'Segoe UI'; background:transparent; border:none;")
        header.addWidget(marker)
        self.heading = QLabel(title, self)
        self.heading.setStyleSheet(f"color:{accent}; font:700 10px 'Segoe UI'; letter-spacing:1px;")
        header.addWidget(self.heading, 1)
        self.badge = QLabel(badge, self)
        self.badge.setStyleSheet(f"color:{accent}; font:700 8px 'Segoe UI'; letter-spacing:1px;")
        self.badge.setVisible(bool(badge))
        header.addWidget(self.badge)
        layout.addLayout(header)
        self.body = QLabel("", self)
        self.body.setTextFormat(Qt.PlainText)
        self.body.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.body.setWordWrap(True)
        self.body.setStyleSheet("color:#B8D1DE; font:11px 'Segoe UI';")
        layout.addWidget(self.body, 1)


class OrbitCanvas(QWidget):
    """Transparent layer for the live core's animated shortcut buttons."""

    phase_changed = Signal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_NoSystemBackground)
        self.phase = 0.0
        self.state = "default"
        self.timer = QTimer(self)
        self.timer.setInterval(33)
        self.timer.timeout.connect(self._advance)

    def _advance(self):
        speed = 3.3 if self.state == "Listening" else 1.35 if self.state == "Thinking" else 2.0
        self.phase = (self.phase + speed) % 360
        self.update()
        self.phase_changed.emit(self.phase)

    def set_state(self, state):
        self.state = state

    def showEvent(self, event):
        super().showEvent(event)
        if not self.timer.isActive():
            self.timer.start()

    def hideEvent(self, event):
        self.timer.stop()
        super().hideEvent(event)

    def paintEvent(self, event):
        # Keep this transparent overlay only to position the orbit shortcuts.
        # The animated rings obscured the NISHA core and are intentionally gone.
        event.accept()


class ActivityFeed(QFrame):
    """Visible, scroll-following feed backed only by actual NISHA turns and actions."""

    cancel_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("activityFeed")
        self.setStyleSheet(
            "QFrame#activityFeed {background:rgba(5,17,31,242); border:1px solid rgba(74,137,175,100); border-radius:12px;} "
            "QLabel {color:#8FC5D8; background:transparent; border:none;} "
            "QComboBox {color:#BCE7EF; background:#0A1C30; border:1px solid rgba(74,137,175,90); border-radius:6px; padding:4px;}"
        )
        self.entries = []
        self.filter_mode = "all"
        self.search_text = ""
        self.refresh_timer = QTimer(self)
        self.refresh_timer.setSingleShot(True)
        self.refresh_timer.setInterval(90)
        self.refresh_timer.timeout.connect(self._refresh)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        header = QHBoxLayout()
        title = QLabel("LIVE INTELLIGENCE FEED", self)
        title.setStyleSheet("font:700 10px 'Segoe UI'; letter-spacing:1px;")
        header.addWidget(title, 1)
        live = QLabel("● LIVE", self)
        live.setStyleSheet("color:#43DBB7; font:700 8px 'Segoe UI'; letter-spacing:1px;")
        header.addWidget(live)
        layout.addLayout(header)
        controls = QHBoxLayout()
        controls.setSpacing(6)
        self.cancel_button = QPushButton("Cancel", self)
        self.cancel_button.setEnabled(False)
        self.cancel_button.setToolTip("Cancel queued Sandbox and desktop tasks")
        self.cancel_button.clicked.connect(self.cancel_requested.emit)
        controls.addWidget(self.cancel_button)
        self.filter = QComboBox(self)
        self.filter.addItem("All activity", "all")
        self.filter.addItem("Tasks", "tasks")
        self.filter.addItem("Conversation", "conversation")
        self.filter.currentIndexChanged.connect(self._filter_changed)
        controls.addWidget(self.filter, 1)
        layout.addLayout(controls)
        self.output = QPlainTextEdit(self)
        self.output.setReadOnly(True)
        self.output.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        self.output.setPlaceholderText("NISHA turns and action receipts will appear here.")
        self.output.setStyleSheet(
            "QPlainTextEdit {color:#C8E9EF; background:rgba(5,17,31,245); border:1px solid rgba(45,160,195,60); border-radius:9px; padding:8px; font:12px 'Segoe UI';} "
            "QScrollBar:vertical {background:transparent; width:8px;} QScrollBar::handle:vertical {background:rgba(80,185,205,135); border-radius:4px; min-height:24px;}"
        )
        layout.addWidget(self.output, 1)

    def _filter_changed(self, index):
        self.filter_mode = self.filter.itemData(index)
        self._schedule_refresh()

    def set_filter(self, mode):
        index = self.filter.findData(mode)
        if index >= 0:
            self.filter.setCurrentIndex(index)

    def set_search(self, text):
        self.search_text = text.strip().casefold()
        self._schedule_refresh()

    def set_turn(self, user, reply, key):
        if not user and not reply:
            return
        if self.entries and self.entries[-1].get("key") == key and self.entries[-1]["kind"] == "turn":
            self.entries[-1].update(user=user, reply=reply)
        else:
            self.entries.append({"kind": "turn", "key": key, "user": user, "reply": reply, "stamp": self._stamp()})
        self._limit_and_refresh()

    def set_task(self, command, status, detail=""):
        entry = next(
            (row for row in reversed(self.entries) if row["kind"] == "task" and row["command"] == command),
            None,
        )
        if entry is None:
            entry = {
                "kind": "task", "command": command, "status": status,
                "detail": detail, "stamp": self._stamp(),
            }
            self.entries.append(entry)
        else:
            entry.update(status=status, detail=detail, stamp=self._stamp())
        self._limit_and_refresh()

    def add_event(self, title, detail):
        self.entries.append({"kind": "event", "title": title, "detail": detail, "stamp": self._stamp()})
        self._limit_and_refresh()

    def clear(self):
        self.entries.clear()
        self._schedule_refresh()

    def _limit_and_refresh(self):
        del self.entries[:-60]
        self.cancel_button.setEnabled(
            any(
                row["kind"] == "task" and row["status"] in {"QUEUED", "RUNNING", "STOPPING"}
                for row in self.entries
            )
        )
        self._schedule_refresh()

    def _schedule_refresh(self):
        if not self.refresh_timer.isActive():
            self.refresh_timer.start()

    @staticmethod
    def _stamp():
        return datetime.now().astimezone().strftime("%H:%M")

    def _refresh(self):
        visible = [
            row for row in self.entries
            if self.filter_mode == "all"
            or self.filter_mode == "tasks" and row["kind"] in {"task", "event"}
            or self.filter_mode == "conversation" and row["kind"] == "turn"
        ]
        if self.search_text:
            visible = [
                row for row in visible
                if self.search_text in " ".join(
                    str(value) for key, value in row.items() if key != "stamp"
                ).casefold()
            ]
        blocks = []
        for row in visible:
            stamp = row["stamp"]
            if row["kind"] == "turn":
                block = f"[{stamp}] YOU\n{row['user']}\n\n[{stamp}] NISHA\n{row['reply'] or 'Working…'}"
            elif row["kind"] == "task":
                block = f"[{stamp}] TASK · {row['status']}\n{row['command']}"
                if row.get("detail"):
                    block += f"\n{row['detail']}"
            else:
                block = f"[{stamp}] {row['title']}\n{row['detail']}"
            blocks.append(block)
        self.output.setPlainText("\n\n────────────────────\n\n".join(blocks))
        self.output.verticalScrollBar().setValue(self.output.verticalScrollBar().maximum())


class MicIndicator(QWidget):
    """A hand-drawn mic icon (not an emoji) so it obeys our teal color and glows properly."""

    clicked = Signal()

    def __init__(self, size=52, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_NoSystemBackground)
        self.listening = False
        self.muted = False
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("Always listening for NISHA · click to mute (Ctrl+Space)")

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self.isEnabled():
            self.clicked.emit()
        super().mousePressEvent(event)

    def set_listening(self, is_listening: bool):
        self.listening = is_listening
        self.update()

    def set_muted(self, muted):
        self.muted = muted
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        cx, cy = w / 2, h / 2

        glow_alpha = 200 if self.listening else 70
        line_alpha = 255 if self.listening else 150

        # outer glowing ring
        pen = QPen(QColor(NISHA_TEAL.red(), NISHA_TEAL.green(), NISHA_TEAL.blue(), glow_alpha))
        pen.setWidth(2)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        ring_r = min(w, h) / 2 - 2
        painter.drawEllipse(QRectF(cx - ring_r, cy - ring_r, ring_r * 2, ring_r * 2))

        # mic body (rounded capsule)
        body_color = QColor(NISHA_TEAL.red(), NISHA_TEAL.green(), NISHA_TEAL.blue(), line_alpha)
        painter.setBrush(body_color)
        painter.setPen(Qt.NoPen)
        body_w, body_h = w * 0.22, h * 0.34
        painter.drawRoundedRect(
            QRectF(cx - body_w / 2, cy - body_h / 2 - h * 0.06, body_w, body_h),
            body_w / 2,
            body_w / 2,
        )

        # mic stand (arc + stem + base line)
        pen2 = QPen(body_color)
        pen2.setWidth(2)
        painter.setPen(pen2)
        painter.setBrush(Qt.NoBrush)
        arc_r = w * 0.20
        painter.drawArc(
            int(cx - arc_r),
            int(cy - arc_r * 0.4),
            int(arc_r * 2),
            int(arc_r * 1.6),
            200 * 16,
            140 * 16,
        )
        painter.drawLine(QPointF(cx, cy + h * 0.20), QPointF(cx, cy + h * 0.30))
        painter.drawLine(
            QPointF(cx - w * 0.10, cy + h * 0.30), QPointF(cx + w * 0.10, cy + h * 0.30)
        )
        if self.muted:
            painter.setPen(QPen(QColor("#ED7777"), 3))
            painter.drawLine(QPointF(w * 0.2, h * 0.8), QPointF(w * 0.8, h * 0.2))


class WallDashboard(QWidget):
    command_requested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TranslucentBackground, False)
        self.setAttribute(Qt.WA_NoSystemBackground, False)
        self.setStyleSheet("background: rgba(3, 9, 19, 18);")

        # ---------------- Orb + title overlaid at its center ----------------
        # Single `size` argument keeps it perfectly square -> a circle, not an oval.
        self.orb = OrbGifWidget(size=ORB_SIZE, parent=self)

        self.title_label = QLabel("NISHA", self)
        self.title_label.setAlignment(Qt.AlignCenter)
        self.title_label.setFont(QFont("Segoe UI", 30, QFont.Light))
        self.title_label.setStyleSheet(
            f"color: {TEAL}; letter-spacing: 6px; background: transparent;"
        )

        # ---------------- Time / date, directly above the orb ----------------
        self.time_label = QLabel("00:00:00", self)
        self.time_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.time_label.setFont(QFont("Segoe UI", 40, QFont.Light))
        self.time_label.setStyleSheet(f"color: {TEAL}; background: transparent;")

        self.date_label = QLabel("", self)
        self.date_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.date_label.setFont(QFont("Segoe UI", 15))
        self.date_label.setStyleSheet(f"color: {DIM_TEAL}; background: transparent;")

        self.clock_timer = QTimer(self)
        self.clock_timer.timeout.connect(self._update_clock)
        self.clock_timer.start(1000)
        self._update_clock()

        # ---------------- Mic status icon, right below the orb ----------------
        self.mic_label = MicIndicator(size=52, parent=self)
        self.chat_open = False
        self.chat_button = QPushButton(self)
        self.chat_button.setFixedSize(36, 36)
        self.chat_button.setCheckable(True)
        self.chat_button.setAccessibleName("Show conversation")
        self.chat_button.setToolTip("Show conversation · Ctrl+J")
        self.chat_button.setCursor(Qt.PointingHandCursor)
        self.chat_button.setStyleSheet(
            "QPushButton {background:transparent; border:1px solid rgba(45,225,194,90); border-radius:10px;} QPushButton:hover, QPushButton:checked {background:rgba(45,225,194,30);}"
        )
        icon = QPixmap(24, 24)
        icon.fill(Qt.transparent)
        painter = QPainter(icon)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QPen(NISHA_TEAL, 1.6))
        painter.drawRoundedRect(QRectF(3, 3, 18, 14), 4, 4)
        painter.drawLine(QPointF(8, 17), QPointF(5, 21))
        painter.drawLine(QPointF(5, 21), QPointF(12, 17))
        painter.setPen(QPen(NISHA_TEAL, 2.5, Qt.SolidLine, Qt.RoundCap))
        for x in (8, 12, 16):
            painter.drawPoint(QPointF(x, 10))
        painter.end()
        self.chat_button.setIcon(QIcon(icon))
        self.chat_button.setIconSize(QSize(24, 24))

        # ---------------- Conversation bar ("You: ... / NISHA: ..."), below the mic ----------------
        self.conversation_label = QLabel("", self)
        self.conversation_label.setAlignment(Qt.AlignCenter)
        self.conversation_label.setFont(QFont("Segoe UI", 13))
        self.conversation_label.setWordWrap(True)
        self.conversation_label.setTextFormat(Qt.PlainText)
        self.conversation_label.setStyleSheet(f"""
            color: {TEAL};
            background: rgba(4, 14, 26, 210);
            border: 1px solid rgba(45, 180, 210, 85);
            border-radius: 9px;
            padding: 7px 10px;
        """)

        # ---------------- Typed-question bar (optional), below the conversation bar ----------------
        self.input_bar = QLineEdit(self)
        self.input_bar.setPlaceholderText("Type a question...")
        self.input_bar.setFont(QFont("Segoe UI", 12))
        self.input_bar.setFixedHeight(42)
        self.input_bar.setStyleSheet(f"""
            QLineEdit {{
                color: {TEAL};
                background: rgba(3, 12, 23, 235);
                border: 1px solid rgba(45, 190, 218, 140);
                border-radius: 8px;
                padding: 4px 12px;
            }}
        """)

        # ---------------- Live status cards ----------------
        # These cards display configured services and current queue state.
        self.hero_card = QFrame(self)
        self.hero_card.setObjectName("heroCard")
        self.hero_card.setStyleSheet(
            "QFrame#heroCard {background:qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 rgba(8,29,51,238),stop:0.55 rgba(5,17,32,248),stop:1 rgba(8,34,53,235)); border:1px solid rgba(60,165,197,110); border-radius:14px;}"
        )
        self.orbit_canvas = OrbitCanvas(self.hero_card)
        self.orbit_canvas.lower()
        self.compact_mode = False
        self.latest_conversation = ("", "")
        for widget in (self.orb, self.title_label, self.conversation_label):
            widget.setParent(self.hero_card)
        self.title_label.setFont(QFont("Segoe UI", 25, QFont.Light))
        self.title_label.setText("N I S H A")
        self.title_label.setStyleSheet(f"color:{TEAL}; letter-spacing:4px; background:transparent;")
        self.hero_subtitle = QLabel("PERSONAL AI CORE  ·  LOCAL FIRST", self.hero_card)
        self.hero_subtitle.setAlignment(Qt.AlignCenter)
        self.hero_subtitle.setStyleSheet("color:#77B7C8; font:700 9px 'Segoe UI'; letter-spacing:2px; background:transparent;")
        self.devices_card, self.devices_label = self._make_status_card("DEVICES & PROJECTS")
        self.models_card, self.models_label = self._make_status_card("MODEL PROFILES")
        self.knowledge_card, self.knowledge_label = self._make_status_card("MEMORY INSIGHTS")
        self.tasks_card, self.tasks_label = self._make_status_card("TASK QUEUE")
        self.core_card, self.core_label = self._make_status_card("AI CORE OVERVIEW", "READY")
        self.system_card, self.system_label = self._make_status_card("SYSTEM MONITOR", "LOCAL")
        self.system_metrics = {}
        self._build_system_metrics()
        self.email_button = QPushButton("Review email", self)
        self.email_button.setStyleSheet(
            "color: #2DE1C2; background: transparent; border: 1px solid #5FC9B8; border-radius: 6px;"
        )
        self.email_button.hide()
        self.nav_bar = FrontPageBar(self)
        self.activity_feed = ActivityFeed(self)
        self.orbit_buttons = []
        for destination, label, description, accent in (
            ("tasks", "▤", "Open task activity", "#F3BD61"),
            ("learning", "◈", "Open memory and learning", "#AE91FF"),
            ("mute", "◉", "Mute or unmute voice input", "#47E0D2"),
        ):
            button = QToolButton(self.hero_card)
            button.setText(label)
            button.setAccessibleName(description)
            button.setToolTip(description)
            button.setFixedSize(32, 32)
            button.setCursor(Qt.PointingHandCursor)
            button.setStyleSheet(
                f"QToolButton {{color:{accent}; background:rgba(7,22,39,230); border:1px solid {accent}; border-radius:16px; font:700 13px 'Segoe UI';}} "
                f"QToolButton:hover {{background:{accent}; color:#06111D;}}"
            )
            button.clicked.connect(lambda _checked=False, target=destination: self.nav_bar.requested.emit(target))
            self.orbit_buttons.append(button)
        self.orbit_canvas.phase_changed.connect(self.position_orbit_buttons)
        self.header = QFrame(self)
        self.header.setObjectName("dashboardHeader")
        self.header.setStyleSheet(
            "QFrame#dashboardHeader {background:rgba(6,18,32,232); border:1px solid rgba(74,137,175,75); border-radius:11px;} "
            "QLabel {background:transparent; border:none;}"
        )
        self.header_status = QLabel("●  STARTING", self.header)
        self.header_status.setStyleSheet("color:#45E2CD; font:700 10px 'Segoe UI'; letter-spacing:1px;")
        self.time_label.setParent(self.header)
        self.date_label.setParent(self.header)
        self.time_label.setAlignment(Qt.AlignCenter)
        self.time_label.setFont(QFont("Segoe UI", 17, QFont.DemiBold))
        self.time_label.setStyleSheet("color:#5DE7F0; background:transparent;")
        self.date_label.setAlignment(Qt.AlignCenter)
        self.date_label.setFont(QFont("Segoe UI", 9))
        self.date_label.setStyleSheet("color:#8AAFC0; background:transparent;")
        self.search_input = QLineEdit(self.header)
        self.search_input.setPlaceholderText("Search recent conversations and activity…")
        self.search_input.setClearButtonEnabled(True)
        self.search_input.setAccessibleName("Search recent NISHA activity")
        self.search_input.setStyleSheet(
            "QLineEdit {color:#D4EAF0; background:#0A1C30; border:1px solid rgba(74,137,175,90); border-radius:8px; padding:7px 10px; font:11px 'Segoe UI';} "
            "QLineEdit:focus {border-color:#32C7DB;}"
        )
        self.search_input.textChanged.connect(self.activity_feed.set_search)

        self.quick_card = QFrame(self)
        self.quick_card.setObjectName("quickCommands")
        self.quick_card.setStyleSheet(
            "QFrame#quickCommands {background:rgba(7,20,36,226); border:1px solid rgba(74,137,175,85); border-radius:12px;} "
            "QLabel {background:transparent; border:none;} "
            "QToolButton {color:#B9D9E5; text-align:left; background:#0B2035; border:1px solid rgba(74,137,175,70); border-radius:7px; padding:7px 8px; font:10px 'Segoe UI';} "
            "QToolButton:hover {color:#E6FCFF; border-color:#36C7D9; background:#103047;}"
        )
        quick_layout = QVBoxLayout(self.quick_card)
        quick_layout.setContentsMargins(12, 10, 12, 10)
        quick_layout.setSpacing(7)
        quick_header = QHBoxLayout()
        quick_title = QLabel("QUICK ACTIONS", self.quick_card)
        quick_title.setStyleSheet("color:#8FC5D8; font:700 10px 'Segoe UI'; letter-spacing:1px;")
        quick_header.addWidget(quick_title, 1)
        quick_hint = QLabel("ONE CLICK", self.quick_card)
        quick_hint.setStyleSheet("color:#567D92; font:700 8px 'Segoe UI';")
        quick_header.addWidget(quick_hint)
        quick_layout.addLayout(quick_header)
        quick_grid = QGridLayout()
        quick_grid.setHorizontalSpacing(6)
        quick_grid.setVerticalSpacing(6)
        self.quick_buttons = {}
        for index, (label, command) in enumerate((
            ("＋  New chat", "/new"),
            ("▤  Windows", "show open windows"),
            ("⌕  Apps", "list installed apps"),
            ("◇  Devices", "what's the status of the devices?"),
        )):
            button = QToolButton(self.quick_card)
            button.setText(label)
            button.setToolTip(f"Run: {command}")
            button.setAccessibleName(f"Run {command}")
            accents = ("#48D9E5", "#6EAFFF", "#B08CFF", "#4AD7A4")
            accent = accents[index]
            button.setStyleSheet(
                f"QToolButton {{color:{accent}; text-align:left; background:#0B2035; border:1px solid {accent}; border-radius:7px; padding:7px 8px; font:10px 'Segoe UI';}} "
                f"QToolButton:hover {{color:#06131F; background:{accent};}}"
            )
            button.clicked.connect(lambda _checked=False, value=command: self.command_requested.emit(value))
            quick_grid.addWidget(button, index // 2, index % 2)
            self.quick_buttons[command] = button
        quick_layout.addLayout(quick_grid, 1)

        self.voice_dock = QFrame(self)
        self.voice_dock.setObjectName("voiceDock")
        self.voice_dock.setStyleSheet(
            "QFrame#voiceDock {background:rgba(5,18,33,248); border:1px solid rgba(58,167,195,125); border-radius:14px;} "
            "QLabel {background:transparent; border:none;}"
        )
        self.input_bar.setParent(self.voice_dock)
        self.input_bar.setPlaceholderText("Ask NISHA or enter a desktop command…")
        self.input_bar.setAccessibleName("Message NISHA")
        self.input_bar.setStyleSheet(
            "QLineEdit {color:#E2F6F8; background:#071522; border:1px solid rgba(74,137,175,72); border-radius:8px; padding:7px 11px; font:11px 'Segoe UI';} "
            "QLineEdit:focus {border-color:#32C7DB;}"
        )
        self.send_button = QPushButton("Send  ↗", self.voice_dock)
        self.send_button.setAccessibleName("Send message to NISHA")
        self.send_button.setStyleSheet(
            "QPushButton {color:#04131E; background:#39CAD8; border:none; border-radius:8px; padding:7px 13px; font:700 10px 'Segoe UI';} "
            "QPushButton:hover {background:#69E8EC;}"
        )
        self.dock_status = QLabel("WAKE WORD READY", self.voice_dock)
        self.dock_status.setStyleSheet("color:#58D9D4; font:700 8px 'Segoe UI'; letter-spacing:1px;")
        self.mic_label.setParent(self.voice_dock)
        self.mic_label.setFixedSize(38, 38)
        self.chat_button.setParent(self.voice_dock)
        self.chat_button.setFixedSize(34, 34)
        self.send_button.clicked.connect(self.input_bar.returnPressed.emit)
        self.clock_timer = QTimer(self)
        self.clock_timer.timeout.connect(self._update_clock)
        self.clock_timer.start(1000)
        self.system_timer = QTimer(self)
        self.system_timer.timeout.connect(self._update_system_metrics)
        self.system_timer.start(5000)
        self._update_clock()
        self._update_system_metrics()
    def _make_status_card(self, title, badge=""):
        accents = {
            "AI CORE OVERVIEW": "#51D6EE",
            "SYSTEM MONITOR": "#44DDBE",
            "MEMORY INSIGHTS": "#B197FF",
            "MODEL PROFILES": "#70AFFF",
            "DEVICES & PROJECTS": "#5AD79D",
            "TASK QUEUE": "#F0BE62",
        }
        panel = DashboardPanel(title, self, badge, accents.get(title, "#57CFE1"))
        return panel, panel.body

    def position_orbit_buttons(self, phase):
        if getattr(self, "compact_mode", False) or not self.orbit_buttons:
            return
        center_x = self.hero_card.width() / 2
        center_y = self.orb.y() + self.orb.height() / 2
        radius_x = min(self.orb.width() * 0.76, self.hero_card.width() / 2 - 20)
        radius_y = min(
            self.orb.height() * 0.72,
            max(20, min(center_y - 20, self.hero_card.height() - center_y - 20)),
        )
        for index, button in enumerate(self.orbit_buttons):
            angle = radians(phase + index * 120)
            x = int(center_x + cos(angle) * radius_x - button.width() / 2)
            y = int(center_y + sin(angle) * radius_y - button.height() / 2)
            button.move(x, y)

    def _build_system_metrics(self):
        self.system_label.hide()
        layout = self.system_card.layout()
        for key, title in (("cpu", "CPU"), ("memory", "MEMORY"), ("disk", "DISK")):
            row = QHBoxLayout()
            caption = QLabel(title, self.system_card)
            caption.setStyleSheet("color:#86AFC0; font:700 8px 'Segoe UI'; letter-spacing:1px;")
            value = QLabel("—", self.system_card)
            value.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            value.setStyleSheet("color:#51D9E5; font:700 9px 'Segoe UI';")
            row.addWidget(caption, 1)
            row.addWidget(value)
            bar = QProgressBar(self.system_card)
            bar.setRange(0, 100)
            bar.setValue(0)
            bar.setTextVisible(False)
            bar.setFixedHeight(6)
            accent = {"cpu": "#F0B84F", "memory": "#43D8E8", "disk": "#AC8BFF"}[key]
            bar.setStyleSheet(
                "QProgressBar {background:#0A1B2D; border:none; border-radius:3px;} "
                f"QProgressBar::chunk {{background:{accent}; border-radius:3px;}}"
            )
            layout.addLayout(row)
            layout.addWidget(bar)
            self.system_metrics[key] = (value, bar)

    def _update_system_metrics(self):
        try:
            import psutil
            values = {
                "cpu": psutil.cpu_percent(interval=None),
                "memory": psutil.virtual_memory().percent,
                "disk": psutil.disk_usage(Path.cwd().anchor or str(Path.cwd())).percent,
            }
            for key, amount in values.items():
                value, bar = self.system_metrics[key]
                value.setText(f"{amount:.0f}%")
                bar.setValue(int(amount))
        except (ImportError, OSError, KeyError, ValueError):
            for value, bar in self.system_metrics.values():
                value.setText("N/A")
                bar.setValue(0)

    def set_listening(self, is_listening: bool):
        self.mic_label.set_listening(is_listening)

    def set_runtime_state(self, state):
        self.header_status.setText("●  " + state.upper())
        self.orbit_canvas.set_state(state)
        dock_states = {
            "Listening": "VOICE LIVE",
            "Waiting for NISHA": "WAKE WORD READY",
            "Muted": "MICROPHONE MUTED",
            "Speaking": "NISHA SPEAKING",
            "Thinking": "PROCESSING REQUEST",
            "Transcribing": "HEARING YOUR REQUEST",
            "Working in background": "TASK RUNNING",
        }
        self.dock_status.setText(dock_states.get(state, state.upper()))
        color = "#5DE7F0" if state in {"Listening", "Speaking"} else "#E9BF6B" if state in {"Thinking", "Transcribing"} else "#7FA3B8"
        self.header_status.setStyleSheet(f"color:{color}; font:700 10px 'Segoe UI'; letter-spacing:1px;")

    def set_conversation(self, you_text: str, nisha_text: str):
        self.latest_conversation = (you_text, nisha_text)
        you_full, nisha_full = self.latest_conversation
        if self.compact_mode:
            you_text = self._shorten(you_full, 54)
            nisha_text = self._shorten(nisha_full, 118)
        self.conversation_label.setText(
            f"You: {you_text}\nNISHA: {nisha_text}" if you_text or nisha_text else ""
        )
        self.conversation_label.setToolTip(
            f"You: {you_full}\nNISHA: {nisha_full}" if you_full or nisha_full else ""
        )

    @staticmethod
    def _shorten(text, limit):
        text = " ".join(text.split())
        return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"

    def set_compact_mode(self, compact):
        self.compact_mode = bool(compact)
        email_was_visible = getattr(self, "_email_button_was_visible", False)
        if compact:
            self._email_button_was_visible = self.email_button.isVisible()
            self.email_button.hide()
        else:
            self.email_button.setVisible(email_was_visible)
        full_widgets = (
            self.nav_bar, self.header, self.core_card, self.system_card,
            self.knowledge_card, self.models_card, self.devices_card,
            self.tasks_card, self.quick_card, self.activity_feed, self.voice_dock,
        )
        for widget in full_widgets:
            widget.setVisible(not compact)
        self.hero_card.show()
        self.hero_subtitle.setVisible(not compact)
        for button in self.orbit_buttons:
            button.setVisible(not compact)
        self.set_conversation(*self.latest_conversation)
        self.layout_dashboard()

    def _update_clock(self):
        now = datetime.now().astimezone()
        self.time_label.setText(now.strftime("%I:%M:%S %p"))
        self.date_label.setText(now.strftime("%A, %d %B %Y"))

    def resizeEvent(self, event):
        self.layout_dashboard()
        super().resizeEvent(event)

    def set_chat_open(self, opened):
        self.chat_open = opened
        self.chat_button.setChecked(opened)
        self.chat_button.setToolTip(("Hide" if opened else "Show") + " conversation · Ctrl+J")
        self.layout_dashboard()
        # Repaint transparent labels at both their old and new positions.
        for widget in self.findChildren(QWidget):
            widget.update()

    def layout_dashboard(self):
        w, h = self.width(), self.height()
        if self.compact_mode:
            self.hero_card.setGeometry(0, 0, w, h)
            self.orbit_canvas.setGeometry(self.hero_card.rect())
            orb_size = min(156, max(108, min(w * 0.42, h * 0.52)))
            self.orb.setFixedSize(int(orb_size), int(orb_size))
            self.orb.move((w - orb_size) // 2, 20)
            self.title_label.setGeometry(
                (w - orb_size) // 2, int(20 + (orb_size - 34) / 2), orb_size, 34
            )
            self.conversation_label.setGeometry(14, h - 94, w - 28, 78)
            for button in self.orbit_buttons:
                button.hide()
            return

        nav_width = self.nav_bar.width()
        self.nav_bar.setGeometry(12, 12, nav_width, h - 24)

        # Top toolbar reserves space for the frameless window controls.
        header_x = nav_width + 24
        header_w = max(420, w - header_x - 148)
        self.header.setGeometry(header_x, 12, header_w, 52)
        self.header_status.setGeometry(12, 0, 190, 52)
        self.date_label.setGeometry(205, 3, 190, 16)
        self.time_label.setGeometry(205, 18, 190, 29)
        self.search_input.setGeometry(410, 8, max(180, header_w - 424), 36)

        feed_width = min(350, max(285, int(w * 0.235)))
        feed_x = w - feed_width - 14
        content_x = header_x
        left_width = min(310, max(230, int((feed_x - content_x - 30) * 0.255)))
        gap = 11
        center_x = content_x + left_width + gap
        center_w = max(360, feed_x - center_x - gap)
        content_top = 76
        dock_y = h - 70
        content_bottom = dock_y - 12
        content_height = max(250, content_bottom - content_top)
        row_gap = 10
        first_h = max(205, int((content_height - 2 * row_gap) * 0.52))
        second_h = max(128, int((content_height - 2 * row_gap) * 0.23))
        third_h = max(110, content_height - first_h - second_h - 2 * row_gap)
        y1 = content_top
        y2 = y1 + first_h + row_gap
        y3 = y2 + second_h + row_gap

        # Left rail of cards: truthful overview, local system usage and memory.
        self.core_card.setGeometry(content_x, y1, left_width, first_h)
        self.system_card.setGeometry(content_x, y2, left_width, second_h)
        self.knowledge_card.setGeometry(content_x, y3, left_width, third_h)

        # Center hero, task state, real quick commands and configured services.
        self.hero_card.setGeometry(center_x, y1, center_w, first_h)
        self.orbit_canvas.setGeometry(self.hero_card.rect())
        orb_size = min(ORB_SIZE, max(116, first_h - 112), max(116, center_w - 100))
        self.orb.setFixedSize(orb_size, orb_size)
        orb_x = (center_w - orb_size) // 2
        orb_y = max(32, (first_h - orb_size - 54) // 2)
        self.orb.move(orb_x, orb_y)
        self.position_orbit_buttons(self.orbit_canvas.phase)
        self.title_label.setGeometry(orb_x, orb_y + (orb_size - 40) // 2, orb_size, 40)
        self.hero_subtitle.setGeometry(20, 12, center_w - 40, 18)
        self.conversation_label.setGeometry(20, first_h - 51, center_w - 40, 38)

        task_w = int(center_w * 0.57)
        self.tasks_card.setGeometry(center_x, y2, task_w - 5, second_h)
        self.quick_card.setGeometry(center_x + task_w + 4, y2, center_w - task_w - 4, second_h)
        half = (center_w - 10) // 2
        self.models_card.setGeometry(center_x, y3, half, third_h)
        self.devices_card.setGeometry(center_x + half + 10, y3, half, third_h)

        # The feed spans the working rows and follows the newest real event.
        self.activity_feed.setGeometry(feed_x, content_top, feed_width, content_bottom - content_top)

        # Persistent command and voice dock.
        dock_w = feed_x - content_x - gap
        self.voice_dock.setGeometry(content_x, dock_y, dock_w, 58)
        self.dock_status.setGeometry(10, 0, 116, 58)
        self.input_bar.setGeometry(122, 10, max(180, dock_w - 325), 38)
        self.send_button.setGeometry(dock_w - 194, 10, 82, 38)
        self.mic_label.move(dock_w - 101, 10)
        self.chat_button.move(dock_w - 54, 12)

"""
NISHA's wall-mode dashboard: big circular orb on the right (middle-to-bottom),
with time/date above it, title centered on it, mic status just below it, and
a conversation strip + typed-question bar under that. The left/center area is
an open canvas laid out as invisible reference zones for connected devices,
weather, CPU/server info, and a flexible content area for anything else NISHA
needs to show (images, video, text, etc).
"""

from datetime import datetime

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QLabel, QLineEdit, QPushButton, QWidget

from nisha.ui.orb_gif_widget import OrbGifWidget

TEAL = "#2DE1C2"
DIM_TEAL = "#5FC9B8"
NISHA_TEAL = QColor(45, 225, 194)

# Orb is constructed with a single `size` value on purpose -> guarantees a
# perfect square widget, which is what keeps the gif rendering as a circle
# instead of an oval. Bumped up so the orb reads as "big" on a wall display.
ORB_SIZE = 520


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
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_NoSystemBackground)
        self.setStyleSheet("background: transparent;")

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
            background: transparent;
            border-bottom: 1px solid rgba(45, 225, 194, 110);
            padding-bottom: 6px;
        """)

        # ---------------- Typed-question bar (optional), below the conversation bar ----------------
        self.input_bar = QLineEdit(self)
        self.input_bar.setPlaceholderText("Type a question...")
        self.input_bar.setFont(QFont("Segoe UI", 12))
        self.input_bar.setFixedHeight(36)
        self.input_bar.setStyleSheet(f"""
            QLineEdit {{
                color: {TEAL};
                background: transparent;
                border: 1px solid rgba(45, 225, 194, 110);
                border-radius: 8px;
                padding: 4px 12px;
            }}
        """)

        # ---------------- Left/center canvas — invisible reference areas ----------------
        # These labels are unstyled (no border, no background) on purpose: they
        # only mark where content should be drawn/placed, never visible outlines.
        self.devices_label = self._make_reference_label("Connected / Available Devices")
        self.weather_label = self._make_reference_label("Weather")
        self.system_label = self._make_reference_label("CPU / Server Info")
        self.content_label = self._make_reference_label("")
        self.email_button = QPushButton("Review email", self)
        self.email_button.setStyleSheet(
            "color: #2DE1C2; background: transparent; border: 1px solid #5FC9B8; border-radius: 6px;"
        )
        self.email_button.hide()

    def _make_reference_label(self, title):
        label = QLabel(title, self)
        label.setTextFormat(Qt.PlainText)
        label.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        label.setFont(QFont("Segoe UI", 12))
        label.setStyleSheet(f"color: {DIM_TEAL}; background: transparent; border: none;")
        label.setWordWrap(True)
        return label

    def set_listening(self, is_listening: bool):
        self.mic_label.set_listening(is_listening)

    def set_conversation(self, you_text: str, nisha_text: str):
        self.conversation_label.setText(
            f"You: {you_text}\nNISHA: {nisha_text}" if you_text or nisha_text else ""
        )
        self.conversation_label.setToolTip(self.conversation_label.text())
        self.content_label.clear()

    def _update_clock(self):
        now = datetime.now().astimezone()
        self.time_label.setText(now.strftime("%H:%M:%S"))
        self.date_label.setText(now.strftime("%A  %d/%m/%Y"))

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

        right_col_width = int(w * 0.42)
        right_x = w - right_col_width

        # Preserve the original 520px orb on a wall display, but fit smaller or
        # scaled monitors without pushing the question bar offscreen.
        orb_size = min(ORB_SIZE, max(120, h - 316), max(120, right_col_width - 30))
        self.orb.setFixedSize(orb_size, orb_size)

        # Orb is fixed-size and square (set at construction), so it stays a
        # true circle no matter how the window is resized.
        orb_w = self.orb.width()
        orb_h = self.orb.height()
        orb_x = right_x + (right_col_width - orb_w) // 2

        # ---- Vertical stack, top to bottom: time/date -> orb -> mic -> conversation -> input ----
        time_block_h = 74  # time row + date row
        time_orb_gap = 14
        orb_mic_gap = 16
        mic_h = self.mic_label.height()
        mic_conv_gap = 14
        conv_h = 60
        conv_input_gap = 10
        input_h = self.input_bar.height()

        stack_h = (
            time_block_h
            + time_orb_gap
            + orb_h
            + orb_mic_gap
            + mic_h
            + mic_conv_gap
            + conv_h
            + conv_input_gap
            + input_h
        )

        # Bias the whole stack toward the middle/bottom of the screen (rather
        # than dead-center) so the orb visually sits in the middle-to-bottom
        # of the right-hand side, per spec.
        leftover = max(h - stack_h, 0)
        top_offset = max(int(leftover * 0.55), 20)

        # Time, large, right-aligned above the orb's right edge.
        time_y = top_offset
        self.time_label.setFixedSize(orb_w, 65)
        self.time_label.move(orb_x, time_y)

        # Date, smaller, directly under the time, same right alignment.
        date_y = time_y + 65
        self.date_label.setFixedSize(orb_w, 26)
        self.date_label.move(orb_x, date_y)

        # Orb sits right below the time/date block.
        orb_y = time_y + time_block_h + time_orb_gap
        self.orb.move(orb_x, orb_y)

        # Title centered on the orb.
        title_height = 44
        self.title_label.setFixedSize(orb_w, title_height)
        self.title_label.move(orb_x, orb_y + orb_h // 2 - title_height // 2)

        # Mic icon, centered, right below the orb.
        mic_y = orb_y + orb_h + orb_mic_gap
        mic_x = right_x + (right_col_width - self.mic_label.width()) // 2
        self.mic_label.move(mic_x, mic_y)
        self.chat_button.move(mic_x + mic_h + 18, mic_y + (mic_h - self.chat_button.height()) // 2)

        # Conversation bar, right below the mic.
        conv_y = mic_y + mic_h + mic_conv_gap
        self.conversation_label.setFixedWidth(right_col_width - 30)
        self.conversation_label.setFixedHeight(conv_h)
        self.conversation_label.move(right_x + 15, conv_y)

        # Typed-question bar, right below the conversation bar.
        input_y = conv_y + conv_h + conv_input_gap
        self.input_bar.setFixedWidth(right_col_width - 30)
        self.input_bar.move(right_x + 15, input_y)

        # ---------------- Left canvas: devices (top, full width) -> weather/CPU (side by side) -> content ----------------
        left_margin = 30
        left_width = right_x - left_margin - 20

        devices_y = int(h * 0.05)
        self.devices_label.move(left_margin, devices_y)
        self.devices_label.setFixedSize(left_width, 50)

        boxes_y = devices_y + 100
        box_width = (left_width - 20) // 2
        self.weather_label.move(left_margin, boxes_y)
        self.weather_label.setFixedSize(box_width, 140)
        self.system_label.move(left_margin + box_width + 20, boxes_y)
        self.system_label.setFixedSize(box_width, 140)

        content_y = boxes_y + 160
        content_height = max(h - content_y - 30, 50)
        self.content_label.move(left_margin, content_y)
        self.content_label.setFixedSize(left_width, content_height)
        self.email_button.setGeometry(left_margin, h - 60, 130, 34)
        if self.chat_open:
            center_x = (w - orb_w) // 2
            self.orb.move(center_x, orb_y)
            self.title_label.move(center_x, orb_y + orb_h // 2 - title_height // 2)

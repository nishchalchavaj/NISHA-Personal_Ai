"""Local session conversation, with selectable two-sided bubbles in a glass window."""

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)


class MessageBubble(QFrame):
    def __init__(self, role, text):
        super().__init__()
        self.role = role
        self.width_limit = 0
        self.setObjectName("bubble")
        color = "rgba(30,122,106,205)" if role == "user" else "rgba(29,49,61,215)"
        self.setStyleSheet(f"QFrame#bubble {{background:{color}; border-radius:13px;}}")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(13, 9, 13, 11)
        layout.setSpacing(4)
        author = QLabel("You" if role == "user" else "NISHA")
        author.setStyleSheet("color:#86EDCF; font:600 11px 'Segoe UI'; background:transparent;")
        layout.addWidget(author)
        self.body = QLabel()
        self.body.setTextFormat(Qt.PlainText)
        self.body.setWordWrap(True)
        self.body.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.body.setStyleSheet("color:#EDF8F5; font:14px 'Segoe UI'; background:transparent;")
        layout.addWidget(self.body)
        self.set_text(text)

    def set_text(self, text):
        self.body.setText(text or "…")
        if self.width_limit:
            self.fit_width(self.width_limit)

    def fit_width(self, maximum):
        self.width_limit = maximum
        natural = (
            max(
                self.body.fontMetrics().horizontalAdvance(line)
                for line in self.body.text().splitlines()
            )
            + 28
        )
        self.setFixedWidth(min(maximum, max(82, natural)))


class ConversationPanel(QWidget):
    closed = Signal()

    def __init__(self, parent):
        super().__init__(parent, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setWindowTitle("NISHA Conversation")
        self.setAttribute(Qt.WA_TranslucentBackground, False)
        self.messages = []
        self.bubbles = []
        self.current_pair = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 18)
        header = QHBoxLayout()
        title = QLabel("Conversation")
        title.setStyleSheet("color:#DDFBF5; font:600 18px 'Segoe UI'; background:transparent;")
        header.addWidget(title, 1)
        close = QPushButton("×")
        close.setAccessibleName("Close conversation")
        close.setFixedSize(28, 28)
        close.setStyleSheet(
            "color:#2DE1C2; background:rgba(45,225,194,15); border:1px solid rgba(45,225,194,65); border-radius:6px;"
        )
        close.clicked.connect(self.dismiss)
        header.addWidget(close)
        layout.addLayout(header)
        caption = QLabel("You & NISHA · this conversation")
        caption.setStyleSheet("color:#8EBDB7; font:12px 'Segoe UI'; background:transparent;")
        layout.addWidget(caption)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setStyleSheet(
            "QScrollArea {background:transparent;} QScrollBar:vertical {background:transparent; width:7px;} QScrollBar::handle:vertical {background:rgba(111,193,182,120); border-radius:3px; min-height:24px;} QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {height:0;}"
        )
        self.canvas = QWidget()
        self.canvas.setStyleSheet("background:transparent;")
        self.rows = QVBoxLayout(self.canvas)
        self.rows.setContentsMargins(0, 12, 6, 4)
        self.rows.setSpacing(12)
        self.empty = QLabel("Your conversation will appear here.")
        self.empty.setWordWrap(True)
        self.empty.setStyleSheet("color:#8EBDB7; font:14px 'Segoe UI'; background:transparent;")
        self.rows.addWidget(self.empty)
        self.rows.addStretch()
        self.scroll.setWidget(self.canvas)
        layout.addWidget(self.scroll, 1)
        self.hide()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        gradient = QLinearGradient(0, 0, self.width(), self.height())
        gradient.setColorAt(0, QColor(20, 47, 52, 255))
        gradient.setColorAt(1, QColor(8, 22, 29, 255))
        painter.setBrush(gradient)
        painter.setPen(QPen(QColor(100, 235, 213, 115), 1))
        painter.drawRoundedRect(self.rect().adjusted(1, 1, -1, -1), 20, 20)

    def open(self):
        owner = self.parentWidget()
        area = owner.screen().availableGeometry()
        width = min(480, max(300, int(owner.width() * 0.30)), area.width() - 48)
        height = min(660, area.height() - 48)
        y = area.top() + (area.height() - height) // 2
        dashboard = owner.wall_widget
        if dashboard.isVisible():
            upper = (
                dashboard.date_label.mapToGlobal(dashboard.date_label.rect().bottomLeft()).y() + 18
            )
            lower = dashboard.mic_label.mapToGlobal(dashboard.mic_label.rect().topLeft()).y() - 18
            if lower - upper >= 200:
                y = max(area.top() + 16, upper)
                height = min(height, lower - y)
        self.resize(width, height)
        self.move(area.right() - width - 23, y)
        self.show()
        self.raise_()
        self._fit_bubbles()
        QTimer.singleShot(0, self._scroll_to_bottom)

    def begin_turn(self):
        self.current_pair = None

    def record_background(self, user, reply):
        current = self.current_pair
        self.current_pair = None
        self.record(user, reply)
        self.current_pair = current

    def record(self, user, reply, results=False):
        if not user and not reply:
            return
        answer = reply
        if self.current_pair is None or self.current_pair[0] != user:
            if user:
                self._append("user", user)
            self._append("assistant", answer)
            self.current_pair = (user, len(self.messages) - 1)
        else:
            index = self.current_pair[1]
            if self.messages[index]["content"] != answer:
                self.messages[index]["content"] = answer
                self.bubbles[index].set_text(answer)
        QTimer.singleShot(0, self._scroll_to_bottom)

    def _append(self, role, content):
        self.empty.hide()
        self.messages.append({"role": role, "content": content})
        bubble = MessageBubble(role, content)
        self.bubbles.append(bubble)
        row = QWidget()
        row.setStyleSheet("background:transparent;")
        line = QHBoxLayout(row)
        line.setContentsMargins(0, 0, 0, 0)
        if role == "user":
            line.addStretch()
            line.addWidget(bubble, 0, Qt.AlignRight)
        else:
            line.addWidget(bubble, 0, Qt.AlignLeft)
            line.addStretch()
        self.rows.insertWidget(self.rows.count() - 1, row)
        self._fit_bubbles()

    def _fit_bubbles(self):
        width = max(100, int((self.scroll.viewport().width() - 12) * 0.84))
        for bubble in self.bubbles:
            bubble.fit_width(width)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit_bubbles()

    def _scroll_to_bottom(self):
        bar = self.scroll.verticalScrollBar()
        bar.setValue(bar.maximum())

    def clear(self):
        self.messages.clear()
        self.bubbles.clear()
        self.current_pair = None
        while self.rows.count() > 2:
            item = self.rows.takeAt(1)
            item.widget().deleteLater()
        self.empty.show()

    def dismiss(self):
        self.hide()
        self.closed.emit()

    def closeEvent(self, event):
        event.ignore()
        self.dismiss()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and event.position().y() < 80:
            self.drag_offset = event.globalPosition().toPoint() - self.pos()

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.LeftButton and hasattr(self, "drag_offset"):
            self.move(event.globalPosition().toPoint() - self.drag_offset)

    def mouseReleaseEvent(self, event):
        if hasattr(self, "drag_offset"):
            del self.drag_offset

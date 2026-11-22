"""The original transparent wall/table shell, independent of the assistant core."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QShortcut
from PySide6.QtWidgets import QApplication, QLabel, QStackedLayout, QVBoxLayout, QWidget

from nisha.ui.wall_dashboard import WallDashboard


def get_screen_for_output(output_mode):
    primary = QApplication.primaryScreen()
    if output_mode == "projector":
        others = [screen for screen in QApplication.screens() if screen != primary]
        if others:
            return max(
                others, key=lambda screen: screen.geometry().width() * screen.geometry().height()
            )
    return primary


class DashboardWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("NISHA")
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_NoSystemBackground)
        self.setAutoFillBackground(False)
        self.stack = QStackedLayout(self)
        self.wall_widget = WallDashboard()
        self.table_widget = self._build_table_mode()
        self.stack.addWidget(self.wall_widget)
        self.stack.addWidget(self.table_widget)
        self.display_mode = "wall"
        self.output_mode = "monitor"
        self.shortcuts = []
        self.bind_shortcut("F9", self.toggle_display_mode)
        self.bind_shortcut("F10", self.toggle_output_mode)
        self._apply_layout()

    def bind_shortcut(self, key, callback):
        shortcut = QShortcut(key, self)
        shortcut.activated.connect(callback)
        self.shortcuts.append(shortcut)

    def _build_table_mode(self):
        widget = QWidget()
        widget.setAttribute(Qt.WA_TranslucentBackground)
        widget.setAttribute(Qt.WA_NoSystemBackground)
        widget.setStyleSheet("background: transparent;")
        layout = QVBoxLayout(widget)
        layout.setAlignment(Qt.AlignCenter)
        layout.setContentsMargins(18, 14, 18, 14)
        title = QLabel("NISHA")
        title.setAlignment(Qt.AlignCenter)
        title.setFont(QFont("Segoe UI", 18, QFont.Light))
        title.setStyleSheet("color: #2DE1C2; letter-spacing: 4px; background: transparent;")
        layout.addWidget(title)
        self.table_status = QLabel("● Ready")
        self.table_status.setTextFormat(Qt.PlainText)
        self.table_status.setAlignment(Qt.AlignCenter)
        self.table_status.setFont(QFont("Segoe UI", 10))
        self.table_status.setStyleSheet("color: #5FC9B8; margin-top: 6px; background: transparent;")
        layout.addWidget(self.table_status)
        return widget

    def _apply_layout(self):
        screen = get_screen_for_output(self.output_mode)
        geo = screen.geometry()
        fraction = 0.95 if self.display_mode == "wall" else 0.35
        width, height = int(geo.width() * fraction), int(geo.height() * fraction)
        if self.display_mode == "wall":
            x = geo.x() + (geo.width() - width) // 2
            y = geo.y() + (geo.height() - height) // 2
        else:
            x = geo.x() + geo.width() - width - 24
            y = geo.y() + geo.height() - height - 24
        self.stack.setCurrentWidget(
            self.wall_widget if self.display_mode == "wall" else self.table_widget
        )
        self.resize(width, height)
        self.move(x, y)
        if self.windowHandle():
            self.windowHandle().setScreen(screen)

    def toggle_display_mode(self):
        self.display_mode = "table" if self.display_mode == "wall" else "wall"
        self._apply_layout()

    def toggle_output_mode(self):
        self.output_mode = "projector" if self.output_mode == "monitor" else "monitor"
        self._apply_layout()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.pos()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.LeftButton and hasattr(self, "_drag_pos"):
            self.move(event.globalPosition().toPoint() - self._drag_pos)
        super().mouseMoveEvent(event)

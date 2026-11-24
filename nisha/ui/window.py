"""Opaque NISHA wall/table shell with a full-window technical HUD backdrop."""

from math import cos, radians, sin

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPen, QRadialGradient, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QStackedLayout,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from nisha.ui.wall_dashboard import WallDashboard


def get_screen_for_output(output_mode):
    primary = QApplication.primaryScreen()
    if output_mode == "projector":
        others = [screen for screen in QApplication.screens() if screen != primary]
        if others:
            return max(
                others, key=lambda screen: screen.geometry().width() * screen.geometry().height()
            )
    return center_monitor(QApplication.screens()) or primary


def center_monitor(screens):
    """Choose the monitor nearest the center of the combined extended desktop."""
    screens = list(screens)
    if not screens:
        return None
    rectangles = [screen.geometry() for screen in screens]
    left = min(rect.x() for rect in rectangles)
    top = min(rect.y() for rect in rectangles)
    right = max(rect.x() + rect.width() for rect in rectangles)
    bottom = max(rect.y() + rect.height() for rect in rectangles)
    center_x, center_y = (left + right) / 2, (top + bottom) / 2
    return min(
        screens,
        key=lambda screen: (
            (screen.geometry().center().x() - center_x) ** 2
            + (screen.geometry().center().y() - center_y) ** 2
        ),
    )


class DashboardWindow(QWidget):
    closeRequested = Signal()

    def __init__(self):
        super().__init__()
        self.setWindowTitle("NISHA")
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground, False)
        self.setAttribute(Qt.WA_NoSystemBackground, False)
        self.setAutoFillBackground(False)
        self.stack = QStackedLayout(self)
        self.wall_widget = WallDashboard()
        self.table_widget = self._build_table_mode()
        self.stack.addWidget(self.wall_widget)
        self.stack.addWidget(self.table_widget)
        self.display_mode = "wall"
        self.output_mode = "monitor"
        self.full_window = False
        self.compact_mode = False
        self.window_controls = QFrame(self)
        self.window_controls.setObjectName("windowControls")
        self.window_controls.setStyleSheet(
            "QFrame#windowControls {background:rgba(3,11,23,230); border:1px solid rgba(45,190,218,95); border-radius:9px;} "
            "QToolButton {color:#BDEAF0; background:transparent; border:none; border-radius:6px; font:16px 'Segoe UI';} "
            "QToolButton:hover {background:rgba(45,190,218,55);} QToolButton#closeButton:hover {color:#FF9A9A; background:rgba(160,40,55,100);}"
        )
        controls_layout = QHBoxLayout(self.window_controls)
        controls_layout.setContentsMargins(5, 4, 5, 4)
        controls_layout.setSpacing(2)
        self.minimize_button = self._window_button(
            "—", "Minimize NISHA to compact orbit view", self.toggle_compact_mode
        )
        self.full_button = self._window_button("□", "Toggle full-window mode", self.toggle_full_window)
        self.close_button = self._window_button("×", "Close NISHA", self.closeRequested.emit, "closeButton")
        controls_layout.addWidget(self.minimize_button)
        controls_layout.addWidget(self.full_button)
        controls_layout.addWidget(self.close_button)
        self.shortcuts = []
        self.bind_shortcut("F9", self.toggle_display_mode)
        self.bind_shortcut("F10", self.toggle_output_mode)
        self._apply_layout()

    def _window_button(self, label, description, callback, object_name=""):
        button = QToolButton(self.window_controls)
        button.setText(label)
        button.setAccessibleName(description)
        button.setToolTip(description)
        button.setFixedSize(34, 28)
        if object_name:
            button.setObjectName(object_name)
        button.clicked.connect(callback)
        return button

    def paintEvent(self, event):
        """Paint a complete dark, technical HUD backdrop behind both layouts."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        bounds = self.rect()

        base = QLinearGradient(0, 0, self.width(), self.height())
        base.setColorAt(0, QColor("#07111F"))
        base.setColorAt(0.48, QColor("#081827"))
        base.setColorAt(1, QColor("#030913"))
        painter.fillRect(bounds, base)

        glow = QRadialGradient(self.width() * 0.76, self.height() * 0.46, self.width() * 0.54)
        glow.setColorAt(0, QColor(16, 103, 127, 46))
        glow.setColorAt(0.62, QColor(9, 58, 83, 22))
        glow.setColorAt(1, QColor(3, 9, 19, 0))
        painter.fillRect(bounds, glow)

        # Fine drafting grid gives the UI the full-screen system-console feel
        # without competing with labels or the central orb.
        painter.setPen(QPen(QColor(64, 184, 211, 13), 1))
        spacing = 48
        for x in range(0, self.width(), spacing):
            painter.drawLine(x, 0, x, self.height())
        for y in range(0, self.height(), spacing):
            painter.drawLine(0, y, self.width(), y)

        if self.display_mode == "wall" and hasattr(self, "wall_widget"):
            orb_rect = (
                self.wall_widget.orb.geometry()
                .translated(self.wall_widget.hero_card.pos())
                .translated(self.wall_widget.pos())
            )
            center = orb_rect.center()
            radius = max(orb_rect.width(), orb_rect.height()) // 2
            painter.setBrush(Qt.NoBrush)
            for scale, alpha in ((1.28, 30), (1.52, 22), (1.78, 13)):
                diameter = int(radius * 2 * scale)
                painter.setPen(QPen(QColor(45, 201, 221, alpha), 1))
                painter.drawEllipse(center, diameter // 2, diameter // 2)
            painter.setPen(QPen(QColor(76, 213, 227, 31), 1))
            outer = int(radius * 1.78)
            for step in range(48):
                angle = step * 7.5
                direction = radians(angle)
                inner_scale = 1.69 if step % 4 == 0 else 1.74
                painter.drawLine(
                    int(center.x() + cos(direction) * radius * inner_scale),
                    int(center.y() + sin(direction) * radius * inner_scale),
                    int(center.x() + cos(direction) * outer),
                    int(center.y() + sin(direction) * outer),
                )

        # Quiet corner registration marks frame the interface like a projected HUD.
        painter.setPen(QPen(QColor(53, 192, 217, 72), 1.2))
        inset, arm = 18, 42
        for x, sx in ((inset, 1), (self.width() - inset, -1)):
            for y, sy in ((inset, 1), (self.height() - inset, -1)):
                painter.drawLine(x, y, x + sx * arm, y)
                painter.drawLine(x, y, x, y + sy * arm)

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
        if self.compact_mode:
            available = screen.availableGeometry()
            width = min(420, max(340, int(geo.width() * 0.27)))
            height = min(320, max(250, int(geo.height() * 0.30)))
            x = available.x() + available.width() - width - 18
            y = available.y() + available.height() - height - 18
            self.stack.setCurrentWidget(self.wall_widget)
            self.resize(width, height)
            self.move(x, y)
            if self.windowHandle():
                self.windowHandle().setScreen(screen)
            self.window_controls.setGeometry(max(0, width - 126), 8, 116, 38)
            self.window_controls.raise_()
            return
        fraction = 1.0 if self.full_window else (0.95 if self.display_mode == "wall" else 0.35)
        width, height = int(geo.width() * fraction), int(geo.height() * fraction)
        if self.full_window:
            x, y = geo.x(), geo.y()
        elif self.display_mode == "wall":
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
        self.window_controls.setGeometry(max(0, width - 126), 10, 116, 38)
        self.window_controls.raise_()

    def toggle_compact_mode(self):
        self.compact_mode = not self.compact_mode
        self.full_window = False
        self.minimize_button.setText("↗" if self.compact_mode else "—")
        self.minimize_button.setAccessibleName(
            "Restore full NISHA window" if self.compact_mode else "Minimize NISHA to compact orbit view"
        )
        self.minimize_button.setToolTip(self.minimize_button.accessibleName())
        self.full_button.setVisible(not self.compact_mode)
        self.wall_widget.set_compact_mode(self.compact_mode)
        self._apply_layout()

    def toggle_full_window(self):
        if self.compact_mode:
            self.toggle_compact_mode()
        self.full_window = not self.full_window
        self.full_button.setText("❐" if self.full_window else "□")
        self.full_button.setToolTip("Restore window size" if self.full_window else "Toggle full-window mode")
        self._apply_layout()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "window_controls"):
            self.window_controls.setGeometry(max(0, self.width() - 126), 10, 116, 38)
            self.window_controls.raise_()

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

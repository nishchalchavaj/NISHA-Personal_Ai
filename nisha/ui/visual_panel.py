"""Movable, opaque left-side results card with native image/video display."""

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPen, QPixmap
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from nisha.errors import NishaError
from nisha.ui.text_security import PlainTextEdit
from nisha.url_security import browser_source


class PlainCaption(PlainTextEdit):
    def __init__(self):
        super().__init__()
        self.setReadOnly(True)
        self.setMinimumHeight(70)
        self.setMaximumHeight(140)
        self.setStyleSheet(
            "color:#DDFBF5; background:transparent; border:none; font:14px 'Segoe UI';"
        )

    def setText(self, text):
        self.setPlainText(text)

    def text(self):
        return self.toPlainText()


class VisualPanel(QWidget):
    closed = Signal()
    opened = Signal(int)
    image_displayed = Signal(bytes, int)
    asset_changed = Signal(int)
    review_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setWindowTitle("NISHA Results")
        self.setAttribute(Qt.WA_TranslucentBackground, False)
        self.resize(460, 390)
        self.assets = []
        self.index = 0
        self.pixmap = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        header = QHBoxLayout()
        self.title = QLabel("Visual reference")
        self.title.setTextFormat(Qt.PlainText)
        self.title.setWordWrap(True)
        header.addWidget(self.title, 1)
        close = QPushButton("×")
        close.setFixedSize(28, 28)
        close.clicked.connect(self.dismiss)
        header.addWidget(close)
        layout.addLayout(header)
        self.question = QLabel()
        self.question.setTextFormat(Qt.PlainText)
        self.question.setWordWrap(True)
        layout.addWidget(self.question)
        self.response = PlainTextEdit()
        self.response.setReadOnly(True)
        self.response.setMinimumHeight(110)
        self.response.setStyleSheet(
            "color:#DDFBF5; background:transparent; border:none; font:13px 'Segoe UI';"
        )
        layout.addWidget(self.response, 2)
        self.review_button = QPushButton("Review YouTube action")
        self.review_button.clicked.connect(self.review_requested.emit)
        layout.addWidget(self.review_button)
        self.review_button.hide()
        self.stack = QStackedWidget()
        self.image = QLabel()
        self.image.setAlignment(Qt.AlignCenter)
        self.image.setMinimumSize(120, 180)
        self.image.setTextFormat(Qt.PlainText)
        self.video = QVideoWidget()
        self.video.videoSink().videoFrameChanged.connect(self.video_frame)
        self.stack.addWidget(self.image)
        self.stack.addWidget(self.video)
        layout.addWidget(self.stack, 1)
        self.stack.hide()
        self.caption = PlainCaption()
        self.caption.hide()
        layout.addWidget(self.caption)
        footer = QHBoxLayout()
        self.previous, self.next = QPushButton("‹"), QPushButton("›")
        self.previous.clicked.connect(lambda: self.advance(-1))
        self.next.clicked.connect(lambda: self.advance(1))
        self.counter = QLabel()
        self.source = QPushButton("View source")
        self.source.clicked.connect(self.open_source)
        self.play = QPushButton("Play / pause")
        self.play.clicked.connect(self.toggle_video)
        for widget in [self.previous, self.counter, self.next, self.play, self.source]:
            footer.addWidget(widget)
        layout.addLayout(footer)
        self.footer_widgets = [self.previous, self.counter, self.next, self.play, self.source]
        for widget in self.footer_widgets:
            widget.hide()
        self.player = QMediaPlayer(self)
        self.audio = QAudioOutput(self)
        self.audio.setMuted(True)
        self.player.setAudioOutput(self.audio)
        self.player.setVideoOutput(self.video)
        self.player.errorOccurred.connect(self.playback_error)
        self.loader = None
        self.stream_resolver = None
        self.snapshot_timer = QTimer(self)
        self.snapshot_timer.setInterval(5000)
        self.snapshot_timer.timeout.connect(self.refresh_snapshot)
        self.player.playbackStateChanged.connect(self.playback_changed)
        self.setStyleSheet(
            "QLabel {color: #DDFBF5; background: transparent;} QPushButton {color:#2DE1C2; background:rgba(45,225,194,15); border:1px solid rgba(45,225,194,65); border-radius:6px; padding:4px 8px;} QPushButton:hover {background:rgba(45,225,194,40);} QStackedWidget {background:transparent;}"
        )
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

    def anchor(self, owner):
        area = owner.screen().availableGeometry()
        width = min(560, max(320, int(owner.width() * 0.32)), area.width() - 30)
        height = min(660, area.height() - 60)
        self.resize(width, height)
        x = area.left() + 24
        y = max(
            area.top() + 16,
            min(area.bottom() - height - 16, owner.y() + (owner.height() - height) // 2),
        )
        self.move(max(area.left() + 16, x), y)

    def set_response(self, question, answer):
        self.question.setText(question)
        scrollbar = self.response.verticalScrollBar()
        at_bottom = scrollbar.value() >= scrollbar.maximum() - 4
        old_position = scrollbar.value()
        self.response.setPlainText(answer)
        scrollbar.setValue(scrollbar.maximum() if at_bottom else old_position)
        if question or answer:
            self.anchor(self.parentWidget())
            self.opened.emit(self.width() + 40)
            self.show()

    def clear(self):
        self.assets = []
        self.index = 0
        self.question.clear()
        self.response.clear()
        self.review_button.hide()
        self.caption.clear()
        self.title.setText("NISHA Results")
        self.stack.hide()
        self.caption.hide()
        self.snapshot_timer.stop()
        self.player.stop()
        self.pixmap = None
        for widget in self.footer_widgets:
            widget.hide()

    def present(self, assets, loader, stream_resolver=None):
        self.assets, self.loader, self.index = assets, loader, 0
        self.stream_resolver = stream_resolver
        self.anchor(self.parentWidget())
        self.opened.emit(self.width() + 40)
        self.stack.show()
        self.caption.show()
        for widget in self.footer_widgets:
            widget.show()
        self.show()
        self.show_asset()
        self.raise_()

    def show_asset(self):
        self.snapshot_timer.stop()
        self.player.stop()
        self.player.setSource(QUrl())
        self.pixmap = None
        asset = self.assets[self.index]
        self.title.setText(asset.title)
        self.caption.setText(asset.caption)
        self.counter.setText(f"{self.index + 1} / {len(self.assets)}")
        self.asset_changed.emit(self.index)
        self.previous.setEnabled(len(self.assets) > 1)
        self.next.setEnabled(len(self.assets) > 1)
        self.source.setVisible(browser_source(asset.source))
        self.play.setVisible(asset.kind in {"video", "camera_stream"})
        if asset.kind == "camera_stream":
            self.stack.setCurrentWidget(self.video)
            try:
                self.player.setSource(QUrl(self.stream_resolver(asset)))
                self.player.play()
                self.caption.setText("Connecting camera stream… · audio muted")
            except (NishaError, OSError, ValueError, TypeError):
                self.caption.setText(
                    "Camera connection unavailable. Check Ctrl+D endpoints and credentials."
                )
        elif asset.kind == "video":
            self.stack.setCurrentWidget(self.video)
            from urllib.parse import urlsplit

            from nisha.media import WIKI_HOSTS
            from nisha.video_security import local_video

            try:
                if asset.location.startswith("https://"):
                    if (
                        not browser_source(asset.location)
                        or urlsplit(asset.location).hostname not in WIKI_HOSTS
                    ):
                        raise NishaError("Unsupported remote video source.")
                    source = QUrl(asset.location)
                else:
                    source = QUrl.fromLocalFile(str(local_video(asset.location)))
            except (NishaError, OSError, ValueError):
                self.caption.setText(
                    "This video couldn't be opened safely. Check its format and size."
                )
                return
            self.player.setSource(source)
            self.player.play()  # Muted playback doesn't interfere with wake listening.
        else:
            self.stack.setCurrentWidget(self.image)
            self.image.clear()
            self.image.setText("Loading visual…")
            self.loader(asset, self.index)
            if asset.kind == "camera_snapshot":
                self.snapshot_timer.start()

    def refresh_snapshot(self):
        if self.isVisible() and self.assets and self.assets[self.index].kind == "camera_snapshot":
            self.loader(self.assets[self.index], self.index)

    def playback_changed(self, state):
        if (
            self.assets
            and self.assets[self.index].kind == "camera_stream"
            and state == QMediaPlayer.PlayingState
        ):
            self.caption.setText("Live camera stream · audio muted · no recording")

    def image_ready(self, data, index):
        if index != self.index or not self.isVisible():
            return
        from nisha.image_security import passive_image

        try:
            data = passive_image(data)
        except NishaError:
            self.image.setText("This image couldn't be displayed safely.")
            return
        pixmap = QPixmap()
        if not pixmap.loadFromData(data):
            self.image.setText("This image couldn't be displayed.")
            return
        self.pixmap = pixmap
        self.fit_image()
        self.image_displayed.emit(data, index)
        if self.assets and self.assets[self.index].kind == "camera_snapshot":
            from datetime import datetime

            self.caption.setText(
                "Latest snapshot "
                + datetime.now().astimezone().strftime("%H:%M:%S")
                + " · refreshes every 5s · no recording"
            )

    def playback_error(self, *_):
        camera = self.assets and self.assets[self.index].kind == "camera_stream"
        self.caption.setText(
            "Camera stream unavailable. Check Ctrl+D endpoints, credentials and stream format."
            if camera
            else "This video couldn't be played. Check its format."
        )

    def video_frame(self, frame):
        if not self.assets or self.assets[self.index].kind != "video" or not frame.isValid():
            return
        image = frame.toImage()
        if image.isNull():
            return
        data = QByteArray()
        buffer = QBuffer(data)
        buffer.open(QIODevice.WriteOnly)
        image.save(buffer, "JPEG")
        self.image_displayed.emit(bytes(data), self.index)

    def image_failed(self, message):
        self.pixmap = None
        self.image.clear()
        self.image.setText(message)
        if self.assets and self.assets[self.index].kind == "camera_snapshot":
            self.caption.setText("No current snapshot · retrying every 5s")

    def fit_image(self):
        if self.pixmap:
            self.image.setPixmap(
                self.pixmap.scaled(self.image.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
            )

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.fit_image()

    def advance(self, amount):
        if not self.assets:
            return
        self.index = (self.index + amount) % len(self.assets)
        self.show_asset()

    def toggle_video(self):
        if self.player.playbackState() == QMediaPlayer.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    def open_source(self):
        from PySide6.QtGui import QDesktopServices

        if self.assets and browser_source(self.assets[self.index].source):
            QDesktopServices.openUrl(QUrl(self.assets[self.index].source))

    def dismiss(self):
        self.snapshot_timer.stop()
        self.player.stop()
        self.player.setSource(QUrl())
        self.hide()
        self.closed.emit()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.drag_offset = event.globalPosition().toPoint() - self.pos()

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.LeftButton and hasattr(self, "drag_offset"):
            self.move(event.globalPosition().toPoint() - self.drag_offset)

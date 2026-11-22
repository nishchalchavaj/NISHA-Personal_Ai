"""
NISHA's orb — built from a pre-made rotating particle-sphere animation
(jarvis.gif), recolored to NISHA's teal and given real transparency
(black background pixels become invisible, bright pixels stay visible),
so it floats cleanly with no background box.
"""

from pathlib import Path

import numpy as np
from PIL import Image, ImageSequence
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap
from PySide6.QtWidgets import QLabel

NISHA_TEAL = (45, 225, 194)
STATE_COLORS = {
    "idle": NISHA_TEAL,
    "listening": NISHA_TEAL,
    "thinking": (32, 76, 156),
    "speaking": NISHA_TEAL,
}
GIF_PATH = Path(__file__).parent / "assets" / "orb.gif"


def _process_frame(frame: Image.Image, size: int) -> QPixmap:
    frame = frame.convert("L")
    # crop to a centered square first, so the sphere isn't stretched into an oval
    w, h = frame.size
    crop_size = min(w, h)
    left = (w - crop_size) // 2
    top = (h - crop_size) // 2
    frame = frame.crop((left, top, left + crop_size, top + crop_size))
    frame = frame.resize((size, size), Image.LANCZOS)
    arr = np.array(frame, dtype=np.uint8)
    h, w = arr.shape
    rgba = np.zeros((h, w, 4), dtype=np.uint8)
    rgba[..., 0] = NISHA_TEAL[0]
    rgba[..., 1] = NISHA_TEAL[1]
    rgba[..., 2] = NISHA_TEAL[2]
    rgba[..., 3] = arr  # brightness becomes transparency: black = invisible, bright = visible
    qimage = QImage(rgba.tobytes(), w, h, QImage.Format_RGBA8888)
    return QPixmap.fromImage(qimage.copy())


class OrbGifWidget(QLabel):
    def __init__(self, size=240, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_NoSystemBackground)
        self.setStyleSheet("background: transparent;")
        self.setAlignment(Qt.AlignCenter)

        with Image.open(GIF_PATH) as gif:
            self.frames = [
                _process_frame(f.convert("RGBA"), size) for f in ImageSequence.Iterator(gif)
            ]
        self.setScaledContents(True)
        self.frame_index = 0
        self.state = "idle"

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._advance)
        self._apply_interval()

        self.setPixmap(self.frames[0])

    def _apply_interval(self):
        # different states play the same animation at different speeds
        speed_map = {"idle": 60, "listening": 32, "thinking": 22, "speaking": 28}
        self.timer.start(speed_map.get(self.state, 45))

    def set_state(self, state: str):
        if state in ("idle", "listening", "thinking", "speaking"):
            changed = state != self.state
            self.state = state
            self._apply_interval()
            if changed:
                self._show_frame()

    def _advance(self):
        self.frame_index = (self.frame_index + 1) % len(self.frames)
        self._show_frame()

    def _show_frame(self):
        frame = self.frames[self.frame_index]
        if STATE_COLORS[self.state] != NISHA_TEAL:
            frame = frame.copy()
            painter = QPainter(frame)
            painter.setCompositionMode(QPainter.CompositionMode_SourceIn)
            painter.fillRect(frame.rect(), QColor(*STATE_COLORS[self.state]))
            painter.end()
        self.setPixmap(frame)

import pytest
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

from nisha.ui.orb_gif_widget import STATE_COLORS, OrbGifWidget


@pytest.fixture
def orb(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    widget = OrbGifWidget(size=120)
    widget.timer.stop()
    yield widget
    widget.timer.stop()
    widget.close()
    app.processEvents()


def test_activity_colors_preserve_animation_transparency_size_and_position(orb):
    original = orb.frames[0].toImage().convertToFormat(QImage.Format_RGBA8888)
    point = max(
        ((x, y) for y in range(original.height()) for x in range(original.width())),
        key=lambda xy: original.pixelColor(*xy).alpha(),
    )
    alpha = original.pixelColor(*point).alpha()
    position = orb.pos()
    for state, expected in STATE_COLORS.items():
        orb.set_state(state)
        orb.timer.stop()
        frame = orb.pixmap().toImage()
        color = frame.pixelColor(*point)
        assert max(abs(a - b) for a, b in zip(color.getRgb()[:3], expected)) <= 2
        assert color.alpha() == alpha
        assert frame.pixelColor(0, 0).alpha() == original.pixelColor(0, 0).alpha()
        assert orb.size().width() == orb.size().height() == 120
        assert orb.pos() == position
    assert STATE_COLORS["listening"] == STATE_COLORS["speaking"] == STATE_COLORS["idle"]
    assert STATE_COLORS["thinking"] == (32, 76, 156)

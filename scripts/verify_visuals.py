"""Render the glass media card and play a synthetic video offscreen."""

import os
import shutil
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtCore import QEventLoop, QRect, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QFontDatabase, QImage, QPainter, QPen
from PySide6.QtMultimedia import QMediaPlayer
from PySide6.QtWidgets import QApplication

from nisha.core import NishaCore
from nisha.media import MediaService
from nisha.settings import load_settings
from nisha.ui.app import NishaWindow


class Gateway:
    def close(self):
        pass


def wait_until(app, condition, timeout=8000):
    loop = QEventLoop()
    timer = QTimer()
    timer.setInterval(25)
    timer.timeout.connect(lambda: loop.quit() if condition() else None)
    timer.start()
    QTimer.singleShot(timeout, loop.quit)
    loop.exec()
    timer.stop()
    app.processEvents()
    assert condition(), "Visual job did not reach expected state"


def main():
    settings = load_settings()
    with TemporaryDirectory(prefix="visual-check-", dir=settings.data_dir) as directory:
        root = Path(directory)
        core = NishaCore(
            settings.model_copy(update={"data_dir": root, "online_visuals": False}), Gateway()
        )
        app = QApplication([])
        QFontDatabase.addApplicationFont("C:/Windows/Fonts/segoeui.ttf")
        app.setFont(QFont("Segoe UI", 10))
        window = NishaWindow(core, start_listener=False)
        window.vision.describe = lambda data: (
            "A synthetic diagram with colored circles arranged along a horizontal line."
        )

        # Qt's offscreen backend exposes an 800px virtual screen. Emulate the
        # full-HD monitor used by the desktop while rendering without windows.
        class PreviewScreen:
            def availableGeometry(self):
                return QRect(0, 0, 1920, 1080)

        window.screen = lambda: PreviewScreen()
        window.resize(1824, 1026)
        window.show()
        app.processEvents()
        original_orb = window.wall_widget.orb.pos()
        image_path = root / "solar_system.png"
        image = QImage(800, 430, QImage.Format_ARGB32)
        image.fill(QColor("#0B1720"))
        painter = QPainter(image)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QPen(QColor("#507C8B"), 2))
        painter.drawLine(60, 215, 730, 215)
        for x, size, color in [
            (90, 45, "#F2C56F"),
            (240, 15, "#A8B4C5"),
            (400, 26, "#53C8DE"),
            (590, 36, "#D99475"),
        ]:
            painter.setBrush(QColor(color))
            painter.drawEllipse(x - size, 215 - size, size * 2, size * 2)
        painter.setPen(QColor("#DDFBF5"))
        painter.setFont(QFont("Segoe UI", 20))
        painter.drawText(40, 65, "Solar system · schematic")
        painter.setFont(QFont("Segoe UI", 12))
        painter.drawText(40, 385, "Synthetic UI check · not to scale")
        painter.end()
        image.save(str(image_path))
        asset = MediaService.local_file(image_path)
        window.current_user = "Explain the solar system"
        window.current_reply = "This schematic uses colored circles to represent celestial bodies. It illustrates their arrangement; sizes and distances are not to scale."
        window.render()
        window.visual_panel.present([asset], window.load_visual_image)
        wait_until(
            app, lambda: window.visual_panel.pixmap is not None and not window.background_jobs
        )
        panel = window.visual_panel
        assert panel.testAttribute(Qt.WA_TranslucentBackground)
        assert panel.x() == 24 and panel.x() < window.x() + window.width() / 2
        assert window.wall_widget.orb.pos() == original_orb
        assert abs(panel.geometry().center().y() - window.geometry().center().y()) < 50
        orb = window.wall_widget.orb.geometry().translated(window.pos())
        assert not panel.geometry().intersects(orb), "Results overlap the orb"
        panel.grab().save(str(settings.data_dir / "visual-panel-preview.png"))
        # Composite two native widget captures to document the floating placement.
        capture = window.grab()
        painter = QPainter(capture)
        painter.drawPixmap(panel.pos() - window.pos(), panel.grab())
        painter.end()
        capture.save(str(settings.data_dir / "desktop-visual-preview.png"))
        panel.dismiss()
        assert not panel.isVisible()
        ffmpeg = shutil.which("ffmpeg")
        if ffmpeg:
            video = root / "synthetic_video.mp4"
            subprocess.run(
                [
                    ffmpeg,
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-f",
                    "lavfi",
                    "-i",
                    "testsrc=size=320x180:rate=10",
                    "-t",
                    "2",
                    "-pix_fmt",
                    "yuv420p",
                    str(video),
                ],
                check=True,
                timeout=30,
            )
            panel.present([MediaService.local_file(video)], window.load_visual_image)
            assert panel.audio.isMuted()
            wait_until(
                app,
                lambda: (
                    panel.player.position() > 100
                    or panel.player.mediaStatus() == QMediaPlayer.EndOfMedia
                ),
            )
            panel.dismiss()
            print("PASS: synthetic video decoded and played muted in the floating card.")
        window.close()
        app.processEvents()
        core.close()
    print(
        "PASS: glass panel, image load, left-middle placement, fixed orb, dismissal and original UI. Preview: data/desktop-visual-preview.png"
    )


if __name__ == "__main__":
    main()

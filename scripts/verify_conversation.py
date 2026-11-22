"""Render local conversation bubbles beside the unchanged dashboard/results UI."""

import os
from pathlib import Path
from tempfile import TemporaryDirectory

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtCore import QEventLoop, QRect, QTimer
from PySide6.QtGui import QFont, QFontDatabase, QImage, QPainter
from PySide6.QtWidgets import QApplication, QWidget

from nisha.core import NishaCore
from nisha.settings import load_settings
from nisha.ui.app import NishaWindow


class Gateway:
    def close(self):
        pass


class Screen:
    def availableGeometry(self):
        return QRect(0, 0, 1920, 1080)


def main():
    settings = load_settings()
    app = QApplication([])
    QFontDatabase.addApplicationFont("C:/Windows/Fonts/segoeui.ttf")
    app.setFont(QFont("Segoe UI", 10))
    with TemporaryDirectory(prefix="chat-preview-", dir=settings.data_dir) as directory:
        core = NishaCore(
            settings.model_copy(update={"data_dir": Path(directory), "online_visuals": False}),
            Gateway(),
        )
        window = NishaWindow(core, start_listener=False)
        window.screen = lambda: Screen()
        window.resize(1824, 1026)
        window.show()
        app.processEvents()
        orb = window.wall_widget.orb.pos()
        for user, reply in [
            ("Good evening, NISHA.", "Good evening, Boss. How was your day?"),
            (
                "It was busy. Let's keep replies short.",
                "Sure. I'll keep them short unless you ask for more detail.",
            ),
            (
                "Write an email to my supplier about the delayed components.",
                "Subject: Urgent delivery update\n\nDear Supplier,\n\nPlease confirm when the delayed components will arrive. I need them urgently to complete my project. If any items are unavailable, please let me know immediately so we can arrange an alternative.\n\nThank you,\nNishchal",
            ),
        ]:
            window.current_user, window.current_reply = user, reply
            window.render()
        window.toggle_conversation()
        window.set_state("Listening")
        for widget in window.findChildren(QWidget):
            widget.update()
        loop = QEventLoop()
        QTimer.singleShot(200, loop.quit)
        loop.exec()
        capture = QImage(1920, 1080, QImage.Format_ARGB32)
        capture.fill(0xFF000000)
        painter = QPainter(capture)
        painter.drawPixmap(window.pos(), window.grab())
        for panel in (window.visual_panel, window.chat_panel):
            painter.drawPixmap(panel.pos(), panel.grab())
        painter.end()
        output = settings.data_dir / "conversation-preview.png"
        capture.save(str(output))
        centered = window.wall_widget.orb.geometry().translated(
            window.wall_widget.mapToGlobal(window.wall_widget.rect().topLeft())
        )
        assert not centered.intersects(window.chat_panel.geometry())
        assert not centered.intersects(window.visual_panel.geometry())
        window.chat_panel.close()
        assert window.wall_widget.orb.pos() == orb
        assert window.visual_panel.isVisible()
        window.close()
        app.processEvents()
        core.close()
    print(
        f"PASS: two-sided glass chat on the right, separate left results, centered/restored orb. Preview: {output}"
    )


if __name__ == "__main__":
    main()

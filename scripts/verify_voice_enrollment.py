"""Check the real microphone recorder without saving or transcribing room audio."""

import os
from tempfile import TemporaryDirectory

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from pathlib import Path

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication

from nisha.core import NishaCore
from nisha.settings import load_settings
from nisha.ui.app import NishaWindow
from nisha.ui.voice_dialog import VoiceDialog


class Gateway:
    def close(self):
        pass


def main():
    app = QApplication([])
    QFontDatabase.addApplicationFont("C:/Windows/Fonts/segoeui.ttf")
    app.setFont(QFont("Segoe UI", 10))
    settings = load_settings()
    with TemporaryDirectory(prefix="voice-enrollment-check-", dir=settings.data_dir) as directory:
        core = NishaCore(settings.model_copy(update={"data_dir": Path(directory)}), Gateway())
        window = NishaWindow(core, start_listener=False)
        dialog = VoiceDialog(window)
        assert dialog.microphone.currentData() is None
        ticks = []
        timer = QTimer()
        timer.setInterval(50)
        timer.timeout.connect(lambda: ticks.append(True))
        timer.start()
        dialog.show()
        app.processEvents()
        destination = settings.data_dir / "voice-enrollment-preview.png"
        dialog.grab().save(str(destination))
        dialog.record_sample()
        loop = QEventLoop()
        dialog.job.finished.connect(loop.quit)
        QTimer.singleShot(15000, loop.quit)
        loop.exec()
        try:
            assert dialog.job.wait(2000), "Recorder failed to stop promptly"
            app.processEvents()
            assert dialog.recording is not None, dialog.status.text()
            assert len(dialog.recording) == 4 * 16000
            assert dialog.source.startswith("Windows default"), dialog.source
            assert len(ticks) > 20, "Qt stopped responding while recording"
            assert not dialog.profile.entries() and not list(dialog.profile.samples.iterdir())
            print(
                "PASS: real Windows default input recorded a four-second take; Qt stayed responsive and no audio was saved or transcribed. Preview:",
                destination,
            )
        finally:
            dialog.job.requestInterruption()
            dialog.job.wait()
            dialog.recording = None
            dialog.reject()
            timer.stop()
            window.close()
            core.close()


if __name__ == "__main__":
    main()

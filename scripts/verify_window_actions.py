"""Verify native actions on newly created disposable test windows only."""

import json
import os
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from time import sleep

from nisha.window_actions import WindowActions, WindowsBackend


def child(stop_file):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget

    class Unsaved(QWidget):
        def closeEvent(self, event):
            if self.property("test_complete"):
                event.accept()
            else:
                event.ignore()  # Simulate an app waiting for a save decision.

    app = QApplication([])
    windows = [QWidget(), QWidget(), Unsaved()]
    for index, window in enumerate(windows):
        window.setWindowTitle(f"NISHA disposable window verification {index}")
        layout = QVBoxLayout(window)
        layout.addWidget(QLabel("Disposable native-action test. No user files are open."))
        window.resize(360, 100)
        window.show()
    QTimer.singleShot(
        500,
        lambda: print(
            json.dumps({"pid": os.getpid(), "handles": [int(w.winId()) for w in windows]}),
            flush=True,
        ),
    )

    def finish():
        windows[2].setProperty("test_complete", True)
        app.quit()

    shutdown = QTimer()
    shutdown.timeout.connect(lambda: finish() if Path(stop_file).exists() else None)
    shutdown.start(100)
    QTimer.singleShot(20000, finish)
    app.exec()


def verify(stop_file):
    process = subprocess.Popen(
        [sys.executable, str(Path(__file__).resolve()), "--child", str(stop_file)],
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        identity = json.loads(process.stdout.readline())
        backend = WindowsBackend()
        targets = [
            w
            for w in backend.windows()
            if w.pid == identity["pid"] and w.handle in identity["handles"]
        ]
        assert len(targets) == 3, targets
        actions = WindowActions(backend)
        result = actions.perform("minimize", windows=targets)
        assert all(backend.status(w) == "minimized" for w in targets), result
        for window in targets:
            backend.minimize_async(window.handle, 9)  # Restore our disposable windows only.
        sleep(0.2)
        result = actions.perform("close", windows=targets)
        assert "Verified 2" in result and "1 window(s) remain open" in result, result
        assert sum(backend.status(w) == "closed" for w in targets) == 2
        print(
            "PASS: native cross-process minimize and close verified on three disposable windows; refusing app was reported as remaining open. No user app window was changed."
        )
    finally:
        stop_file.touch()
        process.wait(timeout=5)


if __name__ == "__main__":
    if "--child" in sys.argv:
        child(sys.argv[-1])
    else:
        with TemporaryDirectory(prefix="nisha-window-test-") as directory:
            verify(Path(directory) / "stop")

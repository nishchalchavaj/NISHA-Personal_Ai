"""Exercise direct HTTP devices and live snapshot UI against a synthetic local server."""

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread
from time import sleep

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtCore import QBuffer, QByteArray, QEventLoop, QIODevice, QRect, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QFontDatabase, QImage, QPainter
from PySide6.QtWidgets import QApplication, QDialog, QLineEdit

from nisha.core import NishaCore
from nisha.settings import load_settings
from nisha.ui.app import NishaWindow
from nisha.ui.connections_dialog import ConnectionsDialog


class Gateway:
    def close(self):
        pass


def wait_until(app, condition, timeout=10000):
    loop, timer = QEventLoop(), QTimer()
    timer.setInterval(25)
    timer.timeout.connect(lambda: loop.quit() if condition() else None)
    timer.start()
    QTimer.singleShot(timeout, loop.quit)
    loop.exec()
    timer.stop()
    app.processEvents()
    assert condition(), "Connection UI did not reach the expected state"


def main():
    settings = load_settings()
    app = QApplication([])
    QFontDatabase.addApplicationFont("C:/Windows/Fonts/segoeui.ttf")
    app.setFont(QFont("Segoe UI", 10))
    frame = QImage(640, 360, QImage.Format_RGB32)
    frame.fill(QColor("#12343B"))
    painter = QPainter(frame)
    painter.setPen(QColor("#2DE1C2"))
    painter.setFont(QFont("Segoe UI", 20))
    painter.drawText(55, 150, "Synthetic camera connection check")
    painter.setFont(QFont("Segoe UI", 12))
    painter.drawText(55, 210, "Local HTTP server · no physical camera")
    painter.end()
    raw = QByteArray()
    buffer = QBuffer(raw)
    buffer.open(QIODevice.WriteOnly)
    frame.save(buffer, "JPEG")
    buffer.close()
    jpeg = bytes(raw)
    state = {"light": "off", "camera": True, "frames": 0}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_GET(self):
            sleep(0.25)  # Prove device work doesn't stall Qt.
            if self.path == "/snapshot":
                if not state["camera"]:
                    self.send_response(503)
                    self.end_headers()
                    return
                state["frames"] += 1
                self.send_response(200)
                self.send_header("Content-Type", "image/jpeg")
                self.end_headers()
                self.wfile.write(jpeg)
            else:
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"state": state["light"]}).encode())

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            state["light"] = body["state"]
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"{}")

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        with TemporaryDirectory(prefix="connections-check-", dir=settings.data_dir) as directory:
            root = Path(directory)
            project = root / "project"
            project.mkdir()
            core = NishaCore(
                settings.model_copy(update={"data_dir": root, "online_visuals": False}), Gateway()
            )
            window = NishaWindow(core, start_listener=False)
            window.device_poll_timer.stop()
            dialog = ConnectionsDialog(core.connections, window)
            dialog.name.setText("Demo project")
            dialog.folder.setText(str(project))
            dialog.requirements.setPlainText("Synthetic test requirements")
            dialog.budget.setText("INR 10000")
            dialog.save()
            assert dialog.result() == QDialog.Accepted
            assert core.connections.load().default_project == "Demo project"
            assert dialog.secret.echoMode() == QLineEdit.Password
            config = core.connections.load().model_dump()
            config["devices"] = [
                {
                    "id": "light",
                    "name": "Test light",
                    "kind": "light",
                    "status": {"url": base + "/status"},
                    "on": {"url": base + "/power", "method": "POST", "body": {"state": "on"}},
                    "off": {"url": base + "/power", "method": "POST", "body": {"state": "off"}},
                },
                {
                    "id": "camera",
                    "name": "Test camera",
                    "kind": "camera",
                    "snapshot": {"url": base + "/snapshot"},
                },
            ]
            core.connections.save(json.dumps(config))
            assert "reported by the device" in core.chat("turn on lights", core.new_session())
            assert state["light"] == "on"

            class Screen:
                def availableGeometry(self):
                    return QRect(0, 0, 1920, 1080)

            window.screen = lambda: Screen()
            window.resize(1824, 1026)
            window.show()
            original_orb = window.wall_widget.orb.pos()
            ticks = []
            responsive = QTimer()
            responsive.setInterval(40)
            responsive.timeout.connect(lambda: ticks.append(1))
            responsive.start()
            assert window.ui_command("show me CCTV camera visuals")
            panel = window.visual_panel
            panel.snapshot_timer.setInterval(300)
            wait_until(app, lambda: panel.pixmap is not None and state["frames"] >= 3)
            assert len(ticks) >= 10
            assert panel.audio.isMuted() and panel.testAttribute(Qt.WA_TranslucentBackground)
            assert panel.x() == 24 and panel.x() < window.width() // 2
            assert window.wall_widget.orb.pos() == original_orb
            assert "Latest snapshot" in panel.caption.text()
            capture = window.grab()
            painter = QPainter(capture)
            painter.drawPixmap(panel.pos() - window.pos(), panel.grab())
            painter.end()
            capture.save(str(settings.data_dir / "desktop-camera-preview.png"))
            state["camera"] = False
            wait_until(
                app, lambda: panel.pixmap is None and "No current snapshot" in panel.caption.text()
            )
            state["camera"] = True
            wait_until(app, lambda: panel.pixmap is not None)
            panel.dismiss()
            assert not panel.snapshot_timer.isActive()
            wait_until(app, lambda: not window.background_jobs)
            responsive.stop()
            window.close()
            app.processEvents()
            core.close()
        print(
            "PASS: local setup saved; direct HTTP light state verified; live snapshot refresh, failure/recovery, muted glass panel and responsive Qt UI checked. No real IoT or Gmail account used."
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


if __name__ == "__main__":
    main()

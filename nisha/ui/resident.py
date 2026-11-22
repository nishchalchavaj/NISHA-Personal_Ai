"""Single desktop resident, local show/quit control, and optional Windows login startup."""

import json
import os
import subprocess
from hashlib import sha256
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QLockFile, QObject
from PySide6.QtNetwork import QLocalServer, QLocalSocket

from nisha.errors import NishaError
from nisha.settings import ROOT


class DesktopInstance(QObject):
    def __init__(self, data_dir, parent=None):
        super().__init__(parent)
        self.name = (
            "NISHA-" + sha256(str(Path(data_dir).resolve()).casefold().encode()).hexdigest()[:20]
        )
        self.lock = QLockFile(str(Path(data_dir) / "desktop.lock"))
        self.server = QLocalServer(self)
        self.server.setSocketOptions(QLocalServer.UserAccessOption)
        self.window = None
        self.clients = []

    def notify(self, command):
        socket = QLocalSocket(self)
        socket.connectToServer(self.name)
        if not socket.waitForConnected(1500):
            socket.deleteLater()
            return False
        socket.write(command.encode("ascii") + b"\n")
        socket.flush()
        QCoreApplication.processEvents()
        success = socket.bytesToWrite() == 0 or socket.waitForBytesWritten(1500)
        socket.disconnectFromServer()
        socket.deleteLater()
        return success

    def acquire(self):
        if not self.lock.tryLock(0):
            return False
        if not self.server.listen(self.name):
            # Only the process holding the instance lock may remove a stale endpoint.
            QLocalServer.removeServer(self.name)
            if not self.server.listen(self.name):
                self.lock.unlock()
                raise NishaError("NISHA couldn't start its local desktop control channel.")
        self.server.newConnection.connect(self.accept_client)
        return True

    def accept_client(self):
        while self.server.hasPendingConnections():
            socket = self.server.nextPendingConnection()
            self.clients.append(socket)
            socket.setProperty("request", b"")
            socket.readyRead.connect(lambda socket=socket: self.read_client(socket))
            socket.disconnected.connect(lambda socket=socket: self.release_client(socket))
            if socket.bytesAvailable():
                self.read_client(socket)

    def read_client(self, socket):
        data = socket.property("request") + bytes(socket.readAll())
        if len(data) > 32:
            socket.abort()
            return
        socket.setProperty("request", data)
        if b"\n" not in data:
            return
        command = data.split(b"\n", 1)[0]
        if self.window:
            if command == b"show":
                self.window.open_fresh()
            elif command == b"quit":
                self.window.quit_application()
        socket.disconnectFromServer()

    def release_client(self, socket):
        if socket in self.clients:
            self.clients.remove(socket)
        socket.deleteLater()

    def close(self):
        for socket in list(self.clients):
            socket.abort()
        self.server.close()
        self.lock.unlock()


class LoginStartup:
    def __init__(self, data_dir):
        self.marker = Path(data_dir) / "desktop-startup.json"

    @staticmethod
    def command():
        executable = (
            Path(os.environ.get("WINDIR", "C:/Windows"))
            / "System32/WindowsPowerShell/v1.0/powershell.exe"
        )
        return subprocess.list2cmdline(
            [
                str(executable),
                "-NoProfile",
                "-WindowStyle",
                "Hidden",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(ROOT / "scripts/start.ps1"),
                "-Background",
            ]
        )

    def enabled(self):
        if os.name != "nt":
            return False
        import winreg

        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run"
            ) as key:
                return winreg.QueryValueEx(key, "NISHA")[0] == self.command()
        except OSError:
            return False

    def set_enabled(self, enabled):
        if os.name != "nt":
            raise NishaError("Automatic login startup is available on Windows.")
        import winreg

        try:
            with winreg.CreateKeyEx(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Run",
                0,
                winreg.KEY_SET_VALUE,
            ) as key:
                if enabled:
                    winreg.SetValueEx(key, "NISHA", 0, winreg.REG_SZ, self.command())
                else:
                    try:
                        winreg.DeleteValue(key, "NISHA")
                    except FileNotFoundError:
                        pass
            self.marker.write_text(json.dumps({"initialized": True}), encoding="utf-8")
        except OSError as exc:
            raise NishaError(
                "Windows login startup couldn't be updated. Use the launcher manually."
            ) from exc

    def initialize(self):
        # Wake listening after Windows login requires a resident process. Later
        # launches respect the user's tray-menu choice, including opting out.
        if os.name == "nt" and not self.marker.exists():
            self.set_enabled(True)

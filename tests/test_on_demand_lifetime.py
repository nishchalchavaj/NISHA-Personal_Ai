import ctypes
import os
import subprocess
import sys
import time
from ctypes import wintypes
from pathlib import Path

import pytest


@pytest.mark.parametrize("action", ["close", "hide_to_background", "close_requested"])
def test_close_on_demand_window_stops_listening_instead_of_hiding(core, monkeypatch, action):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from nisha.ui.app import NishaWindow

    app = QApplication.instance() or QApplication([])
    window = NishaWindow(core, start_listener=False, background_enabled=True, on_demand=True)
    window.show()
    app.processEvents()
    getattr(window, action)()
    app.processEvents()
    assert window.closing and not window.in_background and not window.isVisible()
    assert not window.recovery_timer.isActive()


@pytest.mark.skipif(os.name != "nt", reason="Windows job object lifecycle")
def test_owned_child_exits_with_app_but_unrelated_process_survives(tmp_path):
    ready, stop, user_ready = tmp_path / "child.pid", tmp_path / "exit", tmp_path / "user-app.pid"
    program = """
import subprocess, sys, time
from pathlib import Path
from nisha.process_lifetime import attach_child_lifetime, user_app_options
attach_child_lifetime()
child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
user_app = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'], **user_app_options())
Path(sys.argv[3]).write_text(str(user_app.pid))
Path(sys.argv[1]).write_text(str(child.pid))
while not Path(sys.argv[2]).exists():
    time.sleep(.05)
"""
    control = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    parent = subprocess.Popen(
        [sys.executable, "-c", program, str(ready), str(stop), str(user_ready)],
        cwd=Path(__file__).resolve().parents[1],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    handle = None
    try:
        deadline = time.monotonic() + 10
        while not ready.exists() and parent.poll() is None and time.monotonic() < deadline:
            time.sleep(0.05)
        assert ready.exists(), parent.communicate(timeout=2)[1].decode(errors="replace")
        handle = kernel.OpenProcess(0x00100000, False, int(ready.read_text()))
        assert handle
        stop.write_text("exit normally")
        assert parent.wait(timeout=5) == 0
        assert kernel.WaitForSingleObject(handle, 5000) == 0
        assert control.poll() is None
        import psutil

        assert psutil.Process(int(user_ready.read_text())).is_running()
    finally:
        if user_ready.exists():
            import psutil

            try:
                user_process = psutil.Process(int(user_ready.read_text()))
                user_process.terminate()
                user_process.wait(timeout=5)
            except psutil.NoSuchProcess:
                pass
        if handle:
            kernel.CloseHandle(handle)
        if parent.poll() is None:
            parent.terminate()
            parent.wait(timeout=5)
        control.terminate()
        control.wait(timeout=5)

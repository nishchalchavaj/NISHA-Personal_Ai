"""Verify the archived orb's real browser loads bundled scripts under its CSP."""

import importlib.util
import json
import os
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication


def main():
    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location(
        "archived_orb", root / "legacy/prototype/ui/orb_web_widget.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    app = QApplication([])
    widget = module.OrbWebWidget()
    loop, results = QEventLoop(), []

    def inspect(ok):
        if not ok:
            results.append("load failed")
            loop.quit()
            return
        widget.set_state("thinking")
        widget.set_state("');window.securityInjected=true;//")

        def received(value):
            results.append(value)
            loop.quit()

        widget.page().runJavaScript(
            "JSON.stringify([typeof THREE, typeof setOrbState, typeof window.securityInjected, typeof stateSettings === 'undefined' ? 0 : stateSettings.amplitude])",
            received,
        )

    widget.loadFinished.connect(inspect)
    QTimer.singleShot(15000, loop.quit)
    loop.exec()
    assert widget.orb_profile.isOffTheRecord()
    assert len(results) == 1 and json.loads(results[0]) == [
        "object",
        "function",
        "undefined",
        0.22,
    ], results
    print(
        "PASS: real archived WebView loaded its bundled Three.js and state function under CSP; invalid state did not execute; profile is off the record.",
        flush=True,
    )
    widget.deleteLater()
    QTimer.singleShot(150, loop.quit)
    loop.exec()
    app.processEvents()


if __name__ == "__main__":
    main()

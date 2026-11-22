"""Run NISHA window commands on the exact synthetic editor windows opened by testing."""

import argparse
import json
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from time import monotonic, sleep

import psutil

from nisha.core import NishaCore
from nisha.desktop import DesktopAdapter
from nisha.errors import NishaError
from nisha.settings import load_settings
from nisha.window_actions import WindowActions, WindowsBackend


class NoGeneration:
    def stream(self, *args, **kwargs):
        raise AssertionError("Window commands must invoke the native adapter without generation")

    def close(self):
        pass


class TestEditors(WindowsBackend):
    def __init__(self, files):
        super().__init__()
        self.files = files
        observed = super().windows()
        self.targets = []
        for name, executable in files.items():
            matches = [
                window
                for window in observed
                if Path(name).stem in window.title
                and psutil.Process(window.pid).name().casefold() == executable
            ]
            if len(matches) != 1:
                raise NishaError(
                    f"Expected exactly one original synthetic editor window for {name}."
                )
            self.targets.extend(matches)

    def windows(self):
        return list(self.targets)

    def request(self, window, action):
        # If the user switches a tested editor to a different document during
        # this check, do not close that changed window or bypass save prompts.
        current = self.gui.GetWindowText(window.handle)
        if current != window.title:
            raise NishaError("The tested editor changed its document/title; leave it open.")
        super().request(window, action)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--launch", action="store_true", help="Reopen the synthetic editor files")
    args = parser.parse_args()
    settings = load_settings()
    report_dir = (
        settings.data_dir
        / "reports"
        / ("full-check-" + datetime.now().astimezone().date().isoformat())
    )
    report_dir.mkdir(parents=True, exist_ok=True)
    workspace = settings.data_dir / "editor-verification/workspace"
    paths = [
        max(workspace.glob(pattern), key=lambda path: path.stat().st_mtime)
        for pattern in ["nisha-document-*.txt", "nisha-document-*.docx", "nisha-code-*.py"]
    ]
    executables = {".txt": "notepad.exe", ".docx": "winword.exe", ".py": "code.exe"}
    files = {path.name: executables[path.suffix] for path in paths}
    if args.launch:
        desktop = DesktopAdapter(settings.apps)
        for path, app in zip(paths, ["notepad", "word", "vscode"]):
            desktop.open_document(path, app)
        deadline = monotonic() + 15
        while True:
            try:
                TestEditors(files)
                break
            except NishaError:
                if monotonic() >= deadline:
                    raise
                sleep(0.1)
    backend = TestEditors(files)
    assert len(backend.targets) == 3
    results = []
    with TemporaryDirectory(prefix="editor-window-check-", dir=settings.data_dir) as directory:
        core = NishaCore(settings.model_copy(update={"data_dir": Path(directory)}), NoGeneration())
        core.window_actions = WindowActions(backend)  # Use production timeout and command parsing.
        session = core.new_session()
        try:
            reply = core.chat("minimize windows", session)
            states = {window.title: backend.status(window) for window in backend.targets}
            results.append({"command": "minimize windows", "reply": reply, "states": states})
            (report_dir / "native-editor-window-actions.json").write_text(
                json.dumps(results, indent=2), encoding="utf-8"
            )
            print(json.dumps(results[-1], indent=2), flush=True)
            assert all(state == "minimized" for state in states.values()), reply
            assert "Verified 3 app window(s) minimized." in reply, reply
            for window in backend.targets:
                backend.minimize_async(window.handle, 9)  # Restore these test windows only.
            deadline = monotonic() + 3
            while monotonic() < deadline and any(
                backend.status(window) != "open" for window in backend.targets
            ):
                sleep(0.05)
            assert all(backend.status(window) == "open" for window in backend.targets)
            reply = core.chat("close windows", session)
            states = {window.title: backend.status(window) for window in backend.targets}
            results.append({"command": "close windows", "reply": reply, "states": states})
            print(json.dumps(results[-1], indent=2), flush=True)
            (report_dir / "native-editor-window-actions.json").write_text(
                json.dumps(results, indent=2), encoding="utf-8"
            )
            assert all(state == "closed" for state in states.values()), reply
            assert "Verified 3 app window(s) closed." in reply, reply
            print(
                "PASS: actual NISHA command routing minimized and closed the original Notepad, Word, and VS Code test windows. Native requests and observed window states verified; no model-generated success claims."
            )
        finally:
            core.close()


if __name__ == "__main__":
    main()

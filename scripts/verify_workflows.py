"""Real local generation into files; editor launches and Gmail remain simulated."""

import ast
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from docx import Document

from nisha.core import NishaCore
from nisha.settings import load_settings
from nisha.workflows import WorkflowService


class PreviewDesktop:
    def __init__(self):
        self.files = []

    def app_path(self, name):
        return None

    def open_document(self, path, app):
        self.files.append((path, app))


class PreviewGmail:
    def __init__(self):
        self.sent = []

    def send_email(self, *payload):
        self.sent.append(payload)
        return "Synthetic Gmail submission accepted."


def main():
    settings = load_settings()
    with TemporaryDirectory(prefix="workflow-check-", dir=settings.data_dir) as folder:
        core = NishaCore(settings.model_copy(update={"data_dir": Path(folder)}))
        desktop, gmail = PreviewDesktop(), PreviewGmail()
        core.workflows = WorkflowService(core.settings, desktop, gmail)
        try:
            core.chat("Write two sentences about solar energy in Notepad.", core.new_session())
            path, app = desktop.files[-1]
            assert app == "notepad" and "solar" in path.read_text().lower()
            print("PASS: real local generation into a Notepad text file.", flush=True)
            core.chat("Write a short study plan in Word, under 80 words.", core.new_session())
            path, app = desktop.files[-1]
            assert app == "word" and len(Document(path).paragraphs) >= 1
            print("PASS: real local generation into a readable Word document.", flush=True)
            core.chat(
                "Write Python code: a function add(a, b) returning a + b. No explanation.",
                core.new_session(),
            )
            path, app = desktop.files[-1]
            assert path.suffix == ".py" and app == "vscode"
            ast.parse(path.read_text())
            print("PASS: real local code generation saved as valid Python source.", flush=True)
            session = core.new_session()
            core.chat(
                "Write a short email to demo@example.invalid asking for a meeting tomorrow.",
                session,
            )
            pending = core.store.pending_email(session)
            assert pending and not gmail.sent
            payload = json.loads(Path(pending["path"]).read_text())
            assert payload["recipient"] == "demo@example.invalid" and payload["body"]
            core.chat("approve email " + pending["token"], session)
            assert len(gmail.sent) == 1
            print(
                "PASS: real email drafting and exact approval; Gmail transport simulated, no email sent.",
                flush=True,
            )
        finally:
            core.close()


if __name__ == "__main__":
    main()

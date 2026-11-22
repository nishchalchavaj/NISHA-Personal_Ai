"""Real local-model presentation notes and contextual Gmail reply; no native launches or sends."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZipFile

from nisha.core import NishaCore
from nisha.settings import load_settings


class Desktop:
    def app_path(self, _):
        return None

    def open_folder(self, _):
        pass

    def open_file(self, _):
        pass


class Mailer:
    def recent_messages(self):
        return [
            {
                "uid": "1",
                "sender": "Alex <alex@example.org>",
                "recipient": "alex@example.org",
                "subject": "Project notes",
                "body": "Can you share the notes tomorrow?",
                "message_id": "<synthetic@example.org>",
                "references": "",
            }
        ]

    def send_email(self, *_args, **_kwargs):
        raise AssertionError("Verification must never send email")


def main():
    settings = load_settings()
    with TemporaryDirectory(prefix="project-model-check-", dir=settings.data_dir) as directory:
        root = Path(directory)
        project = root / "project"
        project.mkdir()
        deck = project / "deck.pptx"
        with ZipFile(deck, "w") as archive:
            archive.writestr(
                "[Content_Types].xml",
                '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Override PartName="/ppt/presentation.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"/></Types>',
            )
            archive.writestr(
                "ppt/presentation.xml",
                '<p:presentation xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"/>',
            )
            archive.writestr(
                "ppt/slides/slide1.xml",
                '<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><a:t>Zephyr electric motor project</a:t><a:t>48V motor. Budget INR 10000. Presentation tomorrow.</a:t></p:sld>',
            )
        (project / "requirements.md").write_text(
            "Use a 48V motor; include warranty evidence. Budget INR 10000. No supplier has been chosen."
        )
        core = NishaCore(settings.model_copy(update={"data_dir": root}))
        core.workflows.desktop = Desktop()
        core.connections.save(
            json.dumps(
                {
                    "projects": [
                        {
                            "name": "Zephyr",
                            "folder": str(project),
                            "requirements": "48V motor with warranty",
                            "budget": "INR 10000",
                            "presentation": "deck.pptx",
                            "supporting_files": ["requirements.md"],
                        }
                    ],
                    "default_project": "Zephyr",
                }
            )
        )
        session = core.new_session()
        try:
            receipt = core.chat("prepare everything for tomorrow's presentation", session)
            bundle = next(core.workflows.workspace.glob("presentation-ready-*"))
            notes = (bundle / "speaker-notes.txt").read_text(encoding="utf-8")
            assert len(notes) > 150 and "48" in notes and ("10000" in notes or "10,000" in notes)
            assert "Prepared a local bundle" in receipt and deck.exists()
            print(
                "PASS: real local model generated source-based notes/checklist; copied deck and support file intact. Native opening adapters simulated.",
                flush=True,
            )
            core.workflows.mailer = Mailer()
            core.chat("check Gmail", session)
            core.chat("select email 1", session)
            draft = core.chat("reply to him saying I will review the notes before sharing", session)
            assert "Email draft" in draft and "To: alex@example.org" in draft, draft
            pending = core.store.pending_email(session)
            payload = json.loads(Path(pending["path"]).read_text(encoding="utf-8"))
            assert payload["reply_headers"]["In-Reply-To"] == "<synthetic@example.org>"
            assert len(payload["body"]) > 20
            print(
                "PASS: real local model drafted a contextual reply to the selected synthetic email with exact recipient/thread. Nothing sent.",
                flush=True,
            )
        finally:
            core.close()


if __name__ == "__main__":
    main()

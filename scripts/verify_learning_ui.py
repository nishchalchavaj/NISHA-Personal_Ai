"""Exercise local import and external-task approval dialogs without network calls."""

import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory

os.environ["QT_QPA_PLATFORM"] = "offscreen"

import httpx
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication, QDialog, QDialogButtonBox, QLineEdit, QTextEdit

from nisha.core import NishaCore
from nisha.settings import load_settings
from nisha.ui.app import NishaWindow


class Gateway:
    def close(self):
        pass


def wait_for_jobs(app, window):
    loop = QEventLoop()
    timer = QTimer()
    timer.setInterval(20)
    timer.timeout.connect(lambda: loop.quit() if not window.background_jobs else None)
    timer.start()
    QTimer.singleShot(5000, loop.quit)
    loop.exec()
    timer.stop()
    app.processEvents()
    assert not window.background_jobs


def main():
    settings = load_settings()
    with TemporaryDirectory(prefix="learning-ui-", dir=settings.data_dir) as directory:
        core = NishaCore(
            settings.model_copy(
                update={"data_dir": Path(directory), "external_tasks_enabled": True}
            ),
            Gateway(),
        )
        app = QApplication([])
        # The offscreen Qt backend does not discover Windows system fonts reliably.
        font = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / "segoeui.ttf"
        if font.is_file():
            font_id = QFontDatabase.addApplicationFont(str(font))
            families = QFontDatabase.applicationFontFamilies(font_id)
            if families:
                app.setFont(QFont(families[0], 10))
        window = NishaWindow(core, start_listener=False)
        window.show()
        app.processEvents()

        def save_learning():
            dialog = app.activeModalWidget()
            assert isinstance(dialog, QDialog)
            dialog.findChild(QTextEdit).setPlainText("The Zephyr prototype uses a 48 volt motor.")
            dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.Save).click()

        QTimer.singleShot(100, save_learning)
        window.learning_dialog()
        wait_for_jobs(app, window)
        assert "48 volt" in core.knowledge.search("Zephyr motor")[0]["text"]

        def cancel_setup():
            dialog = app.activeModalWidget()
            assert any(
                field.echoMode() == QLineEdit.Password for field in dialog.findChildren(QLineEdit)
            )
            dialog.reject()

        QTimer.singleShot(100, cancel_setup)
        window.setup_worker()
        assert not core.workers.profile.exists()
        core.workers.profile.write_text(
            json.dumps({"provider": "OpenAI", "model": "synthetic-model"})
        )
        core.workers.key_reader = lambda provider: "synthetic-key"
        core.memory.remember("Synthetic private profile: private-test-token")
        sent = []

        def handler(request):
            sent.append(json.loads(request.content))
            return httpx.Response(
                200,
                json={
                    "status": "completed",
                    "output": [
                        {
                            "type": "message",
                            "content": [
                                {
                                    "type": "output_text",
                                    "text": "Merge sort splits and merges arrays.",
                                }
                            ],
                        }
                    ],
                },
            )

        core.workers.client = httpx.Client(transport=httpx.MockTransport(handler))

        def approve_exact():
            dialog = app.activeModalWidget()
            exact = dialog.findChild(QTextEdit)
            assert exact.isReadOnly() and exact.toPlainText() == "Explain merge sort"
            assert not sent
            dialog.accept()

        def fill_task():
            dialog = app.activeModalWidget()
            dialog.findChild(QTextEdit).setPlainText("Explain merge sort")
            assert not sent
            QTimer.singleShot(100, approve_exact)
            dialog.accept()

        QTimer.singleShot(100, fill_task)
        window.external_task_dialog()
        wait_for_jobs(app, window)
        assert len(sent) == 1 and sent[0]["input"] == "Explain merge sort"
        assert "private-test-token" not in str(sent)
        assert not core.knowledge.search("merge sort")
        from nisha.ui.reinforcement_dialog import ReinforcementDialog

        review = ReinforcementDialog(core, window.session, window)
        review.show()
        app.processEvents()
        assert len(review.rows) == 1 and not review.rows[0]["reviewed"]
        review.items.setCurrentRow(0)
        assert "Merge sort" in review.preview.toPlainText()
        review.accept_selected()
        review.items.setCurrentRow(0)
        assert (
            core.knowledge.search("merge sort")[0]["kind"]
            == "reviewed_external_model_output_unverified"
        )
        core.reinforcement.propose_teacher(
            "Synthetic teacher", "Hello", "Hey! Good to hear from you."
        )
        review.refresh()
        review.items.setCurrentRow(0)
        review.use_as.setCurrentIndex(review.use_as.findData("warm"))
        review.accept_selected()
        review.items.setCurrentRow(0)
        assert core.reinforcement.conversation_examples("Hello", ("social_greeting", "warm"))
        assert not core.knowledge.search("Hello")
        report = settings.data_dir / "reports" / "reinforcement-learning-ui.png"
        report.parent.mkdir(parents=True, exist_ok=True)
        app.processEvents()
        assert review.grab().save(str(report))
        review.close()
        assert "Merge sort" in core.store.history(window.session)[1][-1]["content"]
        window.close()
        app.processEvents()
        core.workers.client.close()
        core.close()
    print(
        "PASS: local learning dialog, masked worker key, exact task approval, isolated payload, teacher review and local retrieval. No external request made."
    )


if __name__ == "__main__":
    main()

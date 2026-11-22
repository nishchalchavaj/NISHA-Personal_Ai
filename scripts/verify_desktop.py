"""Render and exercise Qt without opening a visible window or microphone."""

import os
from pathlib import Path
from tempfile import TemporaryDirectory

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtCore import QEventLoop, Qt, QTimer
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication, QDialog, QDialogButtonBox, QLineEdit, QTextEdit, QWidget

from nisha.core import NishaCore
from nisha.settings import load_settings
from nisha.ui.app import NishaWindow


class PreviewGateway:
    def stream(self, alias, messages):
        yield "Hello Nishchal. NISHA is ready for a local conversation."

    def close(self):
        pass


def main():
    settings = load_settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    output = settings.data_dir / "desktop-preview.png"
    with TemporaryDirectory(prefix="desktop-test-", dir=settings.data_dir) as directory:
        root = Path(directory).resolve()
        assert root.is_relative_to(settings.data_dir.resolve())
        core = NishaCore(settings.model_copy(update={"data_dir": root}), PreviewGateway())
        app = QApplication([])
        # The offscreen Qt backend on Windows does not discover system fonts automatically.
        QFontDatabase.addApplicationFont("C:/Windows/Fonts/segoeui.ttf")
        app.setFont(QFont("Segoe UI", 10))
        window = NishaWindow(core, start_listener=False)
        window.show()
        app.processEvents()
        window.input.setText("Hello")
        window.submit()
        loop = QEventLoop()
        window.worker.finished.connect(loop.quit)
        QTimer.singleShot(5000, loop.quit)
        loop.exec()
        app.processEvents()
        assert not window.worker.isRunning()
        assert (
            window.current_reply
            and window.current_reply in window.wall_widget.conversation_label.text()
        )
        assert not window.visual_panel.isVisible()
        assert not window.wall_widget.content_label.text()
        assert window.input.isEnabled()
        assert window.wall_widget.orb.frames
        assert window.wall_widget.orb.pixmap().hasAlphaChannel()
        assert window.testAttribute(Qt.WA_TranslucentBackground)
        assert window.windowFlags() & Qt.FramelessWindowHint
        assert window.wall_widget.orb.state == "idle"
        assert window.input.geometry().bottom() < window.wall_widget.height()
        window.toggle_display_mode()
        app.processEvents()
        assert window.stack.currentWidget() is window.table_widget
        window.toggle_output_mode()
        app.processEvents()
        assert window.output_mode == "projector"
        window.toggle_output_mode()
        window.toggle_display_mode()
        window.resize(1824, 1026)
        app.processEvents()
        # Let the transparent child widgets repaint after switching layouts.
        for widget in window.wall_widget.findChildren(QWidget):
            widget.update()
        QTimer.singleShot(150, loop.quit)
        loop.exec()
        window.grab().save(str(output))
        window.input.setText("/use local_smart")
        session = window.session
        window.submit()
        assert window.alias == "local_smart"
        assert window.session == session
        window.input.setText("/remember ui_preference=original transparent dashboard")
        window.submit()
        assert "Saved" in window.wall_widget.conversation_label.text()
        assert not window.visual_panel.isVisible()
        window.toggle_mute()
        assert window.muted and window.wall_widget.mic_label.muted
        assert window.wall_widget.mic_label.isEnabled()

        def cancel_setup():
            dialog = app.activeModalWidget()
            assert isinstance(dialog, QDialog)
            fields = dialog.findChildren(QLineEdit)
            assert any(field.echoMode() == QLineEdit.Password for field in fields)
            dialog.reject()

        QTimer.singleShot(100, cancel_setup)
        window.setup_gmail()
        assert not core.workflows.mailer.account_file.exists()

        sent = []

        class FakeGmail:
            def send_email(self, recipient, subject, body):
                sent.append((recipient, subject, body))
                return "Gmail accepted the approved email for delivery."

        core.workflows.mailer = FakeGmail()
        core.workflows.draft_email(
            session, "test@example.com", "Synthetic check", "Local draft", core.store
        )
        window.render()
        assert window.wall_widget.email_button.isVisible()

        def approve_review():
            dialog = app.activeModalWidget()
            assert isinstance(dialog, QDialog)
            assert dialog.findChild(QTextEdit).toPlainText() == "Local draft"
            buttons = dialog.findChild(QDialogButtonBox)
            buttons.button(QDialogButtonBox.Ok).click()

        assert not sent
        QTimer.singleShot(100, approve_review)
        window.review_email()
        loop = QEventLoop()
        window.worker.finished.connect(loop.quit)
        QTimer.singleShot(5000, loop.quit)
        loop.exec()
        app.processEvents()
        assert sent == [("test@example.com", "Synthetic check", "Local draft")]
        assert not window.wall_widget.email_button.isVisible()
        window.close()
        restored = NishaWindow(core, start_listener=False)
        assert restored.session != session
        assert not restored.wall_widget.conversation_label.text()
        restored.new_conversation()
        assert restored.session != session
        assert not restored.wall_widget.conversation_label.text()
        restored.close()
        core.close()
    print(
        f"PASS: transparent dashboard, local submission, commands, layouts and orb. Preview: {output}"
    )


if __name__ == "__main__":
    main()

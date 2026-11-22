"""Untrusted text stays text; native rich-text rendering cannot load resources."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QTextDocument
from PySide6.QtWidgets import QMessageBox, QTextEdit


class PassiveDocument(QTextDocument):
    def loadResource(self, resource_type, name):
        return None


class PlainTextEdit(QTextEdit):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setDocument(PassiveDocument(self))
        self.setAcceptRichText(False)

    def setText(self, text):
        self.setPlainText(text)

    def setHtml(self, text):
        self.setPlainText(text)

    def setMarkdown(self, text, *args):
        self.setPlainText(text)


def plain_warning(parent, title, text):
    dialog = QMessageBox(QMessageBox.Warning, title, "", QMessageBox.Ok, parent)
    dialog.setTextFormat(Qt.PlainText)
    dialog.setText(str(text))
    return dialog.exec()

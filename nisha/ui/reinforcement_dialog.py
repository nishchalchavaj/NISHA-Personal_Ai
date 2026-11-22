"""Local feedback and explicit review of teacher answers."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPushButton,
    QVBoxLayout,
)

from nisha.ui.text_security import PlainTextEdit, plain_warning


class ReinforcementDialog(QDialog):
    def __init__(self, core, session, parent=None):
        super().__init__(parent)
        self.core, self.session = core, session
        self.service = core.reinforcement
        self.setWindowTitle("NISHA · Response learning and teacher answers")
        self.resize(760, 800)
        layout = QVBoxLayout(self)
        self.status = QLabel()
        self.status.setTextFormat(Qt.PlainText)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.enabled = QCheckBox("Learn reply presentation from my ratings locally")
        self.enabled.setChecked(self.service.enabled())
        self.enabled.toggled.connect(self.toggle)
        layout.addWidget(self.enabled)
        actions = QHBoxLayout()
        for title, callback in (
            ("Last answer was helpful", lambda: self.rate(1)),
            ("Last answer was unhelpful", lambda: self.rate(0)),
            ("Reset response ratings", self.reset),
        ):
            button = QPushButton(title)
            button.clicked.connect(callback)
            actions.addWidget(button)
        layout.addLayout(actions)
        note = QLabel(
            "Review model answers as reference knowledge or natural conversation examples. "
            "They remain unverified; they cannot grant permissions or change personal memories. "
            "Paste an answer below, or review results from separately approved external tasks."
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        self.items = QListWidget()
        self.items.currentRowChanged.connect(self.preview_selected)
        layout.addWidget(self.items)
        self.preview = PlainTextEdit()
        self.preview.setReadOnly(True)
        layout.addWidget(self.preview)
        self.use_as = QComboBox()
        self.use_as.addItem("Use selected answer as reference knowledge", None)
        self.use_as.addItem("Conversation example: warm and direct", "warm")
        self.use_as.addItem("Conversation example: reflect what I said", "reflective")
        self.use_as.addItem("Conversation example: gentle follow-up", "curious")
        layout.addWidget(self.use_as)
        reviews = QHBoxLayout()
        for title, callback in (
            ("Accept selected reviewed answer", self.accept_selected),
            ("Forget selected teacher answer", self.forget_selected),
        ):
            button = QPushButton(title)
            button.clicked.connect(callback)
            reviews.addWidget(button)
        layout.addLayout(reviews)
        self.provider = QLineEdit()
        self.provider.setPlaceholderText("Source model, for example Gemini or a local model")
        layout.addWidget(self.provider)
        self.prompt = PlainTextEdit()
        self.prompt.setPlaceholderText(
            "Exact question, or one casual user message given to the other model"
        )
        self.prompt.setMaximumHeight(80)
        layout.addWidget(self.prompt)
        self.answer = PlainTextEdit()
        self.answer.setPlaceholderText("Paste the answer here; this makes no network request")
        layout.addWidget(self.answer)
        self.compare = QCheckBox("I prefer this answer to NISHA's last answer to the same question")
        self.compare.toggled.connect(self.set_comparison)
        layout.addWidget(self.compare)
        save = QPushButton("Add pasted answer to review queue")
        save.clicked.connect(self.add_teacher)
        layout.addWidget(save)
        export = QPushButton("Export reviewed preference pairs locally (JSONL)")
        export.clicked.connect(self.export)
        layout.addWidget(export)
        close = QDialogButtonBox(QDialogButtonBox.Close)
        close.rejected.connect(self.reject)
        layout.addWidget(close)
        self.refresh()

    def refresh(self):
        self.status.setText(self.service.status())
        self.rows = self.service.teachers()
        self.items.clear()
        for row in self.rows:
            self.items.addItem(
                f"{'Reviewed' if row['reviewed'] else 'Pending'} · {row['provider']} · {row['prompt'][:80]}"
            )

    def selected(self):
        index = self.items.currentRow()
        return self.rows[index] if 0 <= index < len(self.rows) else None

    def preview_selected(self):
        row = self.selected()
        if row and row["reviewed"]:
            self.use_as.setCurrentIndex(self.use_as.findData(row["conversation_style"]))
        elif hasattr(self, "use_as"):
            self.use_as.setCurrentIndex(0)
        self.preview.setPlainText(
            (
                "NISHA's original answer:\n"
                + self.service.compared_answer(row["decision_id"])
                + "\n\nPreferred teacher answer:\n"
                if row and row["decision_id"]
                else ""
            )
            + (row["prompt"] + "\n\n" + row["answer"] if row else "")
        )

    def toggle(self, enabled):
        self.service.set_enabled(enabled)
        self.status.setText(self.service.status())

    def rate(self, reward):
        self.status.setText(self.service.feedback(self.session, reward))

    def reset(self):
        self.service.reset()
        self.refresh()

    def set_comparison(self, checked):
        decision = self.service.latest(self.session) if checked else None
        if checked and decision:
            self.prompt.setPlainText(decision["prompt"])
            self.preview.setPlainText("NISHA's original answer:\n" + decision["answer"])
        elif checked:
            self.compare.setChecked(False)
            self.status.setText("No eligible answer in this conversation to compare.")

    def add_teacher(self):
        try:
            decision = self.service.latest(self.session) if self.compare.isChecked() else None
            if self.compare.isChecked() and not decision:
                raise ValueError("The answer to compare is no longer available.")
            self.service.propose_teacher(
                self.provider.text(),
                self.prompt.toPlainText(),
                self.answer.toPlainText(),
                decision["id"] if decision else None,
            )
            self.answer.clear()
            self.compare.setChecked(False)
            self.refresh()
        except ValueError as exc:
            plain_warning(self, "Check teacher example", str(exc))

    def accept_selected(self):
        row = self.selected()
        if row:
            try:
                self.service.accept_teacher(row["id"], self.use_as.currentData())
                self.refresh()
            except ValueError as exc:
                plain_warning(self, "Check conversation example", str(exc))

    def forget_selected(self):
        row = self.selected()
        if row:
            self.service.forget_teacher(row["id"])
            self.refresh()

    def export(self):
        if not self.service.preference_pairs():
            self.status.setText("No reviewed preferred comparisons to export yet.")
            return
        path = self.service.export_pairs(self.core.settings.data_dir / "learning_exports")
        self.status.setText("Saved locally: " + str(path))

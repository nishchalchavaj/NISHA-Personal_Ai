"""Local connection setup without changing the original dashboard."""

import json
from pathlib import Path
from typing import ClassVar

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from nisha.connections import EXAMPLE, ConnectionsConfig, Project, endpoint
from nisha.errors import NishaError
from nisha.ui.text_security import PlainTextEdit, plain_warning


class RoutineEditor(QWidget):
    ACTIONS: ClassVar = [
        ("Open folder", "open_folder"), ("Open document", "open_file"),
        ("Open app", "open_app"), ("Open website", "open_website"),
        ("Open local path", "open_path"),
        ("Open URL in Chrome", "open_chrome_url"),
        ("Search in Chrome", "search_chrome"),
        ("Turn device on", "device_on"), ("Turn device off", "device_off"),
    ]
    TARGET_HINTS: ClassVar = {
        "open_folder": "Enter an absolute folder path, for example E:\\Study.",
        "open_file": "Enter an absolute document path, for example E:\\Study\\notes.pdf.",
        "open_app": "Enter an app name, for example chrome or notepad. No .exe path is needed.",
        "open_path": "Enter an absolute path to a folder, file, shortcut or program. Quoted paths are accepted.",
        "open_website": "Enter a full website address beginning with https://.",
        "open_chrome_url": "Enter the page address beginning with https://. Chrome is launched automatically.",
        "search_chrome": "Enter the words to search for. Chrome is launched automatically.",
        "device_on": "Enter a configured device ID from Advanced JSON.",
        "device_off": "Enter a configured device ID from Advanced JSON.",
    }

    def __init__(self, routines):
        super().__init__()
        self.routines = [r.model_dump() for r in routines]
        self.dirty = False
        self.index = -1
        layout = QVBoxLayout(self)
        row = QHBoxLayout()
        self.selector = QComboBox()
        self.selector.currentIndexChanged.connect(self.select_routine)
        row.addWidget(self.selector)
        add = QPushButton("New routine")
        add.clicked.connect(self.add_routine)
        row.addWidget(add)
        delete = QPushButton("Delete routine")
        delete.clicked.connect(self.delete_routine)
        row.addWidget(delete)
        layout.addLayout(row)
        form = QFormLayout()
        self.name = QLineEdit()
        self.trigger = QLineEdit()
        self.trigger.setPlaceholderText("Get ready for College studies")
        self.name.textChanged.connect(self.changed)
        self.name.textChanged.connect(self.update_selector_name)
        self.trigger.textChanged.connect(self.changed)
        form.addRow("Routine name", self.name)
        form.addRow("Exact command to say or type", self.trigger)
        layout.addLayout(form)
        layout.addWidget(QLabel("Steps run left to right. Add up to 12; execution stops if a step fails."))
        self.steps = QTabWidget()
        layout.addWidget(self.steps)
        controls = QHBoxLayout()
        for label, callback in [
            ("Add step", self.add_step), ("Remove step", self.remove_step),
            ("Move earlier", lambda: self.move_step(-1)),
            ("Move later", lambda: self.move_step(1)),
        ]:
            button = QPushButton(label)
            button.clicked.connect(callback)
            controls.addWidget(button)
        layout.addLayout(controls)
        self.refresh_selector()
        self.select_routine(self.selector.currentIndex())

    def changed(self, *_):
        if self.index >= 0:
            self.dirty = True

    def update_selector_name(self, value):
        if self.index >= 0:
            self.selector.setItemText(self.index, value.strip() or "Untitled routine")

    def save_current(self):
        if self.index < 0 or self.index >= len(self.routines):
            return
        item = self.routines[self.index]
        item["name"] = self.name.text().strip()
        item["trigger"] = self.trigger.text().strip()
        item["steps"] = [
            {"action": self.steps.widget(i).findChild(QComboBox).currentData(),
             "target": self.steps.widget(i).findChild(QLineEdit).text().strip()}
            for i in range(self.steps.count())
        ]

    def refresh_selector(self):
        self.selector.blockSignals(True)
        self.selector.clear()
        self.selector.addItems([r["name"] or "Untitled routine" for r in self.routines])
        self.selector.blockSignals(False)

    def select_routine(self, index):
        self.save_current()
        self.index = index
        self.name.blockSignals(True)
        self.trigger.blockSignals(True)
        self.name.setText(self.routines[index]["name"] if index >= 0 else "")
        self.trigger.setText(self.routines[index].get("trigger", "") if index >= 0 else "")
        self.name.blockSignals(False)
        self.trigger.blockSignals(False)
        self.render_steps()

    def render_steps(self):
        self.steps.clear()
        if self.index < 0:
            return
        for position, step in enumerate(self.routines[self.index]["steps"], 1):
            page = QWidget()
            form = QFormLayout(page)
            action = QComboBox()
            for label, value in self.ACTIONS:
                action.addItem(label, value)
            action.setCurrentIndex(max(0, action.findData(step["action"])))
            target = QLineEdit(step["target"])
            hint = QLabel()
            hint.setWordWrap(True)
            def update_hint(*_, selected=action, field=target, label=hint):
                message = self.TARGET_HINTS[selected.currentData()]
                field.setPlaceholderText(message)
                label.setText(message)
            update_hint()
            action.currentIndexChanged.connect(update_hint)
            action.currentIndexChanged.connect(self.changed)
            target.textChanged.connect(self.changed)
            form.addRow("Activity", action)
            form.addRow("Target", target)
            form.addRow("", hint)
            self.steps.addTab(page, f"Step {position}")

    def add_routine(self):
        self.save_current()
        self.routines.append({"name": "New routine", "trigger": "", "aliases": [],
                              "steps": [{"action": "open_chrome_url", "target": ""}]})
        self.dirty = True
        self.index = -1
        self.refresh_selector()
        self.selector.setCurrentIndex(len(self.routines) - 1)
        self.select_routine(self.selector.currentIndex())

    def delete_routine(self):
        if self.index < 0:
            return
        self.routines.pop(self.index)
        self.dirty = True
        self.index = -1
        self.refresh_selector()
        self.selector.setCurrentIndex(0 if self.routines else -1)
        self.select_routine(self.selector.currentIndex())

    def add_step(self):
        if self.index < 0 or self.steps.count() >= 12:
            return
        self.save_current()
        self.routines[self.index]["steps"].append({"action": "open_chrome_url", "target": ""})
        self.dirty = True
        self.render_steps()
        self.steps.setCurrentIndex(self.steps.count() - 1)

    def remove_step(self):
        if self.index < 0 or self.steps.count() <= 1:
            return
        self.save_current()
        position = self.steps.currentIndex()
        self.routines[self.index]["steps"].pop(position)
        self.dirty = True
        self.render_steps()
        self.steps.setCurrentIndex(min(position, self.steps.count() - 1))

    def move_step(self, offset):
        if self.index < 0:
            return
        self.save_current()
        position = self.steps.currentIndex()
        destination = position + offset
        if destination < 0 or destination >= self.steps.count():
            return
        steps = self.routines[self.index]["steps"]
        steps[position], steps[destination] = steps[destination], steps[position]
        self.dirty = True
        self.render_steps()
        self.steps.setCurrentIndex(destination)

    def validation_issue(self):
        self.save_current()
        for routine_index, routine in enumerate(self.routines):
            if not routine["name"].strip():
                self.selector.setCurrentIndex(routine_index)
                self.name.setFocus()
                return "Enter a routine name."
            if not routine["steps"]:
                self.selector.setCurrentIndex(routine_index)
                return f"Add at least one step to '{routine['name']}'."
            for step_index, step in enumerate(routine["steps"]):
                action, target = step["action"], step["target"].strip()
                issue = None
                if not target:
                    issue = "Enter a target for this activity."
                elif action in {"open_website", "open_chrome_url"}:
                    try:
                        endpoint(target)
                    except ValueError:
                        issue = (
                            "This is a program path. Choose 'Open app' and enter chrome, "
                            "or keep 'Open URL in Chrome' and enter a https:// page address."
                            if target.casefold().strip('"').endswith("chrome.exe")
                            else "Enter a full HTTP or HTTPS URL, for example https://www.youtube.com/."
                        )
                elif action == "search_chrome" and (len(target) > 200 or any(c in target for c in "\r\n\x00")):
                    issue = "Enter search words under 200 characters on one line."
                elif action == "open_path":
                    unquoted = target[1:-1] if len(target) >= 2 and target[0] == target[-1] == '"' else target
                    if not Path(unquoted).is_absolute():
                        issue = "Enter an absolute local path, for example C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe."
                if issue:
                    self.selector.setCurrentIndex(routine_index)
                    self.steps.setCurrentIndex(step_index)
                    self.steps.widget(step_index).findChild(QLineEdit).setFocus()
                    return f"{routine['name']} · Step {step_index + 1}: {issue}"
        return None


class ConnectionsDialog(QDialog):
    def __init__(self, connections, parent=None):
        super().__init__(parent)
        self.connections = connections
        self.setWindowTitle("NISHA · Devices, projects and routines")
        self.resize(780, 650)
        layout = QVBoxLayout(self)
        tabs = QTabWidget()
        self.tabs = tabs
        layout.addWidget(tabs)
        try:
            config = connections.load()
        except NishaError:
            config = ConnectionsConfig()
        self.original_project = next(
            (p for p in config.projects if p.name == config.default_project), None
        )
        project = QWidget()
        form = QFormLayout(project)
        self.name, self.folder, self.budget = QLineEdit(), QLineEdit(), QLineEdit()
        self.requirements, self.query = PlainTextEdit(), QLineEdit()
        self.presentation, self.support = QLineEdit(), PlainTextEdit()
        self.requirements.setMaximumHeight(100)
        self.support.setMaximumHeight(85)
        self.name.setPlaceholderText("Project name")
        self.folder.setPlaceholderText("Choose your project folder")
        self.query.setPlaceholderText("Only this exact public query is sent to web search")
        form.addRow("Default project", self.name)
        folder_row = QHBoxLayout()
        folder_row.addWidget(self.folder)
        browse = QPushButton("Choose folder")
        browse.clicked.connect(self.choose_folder)
        folder_row.addWidget(browse)
        form.addRow("Folder", folder_row)
        form.addRow("Requirements", self.requirements)
        form.addRow("Budget", self.budget)
        form.addRow("Public research query", self.query)
        deck_row = QHBoxLayout()
        deck_row.addWidget(self.presentation)
        deck = QPushButton("Choose presentation")
        deck.clicked.connect(self.choose_deck)
        deck_row.addWidget(deck)
        form.addRow("Presentation", deck_row)
        form.addRow("Supporting files\n(one relative path per line)", self.support)
        if self.original_project:
            p = self.original_project
            self.name.setText(p.name)
            self.folder.setText(p.folder)
            self.requirements.setPlainText(p.requirements)
            self.budget.setText(p.budget)
            self.query.setText(p.public_research_query)
            self.presentation.setText(p.presentation)
            self.support.setPlainText("\n".join(p.supporting_files))
        self.initial_project = self.project_values()
        tabs.addTab(project, "Project")
        self.routine_editor = RoutineEditor(config.routines)
        tabs.addTab(self.routine_editor, "Routines")
        advanced = QWidget()
        advanced_layout = QVBoxLayout(advanced)
        note = QLabel(
            "Configure direct HTTP devices, HTTP snapshots/RTSP cameras, named projects, saved routine steps and a SearXNG JSON search URL. Endpoints must match your device's API. Credentials belong in the Credentials tab. Example addresses are placeholders."
        )
        note.setWordWrap(True)
        advanced_layout.addWidget(note)
        self.editor = PlainTextEdit()
        raw = (
            connections.path.read_text(encoding="utf-8")
            if connections.path.exists()
            else config.model_dump_json(indent=2)
        )
        self.editor.setPlainText(raw)
        advanced_layout.addWidget(self.editor)
        example = QPushButton("View configuration example")
        example.clicked.connect(self.show_example)
        advanced_layout.addWidget(example)
        tabs.addTab(advanced, "Advanced JSON")
        credentials = QWidget()
        credentials_layout = QVBoxLayout(credentials)
        note = QLabel(
            "Device passwords/tokens are stored in Windows Credential Manager. Save the device configuration first, then enter credentials for its ID. They are never attached to model requests."
        )
        note.setWordWrap(True)
        credentials_layout.addWidget(note)
        fields = QFormLayout()
        self.device_id, self.username, self.secret = QComboBox(), QLineEdit(), QLineEdit()
        self.secret.setEchoMode(QLineEdit.Password)
        self.device_id.setEditable(True)
        self.device_id.addItems([d.id for d in config.devices])
        fields.addRow("Device ID", self.device_id)
        fields.addRow("Username (basic/digest)", self.username)
        fields.addRow("Password or bearer token", self.secret)
        credentials_layout.addLayout(fields)
        save_secret = QPushButton("Save this device credential")
        save_secret.clicked.connect(self.save_secret)
        credentials_layout.addWidget(save_secret)
        credentials_layout.addStretch()
        tabs.addTab(credentials, "Credentials")
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.finished.connect(lambda *_: self.secret.clear())

    def project_values(self):
        return {
            "name": self.name.text().strip(),
            "folder": self.folder.text().strip(),
            "requirements": self.requirements.toPlainText(),
            "budget": self.budget.text().strip(),
            "public_research_query": self.query.text().strip(),
            "presentation": self.presentation.text().strip(),
            "supporting_files": [
                line.strip() for line in self.support.toPlainText().splitlines() if line.strip()
            ],
        }

    def choose_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Project folder", self.folder.text())
        if folder:
            self.folder.setText(folder)

    def choose_deck(self):
        filename, _ = QFileDialog.getOpenFileName(
            self, "Presentation", self.folder.text(), "PowerPoint (*.pptx)"
        )
        if filename:
            path, folder = Path(filename).resolve(), Path(self.folder.text()).resolve()
            if not path.is_relative_to(folder):
                plain_warning(
                    self, "Presentation", "Choose a presentation inside your project folder."
                )
                return
            self.presentation.setText(str(path.relative_to(folder)))

    def show_example(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Example only · replace with your device API and folder")
        dialog.resize(700, 550)
        layout = QVBoxLayout(dialog)
        text = PlainTextEdit()
        text.setPlainText(json.dumps(EXAMPLE, indent=2))
        text.setReadOnly(True)
        layout.addWidget(text)
        close = QDialogButtonBox(QDialogButtonBox.Close)
        close.rejected.connect(dialog.reject)
        layout.addWidget(close)
        dialog.exec()

    def save(self):
        try:
            try:
                config = ConnectionsConfig.model_validate_json(self.editor.toPlainText())
            except ValueError:
                raise NishaError(
                    "Check the configuration JSON and fields. Use the example to see supported settings."
                ) from None
            values = self.project_values()
            if values != self.initial_project:
                try:
                    project = Project(**values)
                except ValueError:
                    raise NishaError(
                        "Enter a project name, absolute folder and paths inside that folder."
                    ) from None
                if self.original_project:
                    config.projects = [
                        p for p in config.projects if p.name != self.original_project.name
                    ]
                    project.aliases = self.original_project.aliases
                config.projects.append(project)
                config.default_project = project.name
            if self.routine_editor.dirty:
                issue = self.routine_editor.validation_issue()
                if issue:
                    self.tabs.setCurrentWidget(self.routine_editor)
                    raise NishaError(issue)
                config.routines = self.routine_editor.routines
            self.connections.save(config.model_dump_json())
            self.accept()
        except (NishaError, OSError) as exc:
            plain_warning(
                self,
                "Configuration",
                str(exc)
                if isinstance(exc, NishaError)
                else "The local configuration couldn't be written.",
            )

    def save_secret(self):
        try:
            self.connections.save_credential(
                self.device_id.currentText().strip(), self.username.text(), self.secret.text()
            )
            self.secret.clear()
            QMessageBox.information(self, "Credentials", "Device credential saved locally.")
        except NishaError as exc:
            plain_warning(self, "Credentials", str(exc))

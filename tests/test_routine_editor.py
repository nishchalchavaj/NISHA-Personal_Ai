import pytest


@pytest.fixture
def editor(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    from nisha.ui.connections_dialog import RoutineEditor

    widget = RoutineEditor([])
    yield widget
    widget.close()
    del app


def test_incomplete_first_step_is_identified(editor):
    from PySide6.QtWidgets import QLineEdit

    editor.add_routine()
    editor.steps.widget(0).findChild(QLineEdit).setText("https://example.com/one")
    editor.add_step()
    editor.steps.widget(1).findChild(QLineEdit).setText("https://www.youtube.com/shorts")
    editor.steps.widget(0).findChild(QLineEdit).clear()

    assert "Step 1" in editor.validation_issue()
    assert editor.steps.currentIndex() == 0


def test_valid_saved_urls_have_no_editor_issue(editor):
    from PySide6.QtWidgets import QLineEdit

    editor.add_routine()
    editor.steps.widget(0).findChild(QLineEdit).setText("https://example.com/one")
    editor.add_step()
    editor.steps.widget(1).findChild(QLineEdit).setText("https://www.youtube.com/shorts")

    assert editor.validation_issue() is None


def test_chrome_executable_is_explained_as_wrong_target(editor):
    from PySide6.QtWidgets import QLineEdit

    editor.add_routine()
    editor.steps.widget(0).findChild(QLineEdit).setText(
        '"C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe"'
    )
    issue = editor.validation_issue()
    assert "Choose 'Open app' and enter chrome" in issue


def test_quoted_executable_can_be_saved_as_local_path(editor):
    from PySide6.QtWidgets import QComboBox, QLineEdit

    editor.add_routine()
    page = editor.steps.widget(0)
    action = page.findChild(QComboBox)
    action.setCurrentIndex(action.findData("open_path"))
    page.findChild(QLineEdit).setText(
        '"C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe"'
    )
    assert editor.validation_issue() is None

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication

from nisha.ui.app import NishaWindow
from nisha.ui.voice_dialog import VoiceDialog


@pytest.fixture
def dialog(core, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    window = NishaWindow(core, start_listener=False)
    dialog = VoiceDialog(window)
    yield dialog
    dialog.reject()
    window.close()
    app.processEvents()


def test_voice_take_is_not_persisted_until_reviewed_save(dialog):
    t = np.arange(16000) / 16000
    audio = (np.sin(2 * np.pi * 440 * t) * 0.1).astype(np.float32)
    dialog.recorded((audio, "Hey NISHA", "wake", "USB"))
    assert not dialog.profile.entries()
    dialog.save_sample()
    assert dialog.profile.entries()[0]["text"] == "Hey NISHA"
    assert dialog.recording is None


def test_voice_take_type_cannot_be_changed_after_recording(dialog):
    audio = np.full(16000, 0.1, dtype=np.float32)
    dialog.recorded((audio, "Hey NISHA", "wake", "USB"))
    dialog.kind.setCurrentIndex(2)
    dialog.save_sample()
    assert not dialog.profile.entries()
    assert "type changed" in dialog.status.text()

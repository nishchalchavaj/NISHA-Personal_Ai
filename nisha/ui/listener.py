"""Qt bridge for the hardware-independent local listener."""

from PySide6.QtCore import QThread, Signal

from nisha.listening import ListenerEngine


class ContinuousListener(QThread):
    command = Signal(str)
    state = Signal(str)
    wake = Signal()
    error = Signal(str)
    uncertain = Signal(str)
    dismissed = Signal()
    interrupted = Signal()
    quiet_requested = Signal()
    silent_requested = Signal()
    fresh_requested = Signal(str)
    opened = Signal()

    def __init__(self, settings, data_dir=None):
        super().__init__()
        self.engine = ListenerEngine(
            settings,
            self.command.emit,
            self.state.emit,
            self.wake.emit,
            self.error.emit,
            uncertain=self.uncertain.emit,
            dismiss=self.dismissed.emit,
            personal_model_path=data_dir / "voice-profile" / "wake-model.npz" if data_dir else None,
            interrupt=self.interrupted.emit,
            silence=self.quiet_requested.emit,
            silent=self.silent_requested.emit,
            fresh=self.fresh_requested.emit,
            opened=self.opened.emit,
        )

    def run(self):
        self.engine.run()

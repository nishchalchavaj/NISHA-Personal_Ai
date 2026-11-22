"""Deliberate voice enrollment; microphone work and training stay off the Qt thread."""

import logging

import numpy as np
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFormLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from nisha.errors import NishaError
from nisha.voice_profile import VoiceProfile, read_wav


class VoiceJob(QThread):
    result = Signal(object)
    error = Signal(str)
    progress = Signal(str)

    def __init__(self, operation, parent):
        super().__init__(parent)
        self.operation = operation

    def run(self):
        try:
            self.result.emit(self.operation(self))
        except (NishaError, OSError, ValueError) as exc:
            self.error.emit(str(exc))
        except Exception:
            logging.getLogger("nisha").exception("Voice enrollment operation failed")
            self.error.emit(
                "Voice recording or training failed. Check the local log and try another input."
            )


class VoiceDialog(QDialog):
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.profile = VoiceProfile(window.core.settings.data_dir)
        self.recording = None
        self.recorded_text = self.recorded_kind = ""
        self.job = None
        self.setWindowTitle("NISHA · Personal voice samples")
        self.resize(640, 460)
        layout = QVBoxLayout(self)
        note = QLabel(
            "Record your natural voice. Start with 20 wake takes (NISHA / Hey NISHA), 20 non-wake phrases, then varied commands. Only Save keeps a recording. Everything stays on this PC. Choose template or neural wake training; both are separate from Whisper speech recognition."
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        form = QFormLayout()
        self.kind = QComboBox()
        for label, value in [
            ("Wake phrase only", "wake"),
            ("Non-wake speech", "negative"),
            ("Command / conversation", "command"),
        ]:
            self.kind.addItem(label, value)
        self.text = QLineEdit("Hey NISHA")
        self.microphone = QComboBox()
        self.microphone.addItem("Windows default microphone", None)
        import sounddevice as sd

        for index, device in enumerate(sd.query_devices()):
            if (
                device["max_input_channels"]
                and sd.query_hostapis(device["hostapi"])["name"] == "MME"
                and "mapper" not in device["name"].casefold()
            ):
                self.microphone.addItem(device["name"], index)
        form.addRow("Sample type", self.kind)
        form.addRow("Exact words spoken", self.text)
        form.addRow("Microphone", self.microphone)
        self.duration = QComboBox()
        for seconds in [4, 8, 15, 30]:
            self.duration.addItem(f"{seconds} seconds", seconds)
        form.addRow("Recording length", self.duration)
        layout.addLayout(form)
        self.status = QLabel()
        self.status.setTextFormat(Qt.PlainText)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.record = QPushButton("Record 4 seconds")
        self.save = QPushButton("Save reviewed recording")
        self.import_button = QPushButton("Import a recorded WAV")
        self.play = QPushButton("Listen to this take")
        self.train = QPushButton("Train and test personal wake model")
        self.train_neural = QPushButton("Train and test neural wake model")
        self.close_button = QPushButton("Done")
        for button in [
            self.record,
            self.play,
            self.save,
            self.import_button,
            self.train,
            self.train_neural,
            self.close_button,
        ]:
            layout.addWidget(button)
        self.save.setEnabled(False)
        self.play.setEnabled(False)
        self.record.clicked.connect(self.record_sample)
        self.duration.currentIndexChanged.connect(
            lambda _: self.record.setText(f"Record {self.duration.currentData()} seconds")
        )
        self.play.clicked.connect(self.play_sample)
        self.save.clicked.connect(self.save_sample)
        self.import_button.clicked.connect(self.import_sample)
        self.train.clicked.connect(
            lambda: self.start_job(lambda _: self.profile.train(), self.trained)
        )
        self.train_neural.clicked.connect(
            lambda: self.start_job(lambda _: self.profile.train_neural(), self.trained)
        )
        self.close_button.clicked.connect(self.accept)
        self.refresh()

    def refresh(self, note=""):
        entries = self.profile.entries()
        counts = {
            kind: sum(e["kind"] == kind for e in entries)
            for kind in ["wake", "negative", "command"]
        }
        if self.profile.invalid_entries:
            note = (
                f"{self.profile.invalid_entries} damaged index entries were skipped. Original index and recordings are preserved.\n"
                + note
            )
        self.status.setText(
            f"Saved: {counts['wake']} wake, {counts['negative']} non-wake, {counts['command']} command samples.\n{note}"
        )

    def start_job(self, operation, completed):
        if self.job and self.job.isRunning():
            return
        for button in [self.record, self.play, self.save, self.import_button, self.train, self.train_neural]:
            button.setEnabled(False)
        self.job = VoiceJob(operation, self)
        self.window.background_jobs.append(self.job)
        self.job.result.connect(completed)
        self.job.progress.connect(self.refresh)
        self.job.error.connect(lambda text: self.refresh(text))
        self.job.finished.connect(self.job_finished)
        self.job.start()

    def job_finished(self):
        if self.job in self.window.background_jobs:
            self.window.background_jobs.remove(self.job)
        for button in [self.record, self.import_button, self.train, self.train_neural]:
            button.setEnabled(True)
        self.save.setEnabled(self.recording is not None)
        self.play.setEnabled(self.recording is not None)

    def record_sample(self):
        text, kind = self.text.text().strip(), self.kind.currentData()
        seconds = self.duration.currentData()
        if not text:
            self.refresh("Enter the exact words you will say first.")
            return
        settings = self.window.core.settings.voice.model_copy(
            update={"microphone": self.microphone.currentData(), "auto_microphone": False}
        )
        self.recording = None
        self.refresh(
            "Recording starts when the microphone is ready. Say the phrase once in your normal voice."
        )

        def capture(job):
            from nisha.microphones import AutoMicrophoneStream

            listener = self.window.listener
            if listener and not listener.engine.quiet.wait(3):
                raise NishaError("Background microphone is still closing. Try again.")
            stream = AutoMicrophoneStream(settings, should_stop=job.isInterruptionRequested)
            blocks = []
            try:
                with stream:
                    stream.read(1600)
                    stream.settings = settings.model_copy(
                        update={"microphone": stream.selected_index}
                    )
                    stream.pending.clear()
                    job.progress.emit(
                        f"Recording now from {stream.source_name} · say {text!r} once."
                    )
                    for _ in range(seconds * 10):
                        if job.isInterruptionRequested():
                            raise NishaError("Recording cancelled.")
                        block, overflow = stream.read(1600)
                        if overflow:
                            raise NishaError("Audio dropped. Please record again.")
                        blocks.append(block.reshape(-1))
                return np.concatenate(blocks), text, kind, stream.source_name
            finally:
                stream.close()

        self.start_job(capture, self.recorded)

    def recorded(self, result):
        self.recording, self.recorded_text, self.recorded_kind, self.source = result
        rms = float(np.sqrt(np.mean(self.recording * self.recording)))
        self.refresh(
            f"Take ready from {self.source}. Level {rms:.4f}. Listen, check the transcript, then Save. Nothing saved yet."
        )

    def play_sample(self):
        import io
        import wave

        from PySide6.QtCore import QBuffer, QByteArray, QIODevice
        from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer

        target = io.BytesIO()
        with wave.open(target, "wb") as wav:
            wav.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
            wav.writeframes((np.clip(self.recording, -1, 1) * 32767).astype("<i2").tobytes())
        if not hasattr(self, "player"):
            self.player = QMediaPlayer(self)
            self.output = QAudioOutput(self)
            self.player.setAudioOutput(self.output)
        self.player.stop()
        if hasattr(self, "play_buffer"):
            self.play_buffer.close()
            self.play_buffer.deleteLater()
        self.play_buffer = QBuffer(self)
        self.play_buffer.setData(QByteArray(target.getvalue()))
        self.play_buffer.open(QIODevice.ReadOnly)
        self.player.setSourceDevice(self.play_buffer)
        self.player.play()

    def save_sample(self):
        try:
            if self.kind.currentData() != self.recorded_kind:
                raise NishaError("The sample type changed. Record or import a new take.")
            self.profile.save(self.recording, self.text.text(), self.recorded_kind, self.source)
            self.recording = None
            self.save.setEnabled(False)
            self.play.setEnabled(False)
            self.refresh(
                "Saved locally. Record another take with a slightly different pace or distance."
            )
        except (NishaError, OSError) as exc:
            self.refresh(str(exc))

    def import_sample(self):
        from PySide6.QtWidgets import QFileDialog

        path, _ = QFileDialog.getOpenFileName(
            self, "Import your voice recording", "", "PCM WAV (*.wav)"
        )
        if not path:
            return
        try:
            self.recorded(
                (read_wav(path), self.text.text(), self.kind.currentData(), "imported WAV")
            )
            self.job_finished()
        except (NishaError, OSError, ValueError) as exc:
            self.refresh(str(exc))

    def trained(self, report):
        self.refresh(
            f"{report['type']} activated locally using {report.get('wake_samples', 0)} wake and {report.get('non_wake_samples', 0)} non-wake takes. Held-out wakes: {report['wake_test_hits']}/{report['wake_test_total']}; false wakes: {report['negative_test_false_alarms']}/{report['negative_test_total']}. Keep adding variations and retrain to include them. This does not retrain Whisper."
        )

    def done(self, result):
        if self.job and self.job.isRunning():
            self.job.requestInterruption()
            self.refresh("Finishing the recording or training. Press Done again when finished.")
            return
        if hasattr(self, "player"):
            self.player.stop()
        super().done(result)

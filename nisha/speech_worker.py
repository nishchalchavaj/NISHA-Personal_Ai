"""Bound local ASR inference so a stuck native decoder cannot hang the desktop."""

import logging
import multiprocessing
from time import monotonic

from nisha.errors import NishaError


class SpeechTimeout(NishaError):
    pass


def decode_worker(connection, settings):
    from nisha.voice import WhisperSpeech

    speech = WhisperSpeech(settings)
    try:
        speech.prepare()
        speech.warmup()
        connection.send(("ready", None))
        while True:
            request = connection.recv()
            if request is None:
                break
            text = (
                speech.transcribe(request["audio"], control_only=True)
                if isinstance(request, dict) and request.get("control_only")
                else speech.transcribe(request)
            )
            connection.send(
                (
                    "result",
                    (text, speech.last_uncertain, speech.last_wake_confident, speech.last_metrics),
                )
            )
    except (EOFError, BrokenPipeError):
        pass
    except Exception:
        logging.getLogger("nisha").exception("Isolated speech inference failed")
        try:
            connection.send(
                ("error", "Local speech inference failed. Check the cached model and GPU memory.")
            )
        except (EOFError, BrokenPipeError):
            pass
    finally:
        connection.close()


class BoundedSpeech:
    def __init__(self, settings, stopped=None, target=decode_worker):
        self.settings, self.stopped, self.target = settings, stopped, target
        self.process = self.connection = None
        self.model = None  # Compatible with the desktop's old listener cleanup.
        self.last_uncertain = False
        self.last_wake_confident = False
        self.last_metrics = {}

    def receive(self, timeout):
        deadline = monotonic() + timeout
        while monotonic() < deadline:
            if self.stopped and self.stopped.is_set():
                self.close()
                raise SpeechTimeout("Speech decoding was stopped.")
            if self.connection.poll(0.05):
                try:
                    kind, value = self.connection.recv()
                except EOFError as exc:
                    self.close()
                    raise SpeechTimeout("The local speech worker exited. It will restart.") from exc
                if kind == "error":
                    self.close()
                    raise SpeechTimeout(value)
                return kind, value
            if not self.process.is_alive():
                self.close()
                raise SpeechTimeout("The local speech worker exited. It will restart.")
        self.close()
        raise SpeechTimeout(
            "Speech decoding timed out. The local decoder will restart; please repeat."
        )

    def prepare(self):
        if self.process and self.process.is_alive():
            return
        self.close()
        context = multiprocessing.get_context("spawn")
        self.connection, child = context.Pipe()
        self.process = context.Process(target=self.target, args=(child, self.settings), daemon=True)
        self.process.start()
        child.close()
        kind, _ = self.receive(60)
        if kind != "ready":
            self.close()
            raise SpeechTimeout("The local speech worker did not become ready.")

    def transcribe(self, audio):
        return self._transcribe(audio)

    def transcribe_control(self, audio):
        return self._transcribe({"audio": audio, "control_only": True})

    def _transcribe(self, request):
        self.prepare()
        try:
            self.connection.send(request)
        except (OSError, EOFError) as exc:
            self.close()
            raise SpeechTimeout("The local speech worker disconnected. It will restart.") from exc
        kind, value = self.receive(self.settings.decode_timeout)
        if kind != "result":
            raise SpeechTimeout("Invalid response from the local speech worker.")
        text, self.last_uncertain, self.last_wake_confident, self.last_metrics = value
        return text

    def close(self):
        if self.connection:
            self.connection.close()
            self.connection = None
        if self.process:
            if self.process.is_alive():
                self.process.terminate()
            self.process.join(timeout=1)
            self.process = None

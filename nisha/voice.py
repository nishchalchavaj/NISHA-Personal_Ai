"""Optional local STT/TTS adapters. No microphone or model is opened at import time."""

import logging
import os
from pathlib import Path
from typing import Protocol

from nisha.errors import NishaError


class SpeechToText(Protocol):
    def transcribe(self, audio) -> str: ...


class TextToSpeech(Protocol):
    def speak(self, text: str) -> None: ...


class WhisperSpeech:
    def __init__(self, settings):
        self.settings = settings
        self.model = None
        self.last_uncertain = False
        self.last_wake_confident = False
        self.last_metrics = {}
        self.dll_handles = []

    def prepare(self):
        """Load local weights before the first spoken command arrives."""
        from faster_whisper import WhisperModel

        if self.model is None:
            if self.settings.device == "cuda" and os.name == "nt":
                import ctranslate2

                paths = [
                    Path(ctranslate2.__file__).parent,
                    Path("C:/Program Files/NVIDIA GPU Computing Toolkit/CUDA/v12.3/bin"),
                ]
                for path in paths:
                    if path.is_dir():
                        self.dll_handles.append(os.add_dll_directory(str(path)))
            from nisha.settings import ROOT

            configured = ROOT / self.settings.model
            model_name = str(configured) if configured.is_dir() else self.settings.model
            self.model = WhisperModel(
                model_name,
                device=self.settings.device,
                compute_type=self.settings.compute_type,
                local_files_only=True,
            )

    def transcribe(self, audio, control_only=False):
        self.prepare()
        segments, _ = self.model.transcribe(
            audio,
            beam_size=1 if control_only else self.settings.beam_size,
            language=self.settings.language,
            temperature=0,
            vad_filter=True,
            condition_on_previous_text=False,
            initial_prompt=(
                "The user may interrupt with Hey Nisha, Nisha, Stop, Enough, Stop speaking, Be quiet, Don't disturb me, Start fresh, Start a new conversation, or Let's talk about a different topic."
                if control_only
                else "Nisha is a personal computer assistant. Commands include opening YouTube, websites, Notepad, Word, writing email and code."
            ),
            hotwords="Hey Nisha, Nisha, Neesha, Nishaa, Nisa, Meesha, Stop, Enough, Quiet, Don't disturb, Start fresh, New conversation, Different topic"
            if control_only
            else self.settings.hotwords,
            word_timestamps=True,
            max_new_tokens=24 if control_only else None,
            vad_parameters={"min_silence_duration_ms": 500, "speech_pad_ms": 300},
        )
        segments = list(segments)
        text = " ".join(segment.text.strip() for segment in segments).strip()
        self.last_uncertain = bool(segments) and any(
            segment.avg_logprob < self.settings.min_confidence for segment in segments
        )
        from nisha.listening import WakeGate

        gate = WakeGate(self.settings.wake_word, aliases=self.settings.wake_aliases)
        match = gate.pattern.search(text)
        first = segments[0] if segments else None
        words = first.words if first and first.words else []
        # Opening the window and executing a command are separate decisions.
        # Proper names can score below the general-command threshold. Require
        # acoustic evidence for the prefix, while leaving the command uncertain.
        prefix = []
        position = 0
        for word in words:
            position += len(word.word)
            prefix.append(word.probability)
            if match and position >= match.end():
                break
        self.last_wake_confident = bool(
            match
            and first
            and first.avg_logprob >= self.settings.wake_min_confidence
            and first.no_speech_prob < 0.6
            and prefix
            and sum(prefix) / len(prefix) >= 0.35
        )
        self.last_metrics = {
            "logprob": round(first.avg_logprob, 3) if first else None,
            "wake_confident": self.last_wake_confident,
            "uncertain": self.last_uncertain,
            "control_confident": any(
                segment.avg_logprob >= self.settings.wake_min_confidence
                and segment.no_speech_prob < 0.6
                and any(
                    word.probability >= 0.35
                    and word.word.casefold().strip(" ,.!?:;")
                    in {
                        "stop",
                        "enough",
                        "quiet",
                        "quite",
                        "bye",
                        "goodbye",
                        "close",
                        "shut",
                        "shutup",
                        "disturb",
                    }
                    for word in (segment.words or [])
                )
                for segment in segments
            ),
        }
        if self.last_uncertain:
            logging.getLogger("nisha").info("Low-confidence speech: clarification required.")
        return text

    def warmup(self):
        """Initialize CUDA inference before advertising readiness; no user audio is used."""
        if self.settings.device != "cuda":
            return
        import numpy as np

        segments, _ = self.model.transcribe(
            np.zeros(self.settings.sample_rate, dtype=np.float32),
            beam_size=1,
            language=self.settings.language or "en",
            temperature=0,
            vad_filter=False,
            condition_on_previous_text=False,
            no_speech_threshold=None,
            log_prob_threshold=None,
            word_timestamps=True,
            max_new_tokens=8,
        )
        for _ in segments:
            pass


class WindowsSpeech:
    def __init__(self, rate=175, voice_locale=None):
        self.rate = rate
        self.voice_locale = voice_locale

    def choose_voice(self, voices):
        if self.voice_locale:
            locale = self.voice_locale.casefold().replace("_", "-")
            for voice in voices:
                details = " ".join(
                    [voice.name, voice.id]
                    + [str(value) for value in getattr(voice, "languages", [])]
                ).casefold().replace("_", "-")
                if locale in details or (locale == "en-in" and "english (india)" in details):
                    return voice.id
        for voice in voices:
            if "zira" in voice.name.lower() or "female" in voice.name.lower():
                return voice.id
        return None

    def speak(self, text, cancelled=None):
        self._render(text, cancelled=cancelled)

    def save(self, text, path):
        """Synthesize a WAV locally, useful for diagnostics without speaker playback."""
        self._render(text, path)

    def _render_winrt(self, text, cancelled):
        """Use an installed Indian English OneCore voice when Qt exposes one."""
        if os.name != "nt" or self.voice_locale != "en-IN":
            return False
        from time import monotonic, sleep

        from PySide6.QtCore import QCoreApplication, QLocale
        from PySide6.QtTextToSpeech import QTextToSpeech

        if "winrt" not in QTextToSpeech.availableEngines():
            return False
        app = QCoreApplication.instance() or QCoreApplication([])
        speech = QTextToSpeech("winrt")
        locale = QLocale("en_IN")
        if locale not in speech.availableLocales():
            return False
        speech.setLocale(locale)
        voices = speech.availableVoices()
        female = next((voice for voice in voices if voice.gender() == voice.Gender.Female), None)
        if female is None:
            return False
        speech.setVoice(female)
        speech.setRate(max(-1.0, min(1.0, (self.rate - 175) / 125)))
        speech.say(text)
        start_deadline = monotonic() + 3
        while speech.state() == QTextToSpeech.State.Ready and monotonic() < start_deadline:
            app.processEvents()
            if cancelled and cancelled():
                speech.stop()
                return True
            sleep(0.02)
        if speech.state() != QTextToSpeech.State.Speaking:
            speech.stop()
            return False
        finish_deadline = monotonic() + max(15, len(text) / 5)
        while speech.state() == QTextToSpeech.State.Speaking and monotonic() < finish_deadline:
            app.processEvents()
            if cancelled and cancelled():
                speech.stop()
                return True
            sleep(0.02)
        if speech.state() != QTextToSpeech.State.Ready:
            speech.stop()
            return False
        return True

    def _render(self, text, path=None, cancelled=None):
        from time import sleep

        import pyttsx3

        if cancelled and cancelled():
            return
        if path is None and self._render_winrt(text, cancelled):
            return
        if os.name == "nt":
            import pythoncom

            pythoncom.CoInitialize()
        engine = None
        external_loop = False
        try:
            engine = pyttsx3.init()
            engine.setProperty("rate", self.rate)
            if voice_id := self.choose_voice(engine.getProperty("voices")):
                engine.setProperty("voice", voice_id)
            if path is None:
                engine.say(text)
            else:
                engine.save_to_file(text, str(path))
            if cancelled and path is None:
                # Pump SAPI on its owning thread so cancellation can purge the
                # current utterance, rather than wait for a long runAndWait.
                engine.startLoop(False)
                external_loop = True
                engine.iterate()
                while engine.isBusy() and not cancelled():
                    engine.iterate()
                    sleep(0.02)
            else:
                engine.runAndWait()
        finally:
            try:
                if engine is not None:
                    engine.stop()
                    if external_loop:
                        engine.endLoop()
            finally:
                if os.name == "nt":
                    pythoncom.CoUninitialize()


def record(settings):
    import numpy as np
    import sounddevice as sd

    try:
        audio = sd.rec(
            int(settings.record_seconds * settings.sample_rate),
            samplerate=settings.sample_rate,
            channels=1,
            dtype="float32",
            device=settings.microphone,
            blocking=True,
        )
        return np.asarray(audio).reshape(-1)
    except Exception as exc:
        raise NishaError(
            "Cannot record audio. Check the Windows microphone and config voice.microphone."
        ) from exc


def voice_conversation(core):
    speech = WhisperSpeech(core.settings.voice)
    output = WindowsSpeech(core.settings.voice.rate, core.settings.voice.voice_locale)
    session = core.new_session()
    print("Local voice chat. Press Enter to record; type /exit to stop.")
    print("Whisper uses cached local model files; see README if the model is missing.")
    while True:
        try:
            if input("Ready: ").strip() == "/exit":
                return 0
            print(f"Listening for {core.settings.voice.record_seconds} seconds...")
            text = speech.transcribe(record(core.settings.voice))
            if not text:
                print("No speech detected.")
                continue
            print("You: " + text)
            reply = core.chat(text, session)
            print("NISHA: " + reply)
            output.speak(reply)
        except NishaError as exc:
            print(str(exc))
        except (KeyboardInterrupt, EOFError):
            return 0

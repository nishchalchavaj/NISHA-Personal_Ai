"""Local speech segmentation and wake gating. Background audio is never saved."""

import logging
import re
from collections import deque
from threading import Event, RLock
from time import monotonic

from nisha.errors import NishaError

logger = logging.getLogger("nisha")

STOP_PHRASES = {
    "stop",
    "enough",
    "that's enough",
    "that is enough",
    "stop talking",
    "stop speaking",
    "stop explaining",
    "stop the explanation",
    "nisha stop",
    "emergency stop",
}

CLOSE_PHRASES = {
    "just be quiet",
    "just be quite",
    "be quiet",
    "be quite",
    "quiet",
    "quite",
    "close",
    "close nisha",
    "close yourself",
    "if you are nisha close yourself",
    "bye",
    "goodbye",
    "shutup",
    "shut up",
    "close you mouth",
    "close your mouth",
    "go to sleep",
    "stop listening",
    "sleep now",
}


def is_close_phrase(text):
    normalized = re.sub(r"\s+", " ", text.casefold().replace(",", " ")).strip(" ,.!?:;–—-")
    return normalized.removeprefix("please ") in CLOSE_PHRASES


def is_stop_phrase(text):
    normalized = re.sub(r"\s+", " ", text.casefold()).strip(" ,.!?:;–—-")
    return normalized.removeprefix("please ") in STOP_PHRASES


def is_fresh_conversation_phrase(text):
    """Recognize a direct request to reset context, not a mention of such a request."""
    normalized = re.sub(r"\s+", " ", text.casefold().replace("’", "'")).strip(" ,.!?:;–—-")
    normalized = re.sub(
        r"^(?:please |can we |could we |i want to |i would like to )", "", normalized
    )
    normalized = re.sub(r"(?: please| now)$", "", normalized)
    normalized = re.sub(r"^(?:let's|lets|let us) ", "", normalized)
    return bool(
        re.fullmatch(
            r"(?:start (?:fresh|over)|"
            r"(?:start|begin|have) (?:a |some )?(?:new|fresh|another|other|different) (?:conversation|chat)|"
            r"(?:talk|speak) (?:about |on )?(?:a |some )?(?:new|different|another|other)(?: topic| conversation| something)?|"
            r"(?:have|start) (?:a |some )?(?:other|another|different) conversation (?:than|then) this(?: one)?|"
            r"(?:change|switch) (?:the )?topic|"
            r"switch to (?:a )?(?:new|different|another) (?:topic|conversation)|"
            r"(?:talk about |discuss )something (?:else|different)|new conversation|new chat|new topic)",
            normalized,
        )
    )


def output_control(text, reference, gate):
    """Accept attention/stop controls after removing recognized speaker echo."""
    from difflib import SequenceMatcher

    heard = re.findall(r"[\w']+", text.casefold())
    spoken = re.findall(r"[\w']+", reference.casefold())
    echoed = set()
    for match in SequenceMatcher(None, spoken, heard, autojunk=False).get_matching_blocks():
        if match.size >= 3:
            echoed.update(range(match.b, match.b + match.size))
    candidate = " ".join(word for index, word in enumerate(heard) if index not in echoed)
    wake = gate.pattern.search(candidate)
    wake_is_echo = False
    if wake:
        prefix = candidate[: wake.end()].strip()
        wake_is_echo = " " + prefix + " " in " " + " ".join(spoken) + " "
        candidate = candidate[wake.end() :].strip(" ,.!?")
    from nisha.interaction import is_quiet_request, is_silent_request

    if is_quiet_request(candidate):
        return "silent" if is_silent_request(candidate) else "quiet"
    if is_stop_phrase(candidate):
        return "stop"
    if is_close_phrase(candidate):
        return "dismiss"
    if is_fresh_conversation_phrase(candidate):
        return None if " " + candidate + " " in " " + " ".join(spoken) + " " else "fresh"
    if wake and not wake_is_echo and not candidate:
        return "wake"
    return None


def resembles_standalone_wake(text, settings):
    """An acoustic match can corroborate a short mis-spelled name, never a command."""
    from difflib import SequenceMatcher

    words = re.findall(r"\w+", text.casefold())
    if len(words) > 1 and words[:-1] in [["hey"], ["hi"], ["hello"], ["thanks"], ["thank", "you"]]:
        words = words[-1:]
    return (
        not words
        or len(words) == 1
        and any(
            SequenceMatcher(None, words[0], alias.casefold()).ratio() >= 0.8
            for alias in [settings.wake_word, *settings.wake_aliases]
        )
    )


class WakeGate:
    def __init__(self, wake_word="nisha", follow_up_seconds=0, clock=monotonic, aliases=None):
        self.clock = clock
        self.follow_up_seconds = follow_up_seconds
        aliases = [wake_word] + (
            aliases if aliases is not None else ["neesha", "nishaa", "nisa", "meesha", "निशा"]
        )
        self.pattern = re.compile(
            r"^\s*(?:(?:hey|hi|hello)[,\s]+)?(?:"
            + "|".join(re.escape(word) for word in aliases)
            + r")(?!\w)",
            re.IGNORECASE,
        )
        self.deadline = 0
        self.sleep_requested = False

    @property
    def awake(self):
        return self.clock() < self.deadline

    def reset(self):
        self.deadline = 0

    def extend(self):
        self.deadline = (
            self.clock() + self.follow_up_seconds if self.follow_up_seconds else float("inf")
        )

    def accept(self, text):
        """None means ignored; an empty string means wake-only, ready for a question."""
        self.sleep_requested = False
        match = self.pattern.search(text)
        remainder = text[match.end() :].strip(" ,.!?:;–—-") if match else text
        if (self.awake or match) and is_close_phrase(remainder):
            self.reset()
            self.sleep_requested = True
            return None
        if match:
            self.extend()
            return remainder
        if self.awake and text.strip():
            self.extend()
            return text.strip()
        return None

    def requests_close(self, text):
        match = self.pattern.search(text)
        candidate = text[match.end() :] if match else text
        return bool((self.awake or match) and is_close_phrase(candidate))


class UtteranceBuffer:
    """Bound speech in RAM; endpoint after silence, including a short pre-roll."""

    def __init__(self, settings):
        self.settings = settings
        self.noise_floor = 0.0
        self.reset()

    def reset(self):
        self.pre_roll = deque(maxlen=7)
        self.parts = []
        self.samples = self.voiced = self.silent = 0

    def feed(self, block, speech_detected=None):
        import numpy as np

        block = np.asarray(block, dtype=np.float32).reshape(-1).copy()
        rms = float(np.sqrt(np.mean(block * block)))
        threshold = max(self.settings.speech_threshold, self.noise_floor * 2)
        loud = rms >= threshold if speech_detected is None else speech_detected
        if not self.parts:
            if not loud:
                self.noise_floor = self.noise_floor * 0.95 + rms * 0.05
                self.pre_roll.append(block)
                return None
            self.parts.extend(self.pre_roll)
            self.samples = sum(len(part) for part in self.parts)
        self.parts.append(block)
        self.samples += len(block)
        self.voiced += len(block) if loud else 0
        self.silent = 0 if loud else self.silent + len(block)
        rate = self.settings.sample_rate
        if (
            self.silent >= self.settings.silence_seconds * rate
            or self.samples >= self.settings.max_utterance_seconds * rate
        ):
            audio = np.concatenate(self.parts) if self.voiced >= rate * 0.2 else None
            self.reset()
            return audio
        return None


class InterruptBuffer:
    """Short rolling windows also work when speaker echo never becomes silent."""

    def __init__(self, settings):
        self.settings = settings
        self.reset()

    def reset(self):
        self.parts = deque(maxlen=20)
        self.voiced = deque(maxlen=5)
        self.blocks = 0

    def feed(self, block, speech_detected=None):
        import numpy as np

        block = np.asarray(block, dtype=np.float32).reshape(-1).copy()
        self.parts.append(block)
        self.voiced.append(
            bool(np.sqrt(np.mean(block * block)) >= self.settings.speech_threshold)
            if speech_detected is None
            else speech_detected
        )
        self.blocks += 1
        if self.blocks >= 5:
            self.blocks = 0
            if any(self.voiced):
                return np.concatenate(self.parts)
        return None


class ListenerEngine:
    def __init__(
        self,
        settings,
        command,
        state,
        wake,
        error,
        speech=None,
        stream_factory=None,
        uncertain=None,
        dismiss=None,
        personal_model_path=None,
        interrupt=None,
        silence=None,
        silent=None,
        fresh=None,
        opened=None,
    ):
        self.settings = settings
        self.command, self.state, self.wake, self.error = command, state, wake, error
        self.uncertain = uncertain
        self.dismiss = dismiss or (lambda: None)
        self.interrupt = interrupt or (lambda: None)
        self.silence = silence or self.interrupt
        self.silent = silent or self.silence
        self.fresh = fresh or command
        self.opened = opened or wake
        self.background = Event()
        self.output_active = Event()
        self.output_reference = ""
        self.personal_model_path = personal_model_path
        self.personal_model = None
        self.personal_model_version = None
        self.stream_factory = stream_factory
        self.detector_factory = None
        self.gate = WakeGate(
            settings.wake_word, settings.follow_up_seconds, aliases=settings.wake_aliases
        )
        self.stopped = Event()
        if speech is None:
            from nisha.speech_worker import BoundedSpeech

            speech = BoundedSpeech(settings, self.stopped)
        self.speech = speech
        self.muted = Event()
        self.paused = Event()
        self.dispatching = Event()
        self.decoding = Event()
        self.wake_only = Event()
        self.quiet = Event()
        self.quiet.set()
        self.ready = Event()
        self.lock = RLock()
        self.epoch = 0
        from nisha.microphones import MicSelector

        self.mic_selector = MicSelector(hold_seconds=settings.silence_seconds + 0.2)

    def set_muted(self, muted):
        with self.lock:
            self.epoch += 1
            if muted:
                self.muted.set()
                self.gate.reset()
            else:
                self.muted.clear()

    def pause(self):
        with self.lock:
            self.epoch += 1
            self.paused.set()

    def resume(self, follow_up=False, wake_only=False):
        with self.lock:
            self.wake_only.set() if wake_only else self.wake_only.clear()
            if not self.muted.is_set() and (follow_up or self.gate.awake):
                self.gate.extend()
            if not self.dispatching.is_set():
                self.paused.clear()

    def stop(self):
        self.stopped.set()
        self.pause()

    def begin_output(self, text):
        with self.lock:
            self.epoch += 1
            self.output_reference = text
            self.output_active.set()
            self.wake_only.set()
            self.paused.clear()

    def end_output(self):
        with self.lock:
            if self.output_active.is_set():
                self.epoch += 1
            self.output_active.clear()
            self.output_reference = ""

    def wait_for_wake(self):
        """Drop queued/stale follow-ups without stopping background microphone capture."""
        with self.lock:
            self.epoch += 1
            self.gate.reset()

    def invite_reply(self, seconds=30):
        """Open a bounded reply window after NISHA initiates a check-in."""
        with self.lock:
            self.gate.deadline = self.gate.clock() + seconds
            self.wake_only.clear()
            if not self.dispatching.is_set():
                self.paused.clear()

    def open_background_window(self):
        """The first background wake opens the dashboard, without granting commands."""
        if not self.background.is_set():
            return False
        self.background.clear()
        self.epoch += 1
        self.gate.reset()
        self.opened()
        self.state("Waiting for NISHA")
        return True

    def blocked(self):
        return self.stopped.is_set() or self.muted.is_set() or self.paused.is_set()

    def run(self):
        from queue import Queue
        from threading import Thread

        self.audio_queue = Queue(maxsize=4)
        decoder = Thread(target=self.decode_loop, daemon=True)
        decoder.start()
        automatic = None
        try:
            import sounddevice as sd

            factory = self.stream_factory or sd.InputStream
            if self.stream_factory is None:
                from nisha.microphones import AutoMicrophoneStream

                automatic = AutoMicrophoneStream(
                    self.settings, self.mic_selector, should_stop=self.blocked
                )
                factory = lambda **kwargs: automatic
            buffer = UtteranceBuffer(self.settings)
            interrupt_buffer = InterruptBuffer(self.settings)
            detector = (
                self.detector_factory(self.settings.vad_threshold)
                if self.detector_factory
                else SpeechDetector(self.settings.vad_threshold)
                if self.settings.use_speech_vad and self.stream_factory is None
                else None
            )
            started = False
            while not self.stopped.is_set():
                if self.blocked():
                    self.quiet.set()
                    self.stopped.wait(0.05)
                    continue
                buffer.reset()
                interrupt_buffer.reset()
                if detector:
                    detector.reset()
                self.quiet.clear()
                try:
                    with factory(
                        samplerate=self.settings.sample_rate,
                        channels=1,
                        dtype="float32",
                        device=self.settings.microphone,
                    ) as stream:
                        if not started:
                            logger.info("Local wake listener is monitoring the microphone.")
                            started = True
                        listening_state = self.listening_state()
                        self.state(listening_state)
                        source_name = ""
                        while not self.blocked():
                            current_state = self.listening_state()
                            if current_state != listening_state:
                                listening_state = current_state
                                self.state(listening_state)
                            block, overflow = stream.read(self.settings.sample_rate // 10)
                            current_source = (
                                getattr(stream, "source_name", ""),
                                getattr(stream, "source_epoch", 0),
                                self.epoch,
                            )
                            if current_source != source_name:
                                source_name = current_source
                                buffer.reset()
                                interrupt_buffer.reset()
                                if detector:
                                    detector.reset()
                            if overflow:
                                buffer.reset()
                                interrupt_buffer.reset()
                                continue
                            with self.lock:
                                epoch = self.epoch
                                output = self.output_active.is_set()
                            selected_buffer = interrupt_buffer if output else buffer
                            audio = selected_buffer.feed(
                                block, detector.feed(block) if detector else None
                            )
                            if audio is not None and not self.blocked():
                                # Enrolled wake detection uses CPU in the capture
                                # path, so a busy/stalled ASR worker cannot delay it.
                                personal = not output and self.personal_wake(audio)
                                early_wake = False
                                opened_only = False
                                if personal:
                                    with self.lock:
                                        if (
                                            not self.blocked()
                                            and epoch == self.epoch
                                            and not self.gate.awake
                                        ):
                                            opened_only = self.open_background_window()
                                            if not opened_only:
                                                self.epoch += 1
                                                self.gate.extend()
                                                self.wake()
                                            epoch = self.epoch
                                            early_wake = True
                                            self.state(
                                                "Waiting for NISHA" if opened_only else "Listening"
                                            )
                                            logger.info(
                                                "Personal voice model detected a standalone wake."
                                            )
                                from queue import Empty, Full

                                item = (
                                    audio,
                                    epoch,
                                    getattr(stream, "selected_index", None),
                                    output,
                                    personal,
                                    early_wake,
                                    opened_only,
                                )
                                try:
                                    self.audio_queue.put_nowait(item)
                                except Full:
                                    try:
                                        self.audio_queue.get_nowait()
                                    except Empty:
                                        pass
                                    self.audio_queue.put_nowait(item)
                finally:
                    self.quiet.set()
        except Exception:
            logger.exception("Continuous local listener failed")
            # A device fault is not a manual mute. The UI can restart this
            # listener while preserving the user's microphone preference.
            self.error(
                "Listening stopped. Retrying the microphone automatically."
            )
        finally:
            self.stopped.set()
            if automatic:
                automatic.close()
            self.quiet.set()
            decoder.join()
            logger.info("Local wake listener stopped.")

    def decode_loop(self):
        from queue import Empty

        try:
            if hasattr(self.speech, "prepare"):
                self.state("Loading local speech")
                self.speech.prepare()
            self.ready.set()
            logger.info("Local speech model is ready.")
            while not self.stopped.is_set():
                self.decoding.clear()
                try:
                    item = self.audio_queue.get(timeout=0.1)
                    audio, epoch, microphone, output = item[:4]
                    personal, early_wake = item[4:6] if len(item) > 4 else (False, False)
                    opened_only = item[6] if len(item) > 6 else False
                except Empty:
                    continue
                if self.blocked() or epoch != self.epoch:
                    continue
                if opened_only:
                    continue  # Do not treat the opening take as a second attention wake.
                self.decoding.set()
                self.state("Transcribing")
                from nisha.speech_worker import SpeechTimeout

                try:
                    started_decoding = monotonic()
                    text = (
                        self.speech.transcribe_control(audio)
                        if output and hasattr(self.speech, "transcribe_control")
                        else self.speech.transcribe(audio)
                    )
                except SpeechTimeout as exc:
                    if self.stopped.is_set():
                        break
                    logger.warning("%s", exc)
                    self.state("Speech decoder restarting · please repeat")
                    with self.lock:
                        if epoch == self.epoch:
                            self.epoch += 1
                    continue
                del audio
                low_confidence = getattr(self.speech, "last_uncertain", False)
                wake_confident = (
                    not low_confidence
                    or getattr(self.speech, "last_wake_confident", False)
                    or personal
                )
                (logger.debug if output else logger.info)(
                    "Local speech decoded in %.2fs; command uncertain=%s; wake confident=%s.",
                    monotonic() - started_decoding,
                    low_confidence,
                    wake_confident,
                )
                control_confident = not low_confidence or getattr(
                    self.speech, "last_metrics", {}
                ).get("control_confident", False)
                if not output and low_confidence and not wake_confident and microphone is not None:
                    self.mic_selector.penalize(microphone)
                with self.lock:
                    if self.blocked() or epoch != self.epoch:
                        continue
                    if output:
                        # Speaker audio can only stop output or request attention,
                        # never execute a PC command.
                        control = output_control(text, self.output_reference, self.gate)
                        trusted = (
                            wake_confident
                            if control == "wake"
                            else not low_confidence
                            if control == "fresh"
                            else control_confident
                        )
                        if control and trusted:
                            logger.info("Spoken output interruption detected: %s.", control)
                            self.epoch += 1
                            if control == "dismiss":
                                self.gate.reset()
                                self.dismiss()
                            elif control in {"quiet", "silent"}:
                                self.gate.extend()
                                (self.silent if control == "silent" else self.silence)()
                            elif control == "wake":
                                self.gate.extend()
                                self.wake()
                            elif control == "fresh":
                                self.gate.extend()
                                self.fresh("Start fresh")
                            else:
                                self.gate.extend()
                                self.interrupt()
                        continue
                    explicit_wake = bool(self.gate.pattern.search(text))
                    if (
                        explicit_wake and wake_confident or personal
                    ) and self.open_background_window():
                        continue
                    if (
                        personal
                        and not explicit_wake
                        and resembles_standalone_wake(text, self.settings)
                    ):
                        self.gate.extend()
                        if not early_wake:
                            self.wake()
                        self.state("Listening")
                        continue
                    if early_wake and not explicit_wake:
                        # A background acoustic match may show the window, but
                        # cannot authorize an unrelated command in that clip.
                        self.state("Listening")
                        continue
                    remainder = (
                        text[self.gate.pattern.search(text).end() :] if explicit_wake else text
                    )
                    from nisha.interaction import is_quiet_request, is_silent_request

                    if (self.gate.awake or explicit_wake) and is_fresh_conversation_phrase(
                        remainder
                    ):
                        if not low_confidence and (not explicit_wake or wake_confident):
                            self.epoch += 1
                            self.gate.extend()
                            self.fresh(remainder.strip(" ,.!?"))
                        continue
                    if (
                        self.gate.awake or explicit_wake or not self.background.is_set()
                    ) and is_quiet_request(remainder):
                        if control_confident:
                            self.epoch += 1
                            self.gate.extend()
                            (self.silent if is_silent_request(remainder) else self.silence)()
                        continue
                    if (self.gate.awake or explicit_wake) and is_stop_phrase(remainder):
                        if control_confident:
                            self.epoch += 1
                            self.gate.extend()
                            self.interrupt()
                        continue
                    if (
                        self.wake_only.is_set()
                        and not explicit_wake
                        and not self.gate.requests_close(text)
                    ):
                        self.state("Waiting for NISHA")
                        continue
                    previous_deadline = self.gate.deadline
                    accepted = self.gate.accept(text)
                    if self.gate.sleep_requested:
                        if low_confidence:
                            self.gate.deadline = previous_deadline
                        else:
                            logger.info(
                                "Voice dismissal received; returning to background wake listening."
                            )
                            self.epoch += 1
                            self.dismiss()
                        self.state("Listening" if self.gate.awake else "Waiting for NISHA")
                        continue
                    if explicit_wake and not wake_confident:
                        logger.info("Wake phrase was unclear; waiting for a clearer wake.")
                        # Uncertain wake audio must not enable ambient follow-ups.
                        self.gate.deadline = previous_deadline
                    if accepted is None:
                        self.state("Listening" if self.gate.awake else "Waiting for NISHA")
                        continue
                    if accepted:
                        # Opening the UI must not resume capture in the middle
                        # of the decoder -> quiet capture -> command handoff.
                        self.dispatching.set()
                        self.paused.set()
                    if explicit_wake and wake_confident and not early_wake:
                        logger.info("Wake phrase detected; requesting conversation attention.")
                        self.wake()
                    if not accepted:
                        self.state(
                            "Listening" if self.gate.awake else "Wake unclear · say Hey NISHA again"
                        )
                        continue
                # Normal commands wait for idle capture; output controls above
                # keep the microphone open and never enter this dispatch path.
                closed = self.quiet.wait(5)
                with self.lock:
                    self.dispatching.clear()
                    valid = (
                        closed
                        and epoch == self.epoch
                        and not self.stopped.is_set()
                        and not self.muted.is_set()
                    )
                if not valid:
                    if not closed:
                        logger.warning("Microphone handoff timed out; ask the user to repeat.")
                        self.state("Microphone busy · please repeat")
                    if not self.stopped.is_set():
                        self.resume()
                    continue
                if self.uncertain and low_confidence:
                    self.uncertain(accepted)
                else:
                    self.command(accepted)
        except Exception:
            if self.stopped.is_set():
                return  # Shutdown can interrupt model loading or decoding.
            logger.exception("Local speech decoding failed")
            self.stopped.set()
            self.error(
                "Speech recognition stopped. Retrying automatically."
            )
        finally:
            self.decoding.clear()
            self.dispatching.clear()
            if hasattr(self.speech, "close"):
                self.speech.close()

    def listening_state(self):
        if not self.ready.is_set():
            return "Loading local speech"
        return "Listening" if self.gate.awake else "Waiting for NISHA"

    def personal_wake(self, audio):
        if self.personal_model_path is None:
            return False
        from pathlib import Path
        from zipfile import BadZipFile

        from nisha.neural_wake import NeuralWakeModel
        from nisha.voice_profile import PersonalWakeModel

        path = Path(self.personal_model_path)
        neural_path = path.with_name("neural-wake-model.npz")
        try:
            if neural_path.exists():
                path = neural_path
                model_class = NeuralWakeModel
            else:
                model_class = PersonalWakeModel
            version = path.stat().st_mtime_ns
            identity = (str(path), version)
            if identity != self.personal_model_version:
                self.personal_model = model_class.load(path)
                self.personal_model_version = identity
            return self.personal_model.matches(audio)
        except FileNotFoundError:
            self.personal_model = None
            self.personal_model_version = None
        except (OSError, ValueError, KeyError, NishaError, BadZipFile):
            logger.warning("Personal wake model unavailable; using cached speech recognition.")
        return False


class SpeechDetector:
    """Bundled local Silero VAD distinguishes speech from microphone noise."""

    def __init__(self, threshold):
        from faster_whisper.vad import get_vad_model

        self.model = get_vad_model()
        self.threshold = threshold
        self.reset()

    def reset(self):
        self.blocks = deque(maxlen=8)

    def feed(self, block):
        import numpy as np

        self.blocks.append(np.asarray(block, dtype=np.float32).reshape(-1))
        audio = np.concatenate(self.blocks)
        audio = np.pad(audio, (0, (-len(audio)) % 512))
        scores = self.model(audio).reshape(-1)
        return bool(np.max(scores[-4:]) >= self.threshold)

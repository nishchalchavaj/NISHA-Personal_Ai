import threading

import numpy as np
import pytest

from nisha.listening import (
    CLOSE_PHRASES,
    ListenerEngine,
    UtteranceBuffer,
    WakeGate,
    is_close_phrase,
)
from nisha.settings import VoiceSettings


def test_shutdown_during_speech_loading_does_not_report_a_decoder_failure(caplog):
    from nisha.speech_worker import SpeechTimeout

    errors = []

    class Speech:
        closed = False

        def prepare(self):
            engine.stop()
            raise SpeechTimeout("Speech decoding was stopped.")

        def close(self):
            self.closed = True

    speech = Speech()
    engine = ListenerEngine(
        VoiceSettings(), lambda _: None, lambda _: None, lambda: None, errors.append, speech=speech
    )
    engine.decode_loop()
    assert speech.closed and not errors
    assert "Local speech decoding failed" not in caplog.text


def test_wake_followups_expiry_and_exact_word():
    time = [1.0]
    gate = WakeGate(follow_up_seconds=45, clock=lambda: time[0])
    assert gate.accept("Open YouTube") is None
    assert gate.accept("Anisha is here") is None
    assert gate.accept("Hey NISHA, open YouTube!") == "open YouTube"
    assert gate.accept("What about tomorrow?") == "What about tomorrow?"
    time[0] += 46
    assert gate.accept("Open YouTube") is None
    assert gate.accept("Nisha.") == ""
    assert gate.accept("Continue") == "Continue"
    gate.reset()
    assert gate.accept("Continue") is None


def test_all_requested_wakes_keep_conversation_active_until_sleep():
    for name in [
        "Hey NISHA",
        "Hey Neesha",
        "hey nishaa",
        "hey nisa",
        "NISHA",
        "Neesha",
        "nishaa",
        "nisa",
        "meesha",
    ]:
        time = [1.0]
        gate = WakeGate(clock=lambda time=time: time[0])
        assert gate.accept(name) == ""
        time[0] += 10_000
        assert gate.accept("open YouTube") == "open YouTube"
        assert gate.accept("write code") == "write code"
        assert gate.accept("go to sleep") is None
        assert not gate.awake
        assert gate.accept("open YouTube") is None


def test_utterance_endpoint_preroll_and_maximum_duration():
    settings = VoiceSettings(silence_seconds=0.5, max_utterance_seconds=3)
    buffer = UtteranceBuffer(settings)
    quiet = np.zeros(1600, dtype=np.float32)
    loud = np.full(1600, 0.1, dtype=np.float32)
    for _ in range(10):
        assert buffer.feed(quiet) is None
    for _ in range(5):
        assert buffer.feed(loud) is None
    for _ in range(4):
        assert buffer.feed(quiet) is None
    result = buffer.feed(quiet)
    assert len(result) == 17 * 1600  # 7 pre-roll, 5 speech, 5 endpoint
    for _ in range(29):
        assert buffer.feed(loud) is None
    assert len(buffer.feed(loud)) == 3 * 16000


def test_silence_and_single_noise_click_do_not_trigger_transcription():
    buffer = UtteranceBuffer(VoiceSettings())
    quiet = np.zeros(1600, dtype=np.float32)
    assert buffer.feed(np.full(1600, 0.2)) is None
    for _ in range(50):
        assert buffer.feed(quiet) is None


def test_background_noise_floor_does_not_continuously_trigger_whisper():
    buffer = UtteranceBuffer(VoiceSettings())
    for _ in range(100):
        assert buffer.feed(np.full(1600, 0.01)) is None
    for _ in range(100):
        assert buffer.feed(np.full(1600, 0.013)) is None
    assert not buffer.parts


class FakeStream:
    def __init__(self, engine, observed, **kwargs):
        self.engine, self.observed = engine, observed
        self.reads = 0

    def __enter__(self):
        self.observed.append("open")
        return self

    def __exit__(self, *args):
        self.observed.append("close")

    def read(self, frames):
        from time import sleep

        sleep(0.005)
        self.reads += 1
        value = 0.1 if self.reads % 20 <= 5 else 0
        return np.full((frames, 1), value, dtype=np.float32), False


def test_background_audio_is_ignored_wake_executes_only_after_capture_closes():
    observed, commands = [], []
    engine = None

    class Speech:
        calls = 0

        def transcribe(self, audio):
            assert observed[-1] == "open"
            self.calls += 1
            return "television discussion" if self.calls == 1 else "Nisha open YouTube"

    def command(text):
        assert engine.quiet.is_set()
        assert engine.paused.is_set()
        commands.append(text)
        engine.stop()

    engine = ListenerEngine(
        VoiceSettings(),
        command,
        lambda text: None,
        lambda: None,
        lambda text: None,
        speech=Speech(),
        stream_factory=lambda **kw: FakeStream(engine, observed, **kw),
    )
    engine.run()
    assert commands == ["open YouTube"]
    assert observed == ["open", "close"]


def test_muting_during_transcription_drops_pending_command():
    commands, observed = [], []
    engine = None

    class Speech:
        def transcribe(self, audio):
            engine.set_muted(True)
            engine.stop()
            return "Nisha open YouTube"

    engine = ListenerEngine(
        VoiceSettings(),
        commands.append,
        lambda text: None,
        lambda: None,
        lambda text: None,
        speech=Speech(),
        stream_factory=lambda **kw: FakeStream(engine, observed, **kw),
    )
    engine.run()
    assert not commands
    assert engine.quiet.is_set()
    assert not engine.gate.awake


def test_muted_listener_never_opens_microphone():
    observed = []
    engine = ListenerEngine(
        VoiceSettings(),
        lambda text: None,
        lambda text: None,
        lambda: None,
        lambda text: None,
        stream_factory=lambda **kw: observed.append("opened"),
    )
    engine.set_muted(True)
    thread = threading.Thread(target=engine.run)
    thread.start()
    engine.stop()
    thread.join(timeout=2)
    assert not thread.is_alive() and not observed


def test_capture_failure_does_not_turn_on_manual_mute():
    errors = []

    def broken_stream(**_kwargs):
        raise OSError("input disconnected")

    class Speech:
        def prepare(self):
            pass

        def close(self):
            pass

    engine = ListenerEngine(
        VoiceSettings(), lambda _: None, lambda _: None, lambda: None,
        errors.append, speech=Speech(), stream_factory=broken_stream,
    )
    engine.run()
    assert errors and "Retrying" in errors[0]
    assert not engine.muted.is_set()
    assert engine.stopped.is_set()


def test_explicit_wake_signal_precedes_combined_command_and_repeats_when_awake():
    events, observed = [], []
    engine = None

    class Speech:
        calls = 0

        def transcribe(self, _audio):
            self.calls += 1
            return "Hey Neesha, first command" if self.calls == 1 else "NISA, second command"

    def command(text):
        events.append(text)
        if text == "second command":
            engine.stop()
        else:
            engine.resume(follow_up=True)

    engine = ListenerEngine(
        VoiceSettings(),
        command,
        lambda _: None,
        lambda: events.append("wake"),
        lambda _: None,
        speech=Speech(),
        stream_factory=lambda **kw: FakeStream(engine, observed, **kw),
    )
    engine.run()
    assert events == ["wake", "first command", "wake", "second command"]


def test_followup_without_wake_does_not_emit_another_wake():
    events, observed = [], []
    engine = None

    class Speech:
        calls = 0

        def transcribe(self, _audio):
            self.calls += 1
            return "Hey Nisha" if self.calls == 1 else "open YouTube"

    def command(text):
        events.append(text)
        engine.stop()

    engine = ListenerEngine(
        VoiceSettings(),
        command,
        lambda _: None,
        lambda: events.append("wake"),
        lambda _: None,
        speech=Speech(),
        stream_factory=lambda **kw: FakeStream(engine, observed, **kw),
    )
    engine.run()
    assert events == ["wake", "open YouTube"]


def test_background_reset_discards_followup_but_keeps_capture_enabled():
    engine = ListenerEngine(
        VoiceSettings(), lambda _: None, lambda _: None, lambda: None, lambda _: None
    )
    engine.gate.extend()
    epoch = engine.epoch
    engine.wait_for_wake()
    assert engine.epoch == epoch + 1 and not engine.gate.awake
    assert not engine.blocked()


@pytest.mark.parametrize(
    "awake,text,expected",
    [
        (True, "open YouTube", ["open YouTube"]),
        (False, "Hey Nisha, open YouTube", ["wake", "open YouTube"]),
    ],
)
def test_personal_match_does_not_swallow_commands_or_emit_duplicate_wakes(awake, text, expected):
    events, observed = [], []

    class Speech:
        def transcribe(self, _audio):
            return text

    def command(value):
        events.append(value)
        engine.stop()

    engine = ListenerEngine(
        VoiceSettings(),
        command,
        lambda _: None,
        lambda: events.append("wake"),
        lambda _: None,
        speech=Speech(),
        stream_factory=lambda **kwargs: FakeStream(engine, observed, **kwargs),
    )
    engine.personal_wake = lambda _: True
    if awake:
        engine.resume(follow_up=True)
    thread = threading.Thread(target=engine.run)
    thread.start()
    thread.join(3)
    if thread.is_alive():
        engine.stop()
        thread.join(2)
        pytest.fail("Personal wake prevented the recognized command from reaching the UI.")
    assert events == expected


def test_window_wake_resume_cannot_reopen_mic_during_command_handoff():
    events, observed = [], []

    class Speech:
        def transcribe(self, audio):
            return "Hey Nisha, open YouTube"

    class SlowStream(FakeStream):
        def read(self, frames):
            from time import sleep

            sleep(0.08)  # Device I/O returns later than a fast GUI wake callback.
            return super().read(frames)

    def wake():
        assert engine.dispatching.is_set()
        engine.resume(follow_up=True)  # What showing the desktop window does.
        assert engine.paused.is_set()
        events.append("wake")

    def command(text):
        assert engine.quiet.is_set() and not engine.dispatching.is_set()
        events.append(text)
        engine.stop()

    engine = ListenerEngine(
        VoiceSettings(),
        command,
        lambda _: None,
        wake,
        lambda _: None,
        speech=Speech(),
        stream_factory=lambda **kwargs: SlowStream(engine, observed, **kwargs),
    )
    thread = threading.Thread(target=engine.run)
    thread.start()
    thread.join(4)
    if thread.is_alive():
        engine.stop()
        thread.join(2)
        pytest.fail("Showing NISHA reopened capture and lost the recognized command.")
    assert events == ["wake", "open YouTube"]


def test_wake_only_mode_ignores_ambient_followups_during_work():
    events, observed = [], []
    engine = None

    class Speech:
        calls = 0

        def transcribe(self, _audio):
            self.calls += 1
            return "open something" if self.calls == 1 else "Nisha, new question"

    def command(text):
        events.append(text)
        engine.stop()

    engine = ListenerEngine(
        VoiceSettings(),
        command,
        lambda _: None,
        lambda: events.append("wake"),
        lambda _: None,
        speech=Speech(),
        stream_factory=lambda **kw: FakeStream(engine, observed, **kw),
    )
    engine.gate.extend()
    engine.resume(wake_only=True)
    engine.run()
    assert events == ["wake", "new question"]


def test_uncertain_prefix_does_not_emit_trusted_session_reset():
    events, observed = [], []
    engine = None

    class Speech:
        last_uncertain = True

        def transcribe(self, _audio):
            return "Nisha, uncertain command"

    def uncertain(text):
        events.append(text)
        engine.stop()

    engine = ListenerEngine(
        VoiceSettings(),
        lambda _: events.append("command"),
        lambda _: None,
        lambda: events.append("wake"),
        lambda _: None,
        speech=Speech(),
        stream_factory=lambda **kw: FakeStream(engine, observed, **kw),
        uncertain=uncertain,
    )
    engine.run()
    assert events == ["uncertain command"]


def test_uncertain_bare_wake_does_not_enable_background_commands():
    events, observed = [], []
    engine = None

    class Speech:
        calls = 0
        last_uncertain = False

        def transcribe(self, _audio):
            self.calls += 1
            self.last_uncertain = self.calls == 1
            return {1: "Nisha", 2: "open something", 3: "Hey Nisha, confirmed command"}[self.calls]

    def command(text):
        events.append(text)
        engine.stop()

    engine = ListenerEngine(
        VoiceSettings(),
        command,
        lambda _: None,
        lambda: events.append("wake"),
        lambda _: None,
        speech=Speech(),
        stream_factory=lambda **kw: FakeStream(engine, observed, **kw),
    )
    engine.run()
    assert events == ["wake", "confirmed command"]


@pytest.mark.parametrize("phrase", sorted(CLOSE_PHRASES))
def test_close_phrases_require_active_conversation_or_explicit_wake(phrase):
    gate = WakeGate()
    assert not gate.requests_close(phrase)
    assert gate.accept(phrase) is None and not gate.sleep_requested
    gate.extend()
    assert gate.requests_close(phrase)
    assert gate.accept("Please " + phrase.upper() + "!") is None
    assert gate.sleep_requested and not gate.awake
    assert gate.accept("open YouTube") is None and not gate.sleep_requested
    assert gate.accept("Hey Neesha, " + phrase) is None
    assert gate.sleep_requested and not gate.awake


@pytest.mark.parametrize("text", ["close YouTube", "write about quiet", "say goodbye to Alex"])
def test_close_words_inside_commands_do_not_hide_nisha(text):
    assert not is_close_phrase(text)
    gate = WakeGate()
    gate.extend()
    assert not gate.requests_close(text)
    assert gate.accept(text) == text and not gate.sleep_requested


@pytest.mark.parametrize("thinking", [False, True])
def test_close_keeps_capture_alive_discards_followups_and_allows_new_wake(thinking):
    events, observed = [], []
    engine = None

    class Speech:
        calls = 0

        def transcribe(self, _audio):
            self.calls += 1
            return {1: "goodbye", 2: "open something", 3: "Hey Nisha, confirmed command"}[
                self.calls
            ]

    def dismiss():
        assert not engine.blocked() and not engine.gate.awake
        events.append("dismiss")

    def command(text):
        events.append(text)
        engine.stop()

    engine = ListenerEngine(
        VoiceSettings(),
        command,
        lambda _: None,
        lambda: events.append("wake"),
        lambda _: None,
        speech=Speech(),
        stream_factory=lambda **kw: FakeStream(engine, observed, **kw),
        dismiss=dismiss,
    )
    engine.gate.extend()
    engine.resume(wake_only=thinking)
    engine.run()
    assert events == ["dismiss", "wake", "confirmed command"]
    assert not engine.muted.is_set()


def test_uncertain_close_preserves_conversation_and_never_dismisses():
    events, observed = [], []
    engine = None

    class Speech:
        calls = 0
        last_uncertain = False

        def transcribe(self, _audio):
            self.calls += 1
            self.last_uncertain = self.calls == 1
            return "quiet" if self.calls == 1 else "continue please"

    def command(text):
        events.append(text)
        engine.stop()

    engine = ListenerEngine(
        VoiceSettings(),
        command,
        lambda _: None,
        lambda: events.append("wake"),
        lambda _: None,
        speech=Speech(),
        stream_factory=lambda **kw: FakeStream(engine, observed, **kw),
        dismiss=lambda: events.append("dismiss"),
    )
    engine.gate.extend()
    engine.run()
    assert events == ["continue please"]


def test_acoustically_confident_bare_wake_opens_then_trusted_followup_runs():
    events, observed = [], []
    engine = None

    class Speech:
        calls = 0
        last_uncertain = False
        last_wake_confident = True

        def transcribe(self, _audio):
            self.calls += 1
            self.last_uncertain = self.calls == 1
            return "Hey Nisha" if self.calls == 1 else "open YouTube"

    def command(text):
        events.append(text)
        engine.stop()

    engine = ListenerEngine(
        VoiceSettings(),
        command,
        lambda _: None,
        lambda: events.append("wake"),
        lambda _: None,
        speech=Speech(),
        stream_factory=lambda **kw: FakeStream(engine, observed, **kw),
    )
    engine.run()
    assert events == ["wake", "open YouTube"]


def test_confident_wake_does_not_execute_its_uncertain_command():
    events, observed = [], []
    engine = None

    class Speech:
        last_uncertain = True
        last_wake_confident = True

        def transcribe(self, _audio):
            return "Hey Nisha, open something"

    def uncertain(text):
        events.append("uncertain: " + text)
        engine.stop()

    engine = ListenerEngine(
        VoiceSettings(),
        lambda _: events.append("executed"),
        lambda _: None,
        lambda: events.append("wake"),
        lambda _: None,
        speech=Speech(),
        stream_factory=lambda **kw: FakeStream(engine, observed, **kw),
        uncertain=uncertain,
    )
    engine.run()
    assert events == ["wake", "uncertain: open something"]


@pytest.mark.parametrize("first_take", ["Hey Nisha", "Nisha, open YouTube"])
def test_background_first_wake_only_opens_second_wake_activates(first_take):
    events, observed = [], []
    engine = None

    class Speech:
        calls = 0

        def transcribe(self, _audio):
            self.calls += 1
            return [first_take, "open Facebook", "Nisha, open YouTube"][self.calls - 1]

    def opened():
        assert not engine.gate.awake
        events.append("opened idle")

    def command(text):
        events.append(text)
        engine.stop()

    engine = ListenerEngine(
        VoiceSettings(),
        command,
        lambda _: None,
        lambda: events.append("attention"),
        lambda _: None,
        speech=Speech(),
        stream_factory=lambda **kw: FakeStream(engine, observed, **kw),
        opened=opened,
    )
    engine.background.set()
    engine.run()
    assert events == ["opened idle", "attention", "open YouTube"]


def test_personal_background_wake_opens_once_without_consuming_attention():
    events, observed = [], []
    engine = None

    class Speech:
        def transcribe(self, _audio):
            return "Nisha, open YouTube"

    def command(text):
        events.append(text)
        engine.stop()

    engine = ListenerEngine(
        VoiceSettings(),
        command,
        lambda _: None,
        lambda: events.append("attention"),
        lambda _: None,
        speech=Speech(),
        stream_factory=lambda **kw: FakeStream(engine, observed, **kw),
        opened=lambda: events.append("opened idle"),
    )
    engine.personal_wake = lambda audio: True
    engine.background.set()
    engine.run()
    assert events == ["opened idle", "attention", "open YouTube"]


def test_dont_disturb_is_a_control_while_visible_and_idle_without_wake():
    events, observed = [], []
    engine = None

    class Speech:
        def transcribe(self, _):
            return "Dont disturb"

    def quiet():
        events.append("quiet")
        engine.wait_for_wake()
        engine.stop()

    engine = ListenerEngine(
        VoiceSettings(),
        lambda text: events.append("command"),
        lambda _: None,
        lambda: events.append("wake"),
        lambda _: None,
        speech=Speech(),
        stream_factory=lambda **kw: FakeStream(engine, observed, **kw),
        silence=quiet,
    )
    engine.run()
    assert events == ["quiet"] and not engine.gate.awake

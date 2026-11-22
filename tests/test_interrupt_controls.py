import threading

import numpy as np
import pytest

from nisha.listening import InterruptBuffer, ListenerEngine, WakeGate, output_control
from nisha.settings import VoiceSettings


@pytest.mark.parametrize(
    "heard,reference,expected",
    [
        ("Enough!", "This is a long explanation.", "stop"),
        ("Hey Nisha, please stop speaking.", "This is a long explanation.", "stop"),
        ("The planet orbits the sun. Enough.", "The planet orbits the sun.", "stop"),
        ("The red traffic light means stop.", "The red traffic light means stop.", None),
        ("That is enough information for today.", "That is enough information for today.", None),
        ("Nisha open YouTube", "Open YouTube", None),
        ("Don't stop", "An explanation", None),
        ("Stop the video", "An explanation", None),
        ("Please be quiet!", "An explanation", "quiet"),
        ("Please don't disturb me", "An explanation", "quiet"),
        ("Don't say any word", "An explanation", "silent"),
        ("Hey Nisha", "A detailed explanation about planets", "wake"),
        ("Nisha", "A detailed explanation about planets", "wake"),
        ("Hey Neesha", "A detailed explanation about planets", "wake"),
        ("Hey Nisha", "Say Hey Nisha to call me", None),
        ("Nisha", "My name is Nisha", None),
        ("Start fresh", "A detailed explanation about planets", "fresh"),
        ("Let's talk about a different topic", "A detailed explanation", "fresh"),
        ("Start fresh", "Say start fresh to reset the conversation", None),
    ],
)
def test_reply_echo_is_ignored_and_only_exact_controls_are_allowed(heard, reference, expected):
    assert output_control(heard, reference, WakeGate()) == expected


def test_interruption_windows_do_not_wait_for_speaker_silence():
    buffer = InterruptBuffer(VoiceSettings())
    audio = np.full(1600, 0.1, dtype=np.float32)
    windows = [buffer.feed(audio) for _ in range(50)]
    emitted = [window for window in windows if window is not None]
    assert len(emitted) == 10 and max(map(len, emitted)) == 32000
    buffer.reset()
    assert all(buffer.feed(np.zeros(1600)) is None for _ in range(20))


@pytest.mark.parametrize(
    "control",
    ["stop", "enough", "Hey Nisha stop", "quiet", "don't disturb me", "Hey Nisha", "start fresh"],
)
def test_live_capture_accepts_controls_during_output_without_dispatching_commands(control):
    events = []

    class Speech:
        calls = 0

        def transcribe(self, audio):
            self.calls += 1
            assert not engine.quiet.is_set()  # Microphone remains open throughout speech.
            return "Nisha open YouTube" if self.calls == 1 else control

    class Stream:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def read(self, frames):
            engine.stopped.wait(0.005)
            return np.full((frames, 1), 0.1, dtype=np.float32), False

    def finished(kind):
        events.append(kind)
        engine.stop()

    engine = ListenerEngine(
        VoiceSettings(),
        lambda text: events.append("command"),
        lambda _: None,
        lambda: finished("wake"),
        lambda text: events.append("error"),
        speech=Speech(),
        stream_factory=lambda **kwargs: Stream(),
        interrupt=lambda: finished("stop"),
        dismiss=lambda: finished("dismiss"),
        silence=lambda: finished("quiet"),
        fresh=lambda text: finished("fresh"),
    )
    engine.begin_output("A detailed explanation about planets.")
    thread = threading.Thread(target=engine.run)
    thread.start()
    thread.join(timeout=3)
    if thread.is_alive():
        engine.stop()
        thread.join(timeout=2)
        pytest.fail("Spoken control did not stop output within the test deadline.")
    assert events == [
        "wake"
        if control == "Hey Nisha"
        else "fresh"
        if control == "start fresh"
        else "dismiss"
        if control == "quiet"
        else "quiet"
        if control == "don't disturb me"
        else "stop"
    ]


def test_finished_output_invalidates_queued_speaker_audio():
    engine = ListenerEngine(
        VoiceSettings(), lambda _: None, lambda _: None, lambda: None, lambda _: None
    )
    engine.begin_output("Speaker output")
    epoch = engine.epoch
    engine.end_output()
    assert engine.epoch != epoch and not engine.output_active.is_set()
    assert not engine.blocked()


def test_late_output_decode_cannot_become_a_followup_command():
    from queue import Queue

    commands = []
    audio = np.zeros(16000)

    class Speech:
        def transcribe_control(self, _):
            engine.end_output()
            engine.resume(follow_up=True)
            engine.audio_queue.put((audio, engine.epoch, None, False))
            return "open YouTube"  # Old speaker audio must be discarded.

        def transcribe(self, _):
            return "actual user followup"

    def command(text):
        commands.append(text)
        engine.stop()

    engine = ListenerEngine(
        VoiceSettings(), command, lambda _: None, lambda: None, lambda _: None, speech=Speech()
    )
    engine.audio_queue = Queue()
    engine.begin_output("Old speaker output")
    engine.audio_queue.put((audio, engine.epoch, None, True))
    engine.decode_loop()
    assert commands == ["actual user followup"]

from queue import Empty, Queue

import numpy as np
import pytest

from nisha.listening import ListenerEngine, is_fresh_conversation_phrase
from nisha.settings import VoiceSettings


@pytest.mark.parametrize(
    "text",
    [
        "start fresh",
        "Start new conversation!",
        "start a fresh conversation",
        "lets talk new",
        "let's talk different topic",
        "Let's talk about a different topic.",
        "have some other conversation then this",
        "have some other conversation than this one",
        "Can we start a new conversation please?",
        "Let's start over",
        "let us have another conversation",
        "switch to another topic",
        "talk about something else",
    ],
)
def test_direct_fresh_requests(text):
    assert is_fresh_conversation_phrase(text)


@pytest.mark.parametrize(
    "text",
    [
        "Hey NISHA",
        "NISHA",
        "don't start fresh",
        "Do not start a new conversation",
        "Explain how to start a new conversation",
        "She said start fresh",
        "Write code that starts a new conversation",
        "Should I start fresh?",
        "Start fresh paint on the wall",
        "Let's talk about new conversation features",
    ],
)
def test_mentions_names_and_negations_do_not_reset(text):
    assert not is_fresh_conversation_phrase(text)


@pytest.mark.parametrize(
    "awake,thinking,heard,uncertain,expected",
    [
        (True, False, "start fresh", False, True),
        (True, True, "let's talk different topic", False, True),
        (False, False, "start fresh", False, False),
        (False, True, "Hey Nisha, start new conversation", False, True),
        (True, False, "start fresh", True, False),
    ],
)
def test_fresh_control_requires_awake_or_explicit_wake_and_confident_audio(
    awake, thinking, heard, uncertain, expected
):
    received, commands = [], []
    engine = None

    class Speech:
        last_uncertain = uncertain

        def transcribe(self, _):
            return heard

    class OneTakeQueue(Queue):
        def get(self, *args, **kwargs):
            if self.empty():
                engine.stopped.set()
                raise Empty
            return super().get(*args, **kwargs)

    engine = ListenerEngine(
        VoiceSettings(),
        commands.append,
        lambda _: None,
        lambda: None,
        lambda _: None,
        speech=Speech(),
        fresh=received.append,
    )
    if awake:
        engine.gate.extend()
    engine.resume(wake_only=thinking)
    engine.audio_queue = OneTakeQueue()
    engine.audio_queue.put((np.zeros(16000), engine.epoch, None, False))
    engine.decode_loop()
    assert bool(received) == expected
    assert not commands

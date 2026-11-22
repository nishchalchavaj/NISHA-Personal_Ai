from threading import Event
from time import sleep

import numpy as np
import pytest

from nisha.settings import VoiceSettings
from nisha.speech_worker import BoundedSpeech, SpeechTimeout


def hung_decoder(connection, settings):
    connection.send(("ready", None))
    connection.recv()
    sleep(60)


def working_decoder(connection, settings):
    connection.send(("ready", None))
    connection.recv()
    connection.send(("result", ("Nisha", True, True, {"wake_confident": True})))
    sleep(60)


def test_stuck_native_decoder_is_terminated_with_a_bounded_timeout():
    speech = BoundedSpeech(
        VoiceSettings().model_copy(update={"decode_timeout": 0.2}), target=hung_decoder
    )
    with pytest.raises(SpeechTimeout, match="timed out"):
        speech.transcribe(np.zeros(16000))
    assert speech.process is None and speech.connection is None


def test_worker_returns_wake_evidence_and_can_be_stopped_promptly():
    stopped = Event()
    speech = BoundedSpeech(VoiceSettings(), stopped, target=working_decoder)
    try:
        assert speech.transcribe(np.zeros(16000)) == "Nisha"
        assert speech.last_wake_confident and speech.last_uncertain
        stopped.set()
        with pytest.raises(SpeechTimeout, match="stopped"):
            speech.receive(20)
        assert speech.process is None
    finally:
        speech.close()

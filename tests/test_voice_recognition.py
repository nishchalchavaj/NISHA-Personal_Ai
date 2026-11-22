from types import SimpleNamespace

import numpy as np
import pytest

from nisha.settings import VoiceSettings
from nisha.voice import WhisperSpeech


@pytest.mark.parametrize(
    "text,probability,wake",
    [
        ("Hey Nisha", 0.6, True),
        ("Nisha", 0.5, True),
        ("Nisha", 0.05, False),
        ("open YouTube", 0.9, False),
    ],
)
def test_wake_confidence_is_separate_from_command_confidence(text, probability, wake):
    speech = WhisperSpeech(VoiceSettings())
    segment = SimpleNamespace(
        text=text,
        avg_logprob=-0.95,
        no_speech_prob=0.05,
        words=[SimpleNamespace(word=" " + word, probability=probability) for word in text.split()],
    )
    speech.model = SimpleNamespace(transcribe=lambda *args, **kwargs: ([segment], None))
    assert speech.transcribe(np.zeros(16000)) == text
    assert speech.last_uncertain
    assert speech.last_wake_confident is wake


def test_uncertain_combined_command_is_not_promoted_by_confident_wake():
    speech = WhisperSpeech(VoiceSettings())
    segment = SimpleNamespace(
        text="Nisha, open something",
        avg_logprob=-0.9,
        no_speech_prob=0.1,
        words=[
            SimpleNamespace(word=" Nisha,", probability=0.8),
            SimpleNamespace(word=" open", probability=0.1),
            SimpleNamespace(word=" something", probability=0.1),
        ],
    )
    speech.model = SimpleNamespace(transcribe=lambda *args, **kwargs: ([segment], None))
    speech.transcribe(np.zeros(16000))
    assert speech.last_wake_confident and speech.last_uncertain


@pytest.mark.parametrize(
    "probability,no_speech,confident", [(0.8, 0.05, True), (0.05, 0.05, False), (0.8, 0.95, False)]
)
def test_short_control_uses_acoustic_evidence_without_promoting_pc_commands(
    probability, no_speech, confident
):
    speech = WhisperSpeech(VoiceSettings())
    options = []
    segment = SimpleNamespace(
        text="Enough.",
        avg_logprob=-0.95,
        no_speech_prob=no_speech,
        words=[SimpleNamespace(word=" Enough.", probability=probability)],
    )

    def transcribe(audio, **kwargs):
        options.append(kwargs)
        return [segment], None

    speech.model = SimpleNamespace(transcribe=transcribe)
    assert speech.transcribe(np.zeros(16000), control_only=True) == "Enough."
    assert options[0]["beam_size"] == 1
    assert speech.last_metrics["control_confident"] is confident
    assert speech.last_uncertain  # General PC command confidence remains unchanged.

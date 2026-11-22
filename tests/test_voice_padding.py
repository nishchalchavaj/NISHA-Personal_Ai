import numpy as np

from nisha.voice_profile import features


def test_noisy_padding_uses_detected_speech_instead_of_full_take(monkeypatch):
    import faster_whisper.vad

    rng = np.random.default_rng(3)
    audio = rng.normal(0, 0.007, 64000).astype(np.float32)
    t = np.arange(16000) / 16000
    audio[16000:32000] += np.sin(2 * np.pi * (440 * t + 100 * t**2)) * 0.03
    monkeypatch.setattr(
        faster_whisper.vad, "get_speech_timestamps", lambda *args: [{"start": 15000, "end": 34000}]
    )
    result = features(audio)
    assert result is not None and 5 <= len(result) < 100


def test_short_wake_survives_long_silent_recording():
    t = np.arange(8000) / 16000
    speech = np.sin(2 * np.pi * (440 * t + 100 * t**2)).astype(np.float32) * 0.04
    result = features(np.concatenate([np.zeros(160000), speech, np.zeros(160000)]))
    assert result is not None and len(result) < 100

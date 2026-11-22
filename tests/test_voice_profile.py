import numpy as np
import pytest

from nisha.errors import NishaError
from nisha.neural_wake import NeuralWakeModel
from nisha.voice_profile import PersonalWakeModel, VoiceProfile, features


def sample(index, negative=False):
    rng = np.random.default_rng(index)
    t = np.arange(16000) / 16000
    phase = 2 * np.pi * (320 * t + 70 * t**2)
    signal = np.sin(phase) * (0.06 + 0.03 * np.sin(9 * t)) + 0.03 * np.sin(phase * 3)
    if negative:
        signal = np.sin(2 * np.pi * (1800 * t - 450 * t**2)) * 0.06
    return np.concatenate(
        [np.zeros(3200), signal + rng.normal(0, 0.00015, len(t)), np.zeros(6400)]
    ).astype(np.float32)


def test_explicit_sample_save_and_unchanged_reviewed_transcript(tmp_path):
    profile = VoiceProfile(tmp_path)
    entry = profile.save(sample(1), "Hey NISHA", "wake", "USB")
    assert len(profile.entries()) == 1
    assert len(profile.audio(entry)) == len(sample(1))
    with pytest.raises(NishaError, match="already saved"):
        profile.save(sample(1), "NISHA", "wake")
    with pytest.raises(NishaError, match="only NISHA"):
        profile.save(sample(2), "open YouTube", "wake")


def test_empty_dataset_and_silence_do_not_create_a_personal_model(tmp_path):
    profile = VoiceProfile(tmp_path)
    with pytest.raises(NishaError, match="at least 10"):
        profile.train()
    with pytest.raises(NishaError, match="too quiet"):
        profile.save(np.zeros(16000), "Nisha", "wake")
    assert not profile.model_path.exists()


def test_damaged_index_preserves_old_recording_and_accepts_future_variations(tmp_path):
    profile = VoiceProfile(tmp_path)
    original = profile.save(sample(1), "Hey NISHA", "wake")
    with profile.manifest.open("ab") as target:
        target.write(b'null\n{"incomplete":')
    assert profile.entries() == [original] and profile.invalid_entries == 2
    new = profile.save(sample(2), "NISHA", "wake")
    assert profile.entries() == [original, new] and profile.invalid_entries == 2
    assert b'{"incomplete":' in profile.manifest.read_bytes()
    assert len(profile.audio(original)) == len(sample(1))


def test_train_validates_disjoint_samples_and_runtime_model(tmp_path):
    profile = VoiceProfile(tmp_path)
    for index in range(10):
        profile.save(sample(index), "Nisha", "wake")
        profile.save(sample(index + 20, True), "open YouTube", "negative")
    report = profile.train()
    assert report["wake_test_hits"] == report["wake_test_total"] == 2
    assert report["negative_test_false_alarms"] == 0
    assert not report["whisper_weights_retrained"]
    model = PersonalWakeModel.load(profile.model_path)
    assert model.matches(sample(100))
    assert not model.matches(sample(101, True))
    assert not model.matches(np.zeros(16000))


def test_changed_sample_and_outside_path_are_rejected(tmp_path):
    profile = VoiceProfile(tmp_path)
    entry = profile.save(sample(1), "Nisha", "wake")
    with pytest.raises(NishaError, match="outside"):
        profile.audio(dict(entry, audio="../elsewhere.wav"))
    path = profile.root / entry["audio"]
    data = bytearray(path.read_bytes())
    data[-1] ^= 1
    path.write_bytes(data)
    with pytest.raises(NishaError, match="changed"):
        profile.audio(entry)


def test_long_command_cannot_match_standalone_wake_features():
    assert features(np.tile(sample(1), 6)) is None


def test_confusing_training_data_does_not_replace_previous_model(tmp_path):
    profile = VoiceProfile(tmp_path)
    profile.model_path.write_bytes(b"previous model preserved")
    for index in range(10):
        profile.save(sample(index), "Nisha", "wake")
        profile.save(sample(index + 20), "similar non-wake speech", "negative")
    with pytest.raises(NishaError):
        profile.train()
    assert profile.model_path.read_bytes() == b"previous model preserved"


def test_more_variations_retrain_without_losing_existing_recordings(tmp_path):
    profile = VoiceProfile(tmp_path)
    for index in range(10):
        profile.save(sample(index), "Nisha", "wake")
        profile.save(sample(index + 20, True), "ordinary speech", "negative")
    profile.train()
    originals = {
        entry["audio"]: (profile.root / entry["audio"]).read_bytes() for entry in profile.entries()
    }
    for index in range(10, 101):
        profile.save(sample(index), "Hey Nisha", "wake")
    for index in range(30, 40):
        profile.save(sample(index, True), "open YouTube", "command")
    report = profile.train()
    assert report["activated"] and report["wake_samples"] == 101
    assert report["non_wake_samples"] == 20
    assert PersonalWakeModel.load(profile.model_path).matches(sample(200))
    assert all((profile.root / name).read_bytes() == data for name, data in originals.items())


def test_neural_training_changes_weights_and_keeps_disjoint_test(tmp_path):
    profile = VoiceProfile(tmp_path)
    for index in range(15):
        profile.save(sample(index), "Nisha", "wake")
        profile.save(sample(index + 30, True), "ordinary speech", "negative")
    report = profile.train_neural()
    model = NeuralWakeModel.load(profile.neural_model_path)
    assert report["activated"]
    assert report["training_wakes"] == 9
    assert report["wake_test_total"] == 3
    assert model.matches(sample(200))
    assert not model.matches(sample(201, True))
    assert not model.matches(np.zeros(16000))

"""Explicit local recordings and a personal MFCC/DTW wake classifier.

This adapts wake detection to enrolled recordings; it does not retrain Whisper.
Only deliberately saved enrollment clips are persisted.
"""

import json
import logging
import re
import wave
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

import numpy as np

from nisha.errors import NishaError


def read_wav(path):
    import io

    from nisha.file_security import read_local_file

    imported = read_local_file(path, allowed={".wav"}, limit=1_000_000)
    if not (imported.data.startswith(b"RIFF") and imported.data[8:12] == b"WAVE"):
        raise NishaError("This is not a readable PCM WAV recording.")
    try:
        with wave.open(io.BytesIO(imported.data), "rb") as source:
            if (source.getnchannels(), source.getsampwidth(), source.getframerate()) != (
                1,
                2,
                16000,
            ):
                raise NishaError("Voice samples must be mono, 16 kHz, 16-bit PCM WAV files.")
            if source.getnframes() > 16000 * 30:
                raise NishaError("Voice samples must be 30 seconds or shorter.")
            frames = source.readframes(source.getnframes())
            if len(frames) != source.getnframes() * 2:
                raise NishaError("The WAV recording is truncated or its length is incorrect.")
            return np.frombuffer(frames, dtype="<i2").astype(np.float32) / 32768
    except (wave.Error, EOFError) as exc:
        raise NishaError("This is not a readable PCM WAV recording.") from exc


def features(audio):
    audio = np.asarray(audio, dtype=np.float32).reshape(-1)
    if len(audio) < 3200 or not np.isfinite(audio).all():
        return None
    frames = np.lib.stride_tricks.sliding_window_view(audio, 400)[::320].copy()
    energy = np.sqrt(np.mean(frames * frames, axis=1))
    noise = float(np.percentile(energy, 20))
    # A fixed four-second take can contain a sub-second wake surrounded by
    # webcam hiss. Use speech VAD for noisy takes, not the recording's duration.
    if noise > float(energy.max()) * 0.12:
        try:
            from faster_whisper.vad import VadOptions, get_speech_timestamps

            spans = get_speech_timestamps(
                audio,
                VadOptions(
                    threshold=0.3,
                    min_speech_duration_ms=100,
                    min_silence_duration_ms=300,
                    speech_pad_ms=100,
                ),
            )
            if spans:
                audio = audio[spans[0]["start"] : spans[-1]["end"]]
                if len(audio) < 400:
                    return None
                frames = np.lib.stride_tricks.sliding_window_view(audio, 400)[::320].copy()
                energy = np.sqrt(np.mean(frames * frames, axis=1))
                noise = 0  # VAD has already separated speech from the room noise.
        except ImportError:
            pass
    active = np.flatnonzero(energy > max(0.0003, float(energy.max()) * 0.08, noise * 2))
    if len(active) < 5:
        return None
    frames = frames[max(0, active[0] - 2) : active[-1] + 3]
    if len(frames) > 180:
        return None  # Wake enrollment is a short standalone phrase.
    power = np.abs(np.fft.rfft(frames * np.hanning(400), n=512)) ** 2
    edges = np.linspace(0, 2595 * np.log10(1 + 8000 / 700), 26)
    bins = np.clip(np.floor(513 * (700 * (10 ** (edges / 2595) - 1)) / 16000).astype(int), 0, 256)
    filters = np.zeros((24, 257))
    for index, (left, center, right) in enumerate(zip(bins, bins[1:], bins[2:])):
        filters[index, left:center] = np.linspace(0, 1, center - left, endpoint=False)
        filters[index, center:right] = np.linspace(1, 0, right - center, endpoint=False)
    logmel = np.log(np.maximum(power @ filters.T, 1e-10))
    dct = np.cos(np.pi / 24 * (np.arange(24) + 0.5)[:, None] * np.arange(1, 14))
    mfcc = logmel @ dct
    mfcc -= mfcc.mean(axis=0)
    mfcc /= np.maximum(mfcc.std(axis=0), 1)
    return np.concatenate([mfcc, np.gradient(mfcc, axis=0)], axis=1).astype(np.float32)


def distance(left, right):
    if left is None or right is None:
        return float("inf")
    if not 0.45 < len(left) / len(right) < 2.2:
        return float("inf")
    costs = np.mean((left[:, None, :] - right[None, :, :]) ** 2, axis=2)
    previous = np.full(len(right) + 1, np.inf)
    previous[0] = 0
    for row in costs:
        current = np.full(len(right) + 1, np.inf)
        for column, cost in enumerate(row, 1):
            current[column] = cost + min(
                previous[column], previous[column - 1], current[column - 1]
            )
        previous = current
    return float(previous[-1] / (len(left) + len(right)))


class PersonalWakeModel:
    def __init__(self, templates, threshold):
        self.templates, self.threshold = templates, threshold

    def score(self, candidate):
        scores = sorted(distance(candidate, template) for template in self.templates)
        return float(np.mean(scores[:2])) if len(scores) >= 2 else float("inf")

    def matches(self, audio):
        return self.score(features(audio)) <= self.threshold

    @classmethod
    def load(cls, path):
        with np.load(path, allow_pickle=False) as saved:
            threshold = float(saved["threshold"])
            count = int(saved["count"])
            if not 2 <= count <= 100 or not 0 < threshold < 5:
                raise NishaError("Invalid personal wake model.")
            templates = [saved[f"template_{index}"] for index in range(count)]
            if any(
                t.ndim != 2
                or t.shape[1] != 26
                or not 5 <= len(t) <= 180
                or not np.isfinite(t).all()
                for t in templates
            ):
                raise NishaError("Invalid personal wake templates.")
            return cls(templates, threshold)


class VoiceProfile:
    def __init__(self, data_dir):
        self.root = Path(data_dir) / "voice-profile"
        self.samples = self.root / "samples"
        self.manifest = self.root / "manifest.jsonl"
        self.model_path = self.root / "wake-model.npz"
        self.neural_model_path = self.root / "neural-wake-model.npz"
        self.invalid_entries = 0
        self.samples.mkdir(parents=True, exist_ok=True)

    def entries(self):
        self.invalid_entries = 0
        if not self.manifest.exists():
            return []
        entries = []
        try:
            lines = self.manifest.read_bytes().splitlines()
        except OSError as exc:
            raise NishaError(
                "Voice sample index could not be read. Recordings remain on this PC."
            ) from exc
        for line in lines:
            if not line.strip():
                continue
            try:
                entry = json.loads(line.decode("utf-8"))
                if (
                    not isinstance(entry, dict)
                    or entry.get("kind") not in {"wake", "negative", "command"}
                    or not isinstance(entry.get("text"), str)
                    or not 1 <= len(entry["text"]) <= 1000
                    or not isinstance(entry.get("audio"), str)
                    or not isinstance(entry.get("sha256"), str)
                    or not re.fullmatch(r"[a-f0-9]{64}", entry["sha256"])
                    or not (self.root / entry["audio"])
                    .resolve()
                    .is_relative_to(self.samples.resolve())
                ):
                    raise ValueError("Invalid voice sample index entry")
                entries.append(entry)
            except (ValueError, TypeError, OSError):
                self.invalid_entries += 1
        if self.invalid_entries:
            logging.getLogger("nisha").warning(
                "Voice sample index has %d unreadable entries; original index and recordings preserved.",
                self.invalid_entries,
            )
        return entries

    def save(self, audio, text, kind, microphone=""):
        text = text.strip()
        audio = np.asarray(audio, dtype=np.float32).reshape(-1)
        if kind not in {"wake", "negative", "command"} or not text or len(text) > 1000:
            raise NishaError("Choose a sample type and provide the exact words you said.")
        if not 3200 <= len(audio) <= 16000 * 30 or not np.isfinite(audio).all():
            raise NishaError("Record between 0.2 and 30 seconds of valid audio.")
        if float(np.sqrt(np.mean(audio * audio))) < 0.0003:
            raise NishaError("The microphone is too quiet. Choose another input and record again.")
        if np.mean(np.abs(audio) >= 0.98) > 0.02:
            raise NishaError("The recording is clipping. Lower the microphone level and repeat.")
        from nisha.listening import WakeGate

        if kind == "wake" and WakeGate().accept(text) != "":
            raise NishaError(
                "A wake sample must contain only NISHA or Hey NISHA (or an accepted alias)."
            )
        pcm = (np.clip(audio, -1, 1) * 32767).astype("<i2").tobytes()
        digest = sha256(pcm).hexdigest()
        if any(entry["sha256"] == digest for entry in self.entries()):
            raise NishaError("This exact recording is already saved. Record a new take.")
        name = uuid4().hex + ".wav"
        with wave.open(str(self.samples / name), "wb") as target:
            target.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
            target.writeframes(pcm)
        entry = {
            "audio": "samples/" + name,
            "text": text,
            "kind": kind,
            "microphone": microphone,
            "sha256": digest,
        }
        # A crash can leave an incomplete last JSON line. Keep it for recovery,
        # but separate the new entry so future samples remain readable.
        needs_newline = False
        if self.manifest.exists() and self.manifest.stat().st_size:
            with self.manifest.open("rb") as source:
                source.seek(-1, 2)
                needs_newline = source.read(1) != b"\n"
        with self.manifest.open("a", encoding="utf-8") as target:
            if needs_newline:
                target.write("\n")
            target.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return entry

    def audio(self, entry):
        path = (self.root / entry["audio"]).resolve()
        if not path.is_relative_to(self.samples.resolve()):
            raise NishaError("A sample path is outside the voice profile.")
        audio = read_wav(path)
        if sha256((audio * 32768).astype("<i2").tobytes()).hexdigest() != entry["sha256"]:
            raise NishaError(
                "A recording changed after review. Import it again with its correct transcript."
            )
        return audio

    def train(self):
        entries = self.entries()
        from nisha.listening import WakeGate

        gate = WakeGate()
        groups = [
            [entry for entry in entries if entry["kind"] == "wake"],
            [
                entry
                for entry in entries
                if entry["kind"] == "negative"
                or (entry["kind"] == "command" and not gate.pattern.search(entry["text"]))
            ],
        ]
        if any(len(group) < 10 for group in groups):
            raise NishaError(
                "Save at least 10 wake takes and 10 non-wake speech takes before training. Aim for 20 of each."
            )
        prepared = []
        for group in groups:
            # Fixed, disjoint train/calibration/test split; never tune on test clips.
            prepared.append(
                [
                    [
                        features(self.audio(entry))
                        for index, entry in enumerate(group)
                        if index % 5 in slots
                    ]
                    for slots in [{0, 1, 2}, {3}, {4}]
                ]
            )
        wake_train, wake_cal, wake_test = prepared[0]
        # Bound inference cost while allowing enrollment to keep growing. Old
        # recordings stay saved; calibration/test clips are never fitted.
        if len(wake_train) > 100:
            wake_train = [
                wake_train[index] for index in np.linspace(0, len(wake_train) - 1, 100).astype(int)
            ]
        _, negative_cal, negative_test = prepared[1]
        if any(
            sum(item is not None for item in subset) < 2 for subset in [negative_cal, negative_test]
        ):
            raise NishaError(
                "Record more short non-wake speech; silence alone cannot validate false wake rejection."
            )
        if any(item is None for item in wake_train + wake_cal + wake_test):
            raise NishaError(
                "A wake recording has too little speech or is too long. Record short standalone wakes."
            )
        model = PersonalWakeModel(wake_train, 0)
        positive_scores = [model.score(item) for item in wake_cal]
        negative_scores = [model.score(item) for item in negative_cal]
        positive_max, negative_min = max(positive_scores), min(negative_scores)
        if not np.isfinite(positive_max) or positive_max * 1.05 >= min(negative_min * 0.9, 5):
            raise NishaError(
                "Wake and non-wake recordings overlap. Add varied clean wake takes and confusing non-wake examples; the previous model stays active."
            )
        # Use the margin between held-out calibration classes. A five-percent
        # padding around clean wakes rejected quieter real pronunciations.
        margin = (
            (positive_max + negative_min) / 2 if np.isfinite(negative_min) else positive_max * 1.5
        )
        model.threshold = max(0.00001, min(margin, 4.9))
        hits = sum(model.score(item) <= model.threshold for item in wake_test)
        false_alarms = sum(model.score(item) <= model.threshold for item in negative_test)
        report = {
            "wake_test_hits": hits,
            "wake_test_total": len(wake_test),
            "negative_test_false_alarms": false_alarms,
            "negative_test_total": len(negative_test),
            "threshold": model.threshold,
            "type": "personal_mfcc_dtw_wake_classifier",
            "whisper_weights_retrained": False,
            "wake_samples": len(groups[0]),
            "non_wake_samples": len(groups[1]),
            "training_templates": len(wake_train),
            "calibration_wakes": len(wake_cal),
            "calibration_non_wakes": len(negative_cal),
            "activated": hits == len(wake_test) and false_alarms == 0,
        }
        self.root.joinpath("training-report.json").write_text(
            json.dumps(report, indent=2), encoding="utf-8"
        )
        if hits != len(wake_test) or false_alarms:
            raise NishaError(
                "Held-out wake testing failed. Add more varied samples and retrain; the previous model stays active."
            )
        temporary = self.model_path.with_suffix(".tmp")
        with temporary.open("wb") as target:
            np.savez_compressed(
                target,
                count=len(wake_train),
                threshold=model.threshold,
                **{f"template_{index}": item for index, item in enumerate(wake_train)},
            )
        temporary.replace(self.model_path)
        return report

    def train_neural(self):
        """Fit neural weights on reviewed clips; activate only after held-out checks."""
        from nisha.listening import WakeGate
        from nisha.neural_wake import train_model

        entries = self.entries()
        gate = WakeGate()
        groups = [
            [e for e in entries if e["kind"] == "wake"],
            [e for e in entries if e["kind"] == "negative" or
             (e["kind"] == "command" and not gate.pattern.search(e["text"]))],
        ]
        if any(len(group) < 10 for group in groups):
            raise NishaError("Save at least 10 wake and 10 non-wake speech recordings first.")
        split = [
            [[features(self.audio(e)) for i, e in enumerate(group) if i % 5 in slots]
             for slots in [{0, 1, 2}, {3}, {4}]]
            for group in groups
        ]
        (wake_train, wake_cal, wake_test), (negative_train, negative_cal, negative_test) = split
        if any(x is None for x in wake_train + wake_cal + wake_test):
            raise NishaError("A wake recording has too little speech or is too long.")
        if any(sum(x is not None for x in items) < 2 for items in
               [negative_cal, negative_test]):
            raise NishaError("Record more short non-wake speech for validation.")
        model = train_model(wake_train, negative_train, wake_cal, negative_cal)
        hits = sum(model.score(x) >= model.threshold for x in wake_test)
        false_alarms = sum(model.score(x) >= model.threshold for x in negative_test)
        report = {
            "type": "neural_mfcc_mlp_wake_classifier",
            "wake_samples": len(groups[0]), "non_wake_samples": len(groups[1]),
            "training_wakes": len(wake_train), "training_non_wakes": len(negative_train),
            "calibration_wakes": len(wake_cal), "calibration_non_wakes": len(negative_cal),
            "wake_test_hits": hits, "wake_test_total": len(wake_test),
            "negative_test_false_alarms": false_alarms,
            "negative_test_total": len(negative_test),
            "threshold": model.threshold,
            "activated": hits == len(wake_test) and false_alarms == 0,
            "whisper_weights_retrained": False,
        }
        (self.root / "neural-training-report.json").write_text(
            json.dumps(report, indent=2), encoding="utf-8"
        )
        if not report["activated"]:
            raise NishaError("Neural wake held-out test failed; collect more varied recordings. The current detector stays active.")
        temporary = self.neural_model_path.with_suffix(".tmp")
        with temporary.open("wb") as target:
            np.savez_compressed(target, threshold=model.threshold, mean=model.mean,
                                scale=model.scale,
                                **{f"w{i}": w for i, w in enumerate(model.weights)},
                                **{f"b{i}": b for i, b in enumerate(model.biases)})
        temporary.replace(self.neural_model_path)
        return report

"""Small trainable neural wake classifier over the existing MFCC features."""

from itertools import pairwise

import numpy as np

from nisha.errors import NishaError
from nisha.voice_profile import features


def vector(mfcc):
    if mfcc is None:
        return None
    positions = np.linspace(0, len(mfcc) - 1, 8)
    pooled = np.stack([np.interp(positions, np.arange(len(mfcc)), mfcc[:, i]) for i in range(26)])
    return np.concatenate([pooled.ravel(), mfcc.mean(axis=0), mfcc.std(axis=0)]).astype(np.float32)


class NeuralWakeModel:
    def __init__(self, weights, biases, mean, scale, threshold):
        self.weights, self.biases = weights, biases
        self.mean, self.scale, self.threshold = mean, scale, float(threshold)

    def score(self, mfcc):
        item = vector(mfcc)
        if item is None:
            return 0.0
        x = np.clip((item - self.mean) / self.scale, -5, 5)
        for weight, bias in zip(self.weights[:-1], self.biases[:-1]):
            x = np.maximum(x @ weight + bias, 0)
        logit = (x @ self.weights[-1] + self.biases[-1]).item()
        return float(1 / (1 + np.exp(-np.clip(logit, -30, 30))))

    def matches(self, audio):
        return self.score(features(audio)) >= self.threshold

    @classmethod
    def load(cls, path):
        with np.load(path, allow_pickle=False) as saved:
            sizes = [260, 32, 16, 1]
            weights = [saved[f"w{i}"] for i in range(3)]
            biases = [saved[f"b{i}"] for i in range(3)]
            mean, scale = saved["mean"], saved["scale"]
            threshold = float(saved["threshold"])
            if (mean.shape != (260,) or scale.shape != (260,) or
                any(w.shape != (sizes[i], sizes[i + 1]) or b.shape != (sizes[i + 1],)
                    for i, (w, b) in enumerate(zip(weights, biases))) or
                not all(np.isfinite(v).all() for v in [*weights, *biases, mean, scale]) or
                np.any(scale <= 0) or not 0 < threshold < 1):
                raise NishaError("Invalid neural wake model.")
            return cls(weights, biases, mean, scale, threshold)


def train_model(positive, negative, calibration_positive, calibration_negative, epochs=300):
    if any(vector(item) is None for item in positive + calibration_positive):
        raise NishaError("A wake recording has too little speech or is too long.")
    x_pos = np.stack([vector(item) for item in positive])
    x_neg = np.stack([vector(item) for item in negative if vector(item) is not None])
    if len(x_pos) < 6 or len(x_neg) < 6:
        raise NishaError("More valid wake and non-wake recordings are needed for neural training.")
    x = np.concatenate([x_pos, x_neg])
    y = np.concatenate([np.ones((len(x_pos), 1)), np.zeros((len(x_neg), 1))]).astype(np.float32)
    mean = x.mean(axis=0)
    scale = np.maximum(x.std(axis=0), 0.1)
    x = np.clip((x - mean) / scale, -5, 5)
    rng = np.random.default_rng(17)
    sizes = [260, 32, 16, 1]
    weights = [(rng.normal(size=(a, b)) * np.sqrt(2 / a)).astype(np.float32)
               for a, b in pairwise(sizes)]
    biases = [np.zeros(b, dtype=np.float32) for b in sizes[1:]]
    m = [np.zeros_like(p) for p in [*weights, *biases]]
    v = [np.zeros_like(p) for p in [*weights, *biases]]
    sample_weights = np.where(y > 0, 0.5 / len(x_pos), 0.5 / len(x_neg))
    for step in range(1, epochs + 1):
        noisy = x + rng.normal(0, 0.08, x.shape).astype(np.float32)
        activations = [noisy]
        for w, b in zip(weights[:-1], biases[:-1]):
            activations.append(np.maximum(activations[-1] @ w + b, 0))
        logits = activations[-1] @ weights[-1] + biases[-1]
        probability = 1 / (1 + np.exp(-np.clip(logits, -30, 30)))
        delta = (probability - y) * sample_weights
        grad_w, grad_b = [None] * 3, [None] * 3
        for layer in range(2, -1, -1):
            grad_w[layer] = activations[layer].T @ delta + 0.0001 * weights[layer]
            grad_b[layer] = delta.sum(axis=0)
            if layer:
                delta = (delta @ weights[layer].T) * (activations[layer] > 0)
        params = [*weights, *biases]
        for i, (param, grad) in enumerate(zip(params, [*grad_w, *grad_b])):
            m[i] = 0.9 * m[i] + 0.1 * grad
            v[i] = 0.999 * v[i] + 0.001 * grad * grad
            param -= 0.003 * (m[i] / (1 - 0.9**step)) / (np.sqrt(v[i] / (1 - 0.999**step)) + 1e-8)
    model = NeuralWakeModel(weights, biases, mean.astype(np.float32), scale.astype(np.float32), 0.5)
    positive_scores = [model.score(item) for item in calibration_positive]
    negative_scores = [model.score(item) for item in calibration_negative if vector(item) is not None]
    if not negative_scores or min(positive_scores) <= max(negative_scores):
        raise NishaError("Neural wake calibration overlaps non-wake speech; collect more varied takes.")
    # Favor wake recall while staying above every calibration false alarm.
    model.threshold = max(negative_scores) + 0.1 * (min(positive_scores) - max(negative_scores))
    return model

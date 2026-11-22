"""Small neural reward model for reply presentation, trained from explicit ratings."""

import hashlib
import math
import random
import re
from itertools import pairwise

DIMENSIONS = 128
HIDDEN = 16


def features(prompt, context, arm):
    words = re.findall(r"[a-z0-9]+", prompt.casefold())[:80]
    tokens = ["context:" + context, "arm:" + arm, *words]
    tokens += ["pair:" + a + ":" + b for a, b in pairwise(words)]
    tokens += ["arm:" + arm + ":" + word for word in words]
    result = {0: 1.0}
    for token in tokens:
        index = 1 + int.from_bytes(
            hashlib.blake2b(token.encode(), digest_size=4).digest(), "big"
        ) % (DIMENSIONS - 1)
        result[index] = min(result.get(index, 0.0) + 0.25, 2.0)
    return result


def _forward(weights, vector):
    hidden = [
        math.tanh(weights["hidden_bias"][unit] + sum(
            weights["input"][index][unit] * value for index, value in vector.items()
        ))
        for unit in range(HIDDEN)
    ]
    logit = weights["output_bias"] + sum(
        hidden[unit] * weights["output"][unit] for unit in range(HIDDEN)
    )
    estimate = 1 / (1 + math.exp(-max(-20, min(20, logit))))
    return estimate, hidden


def predict(weights, prompt, context, arm):
    return _forward(weights, features(prompt, context, arm))[0]


def train(rows):
    """Return a neural model only when it beats an arm-only held-out baseline."""
    if (
        len(rows) < 30
        or sum(row["reward"] for row in rows) < 8
        or sum(1 - row["reward"] for row in rows) < 8
    ):
        return None
    prompts = sorted({row["prompt"] for row in rows})
    if len(prompts) < 12:
        return None
    random.Random(17).shuffle(prompts)
    fit_prompts = set(prompts[: int(len(prompts) * 0.8)])
    fit = [row for row in rows if row["prompt"] in fit_prompts]
    heldout = [row for row in rows if row["prompt"] not in fit_prompts]
    if len(heldout) < 6:
        return None
    rng = random.Random(23)
    weights = {
        "input": [[rng.uniform(-0.08, 0.08) for _ in range(HIDDEN)] for _ in range(DIMENSIONS)],
        "hidden_bias": [0.0] * HIDDEN,
        "output": [rng.uniform(-0.08, 0.08) for _ in range(HIDDEN)],
        "output_bias": 0.0,
    }
    prepared = [
        (features(row["prompt"], row["context"], row["arm"]), row["reward"])
        for row in fit
    ]
    for _ in range(80):
        rng.shuffle(prepared)
        for vector, reward in prepared:
            estimate, hidden = _forward(weights, vector)
            delta = estimate - reward
            old_output = weights["output"][:]
            for unit in range(HIDDEN):
                weights["output"][unit] -= 0.03 * (delta * hidden[unit] + 0.001 * old_output[unit])
            weights["output_bias"] -= 0.03 * delta
            for unit in range(HIDDEN):
                back = delta * old_output[unit] * (1 - hidden[unit] ** 2)
                weights["hidden_bias"][unit] -= 0.03 * back
                for index, value in vector.items():
                    weights["input"][index][unit] -= 0.03 * (
                        back * value + 0.001 * weights["input"][index][unit]
                    )
    arms = {row["arm"] for row in fit}
    arm_rates = {}
    for arm in arms:
        outcomes = [item["reward"] for item in fit if item["arm"] == arm]
        arm_rates[arm] = (1 + sum(outcomes)) / (2 + len(outcomes))
    baseline = sum(
        (item["reward"] - arm_rates.get(item["arm"], 0.5)) ** 2 for item in heldout
    ) / len(heldout)
    learned = sum(
        (item["reward"] - predict(weights, item["prompt"], item["context"], item["arm"])) ** 2
        for item in heldout
    ) / len(heldout)
    if learned >= baseline - 0.005:
        return None
    return {
        "architecture": "hashed_words_128_tanh_16_sigmoid_1",
        "weights": weights,
        "samples": len(rows),
        "heldout_brier": learned,
        "baseline_brier": baseline,
    }

from nisha.answer_quality import predict, train


def test_reward_model_learns_question_specific_preference():
    rows = []
    for number in range(60):
        short = number % 2 == 0
        arm = "direct" if number % 4 < 2 else "example"
        rows.append({
            "context": "explanation",
            "prompt": f"Explain {'briefly' if short else 'with illustration'} topic {number}",
            "arm": arm,
            "reward": int((short and arm == "direct") or (not short and arm == "example")),
        })
    model = train(rows)
    assert model is not None
    assert model["heldout_brier"] < model["baseline_brier"]
    assert predict(model["weights"], "Explain briefly a new topic", "explanation", "direct") > predict(
        model["weights"], "Explain briefly a new topic", "explanation", "example"
    )


def test_reward_model_waits_for_real_varied_feedback():
    assert train([]) is None
    repeated = [{"context": "explanation", "prompt": "same", "arm": "direct", "reward": 1}] * 40
    assert train(repeated) is None

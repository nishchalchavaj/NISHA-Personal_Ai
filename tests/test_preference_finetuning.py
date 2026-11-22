from scripts.finetune_preferences import MIN_PAIRS, prepare


def test_reviewed_pairs_split_by_question_without_leakage():
    pairs = [
        {"prompt": f"Question {index}", "chosen": f"Preferred {index}",
         "rejected": f"Old {index}"}
        for index in range(MIN_PAIRS)
    ]
    training, validation, ready = prepare(pairs)
    assert ready
    assert len(training) + len(validation) == MIN_PAIRS
    assert {row["prompt"][0]["content"] for row in training}.isdisjoint(
        {row["prompt"][0]["content"] for row in validation}
    )
    assert training[0]["chosen"][0]["role"] == "assistant"


def test_duplicate_or_unreviewed_sized_dataset_cannot_start_training():
    duplicate = {"prompt": "Same", "chosen": "Good", "rejected": "Bad"}
    training, validation, ready = prepare([duplicate] * 50)
    assert not ready and len(training) == 1 and not validation
    assert prepare([]) == ([], [], False)

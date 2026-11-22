"""Prepare reviewed NISHA preference pairs and optionally train a local DPO LoRA adapter."""

import argparse
import hashlib
import json
from pathlib import Path

from nisha.reinforcement import Reinforcement
from nisha.settings import load_settings
from nisha.storage import Store

MIN_PAIRS = 30
BASE_MODEL = "meta-llama/Llama-3.2-3B-Instruct"


def prepare(pairs):
    """Deduplicate reviewed comparisons and split by prompt to avoid evaluation leakage."""
    clean = {}
    for pair in pairs:
        prompt = pair["prompt"].strip()
        chosen = pair["chosen"].strip()
        rejected = pair["rejected"].strip()
        if not prompt or not chosen or not rejected or chosen == rejected:
            continue
        key = (prompt, chosen, rejected)
        clean[key] = {
            "prompt": [{"role": "user", "content": prompt}],
            "chosen": [{"role": "assistant", "content": chosen}],
            "rejected": [{"role": "assistant", "content": rejected}],
        }
    prompts = sorted({key[0] for key in clean}, key=lambda text: hashlib.sha256(text.encode()).digest())
    if len(clean) < MIN_PAIRS or len(prompts) < 12:
        return list(clean.values()), [], False
    training_prompts = set(prompts[: int(len(prompts) * 0.8)])
    train = [example for key, example in clean.items() if key[0] in training_prompts]
    validation = [example for key, example in clean.items() if key[0] not in training_prompts]
    return train, validation, len(train) >= 24 and len(validation) >= 6


def train_adapter(train_rows, validation_rows, model_id, destination):
    try:
        import torch
        from datasets import Dataset
        from peft import LoraConfig
        from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
        from trl import DPOConfig, DPOTrainer
    except ImportError as exc:
        raise SystemExit(
            "Fine-tuning packages are missing. Install the optional dependencies in docs/preference-finetuning.md."
        ) from exc
    if not torch.cuda.is_available():
        raise SystemExit("A CUDA GPU is required for this 4-bit local training recipe.")
    destination.mkdir(parents=True, exist_ok=True)
    tokenizer = AutoTokenizer.from_pretrained(model_id)
    tokenizer.pad_token = tokenizer.eos_token
    model = AutoModelForCausalLM.from_pretrained(
        model_id,
        device_map="auto",
        quantization_config=BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_compute_dtype=torch.float16,
        ),
    )
    model.config.use_cache = False
    config = DPOConfig(
        output_dir=str(destination / "checkpoints"),
        num_train_epochs=1,
        per_device_train_batch_size=1,
        per_device_eval_batch_size=1,
        gradient_accumulation_steps=8,
        learning_rate=1e-5,
        max_length=1024,
        fp16=True,
        gradient_checkpointing=True,
        eval_strategy="epoch",
        save_strategy="epoch",
        report_to="none",
        seed=17,
    )
    trainer = DPOTrainer(
        model=model,
        args=config,
        train_dataset=Dataset.from_list(train_rows),
        eval_dataset=Dataset.from_list(validation_rows),
        processing_class=tokenizer,
        peft_config=LoraConfig(
            r=8,
            lora_alpha=16,
            lora_dropout=0.05,
            bias="none",
            task_type="CAUSAL_LM",
            target_modules="all-linear",
        ),
    )
    trainer.train()
    trainer.save_model(str(destination / "adapter"))
    tokenizer.save_pretrained(destination / "adapter")
    metrics = trainer.evaluate()
    (destination / "report.json").write_text(
        json.dumps({"base_model": model_id, "train_pairs": len(train_rows),
                    "validation_pairs": len(validation_rows), "metrics": metrics}, indent=2),
        encoding="utf-8",
    )
    return metrics


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["check", "train"])
    parser.add_argument("--base-model", default=BASE_MODEL)
    args = parser.parse_args()
    settings = load_settings()
    pairs = Reinforcement(Store(settings.data_dir / "nisha.sqlite3")).preference_pairs()
    train_rows, validation_rows, ready = prepare(pairs)
    print(json.dumps({"reviewed_pairs": len(pairs), "training_pairs": len(train_rows),
                      "validation_pairs": len(validation_rows), "ready": ready}, indent=2))
    if args.action == "check":
        return
    if not ready:
        raise SystemExit(
            "More reviewed chosen/rejected comparisons are needed: at least 30 across 12 questions, "
            "with at least 6 held-out pairs. No model was changed."
        )
    destination = Path(settings.data_dir) / "preference_finetuning" / "llama3.2-dpo"
    metrics = train_adapter(train_rows, validation_rows, args.base_model, destination)
    print(json.dumps({"adapter": str(destination / "adapter"), "metrics": metrics}, indent=2))


if __name__ == "__main__":
    main()

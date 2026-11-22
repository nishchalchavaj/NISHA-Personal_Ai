# Fine-tuning NISHA's conversation model from reviewed preferences

NISHA's everyday local model is Ollama `llama3.2` (3.2B parameters). This
workflow trains a LoRA adapter for the corresponding Llama 3.2 3B Instruct
weights using Direct Preference Optimization (DPO). The larger `qwen3:14b`
profile is outside this small-GPU recipe.

Only explicit, reviewed comparisons enter training: the same question, NISHA's
original answer, and a better answer that you accepted in **Response learning and
teacher answers**. Simple good/bad ratings do not create chosen/rejected pairs.
Those ratings continue training the separate answer-presentation network.
Personal details and stated response preferences are saved in NISHA's local memory
and applied immediately during generation. They are not copied into model weights
or converted into invented preference comparisons.

Check the dataset without installing training packages:

```powershell
.\.venv\Scripts\python.exe scripts\finetune_preferences.py check
```

Training requires at least 30 distinct reviewed comparisons covering at least
12 different questions and leaving at least 6 pairs for validation. The script
splits by question, so another comparison of a training question cannot leak
into validation. It will stop before loading a model if the dataset is too small.

Once enough comparisons exist, create a separate training environment. Install
a CUDA-enabled PyTorch build using the [official Windows selector](https://pytorch.org/get-started/locally/),
then install `trl[peft]`, `datasets`, `bitsandbytes`, and `accelerate` as described
in the [TRL PEFT guide](https://huggingface.co/docs/trl/peft_integration).
Access to the [Llama 3.2 3B Instruct weights](https://huggingface.co/meta-llama/Llama-3.2-3B-Instruct)
is needed; Ollama's existing quantized `llama3.2` files are inference weights and
are not used as the training source. Run `train` with that environment's Python:

```powershell
python scripts\finetune_preferences.py train
```

The script uses 4-bit loading and trains LoRA weights locally. It writes an adapter
and held-out evaluation metrics under `data/preference_finetuning/llama3.2-dpo`.
This directory is excluded from Git. Training does not automatically change the
active assistant model; inspect the validation result and test the adapted model
before choosing it for NISHA. The model also retains the base model's limitations:
preference fine-tuning does not prove factual correctness or grant action permissions.

The data format and training call follow the [Hugging Face DPO trainer documentation](https://huggingface.co/docs/trl/dpo_trainer).

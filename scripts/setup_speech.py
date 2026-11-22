"""Download configured speech weights once; live inference stays offline."""

import os
from pathlib import Path

os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")

from huggingface_hub import snapshot_download

from nisha.settings import ROOT, load_settings


def main():
    settings = load_settings()
    destination = ROOT / settings.voice.model
    if not settings.voice.model.startswith("data/models/"):
        raise SystemExit("This installer expects voice.model under data/models/.")
    if (destination / "model.bin").is_file():
        print("Speech weights already installed:", destination)
        return
    destination.mkdir(parents=True, exist_ok=True)
    snapshot_download(
        repo_id="Systran/faster-whisper-large-v3",
        local_dir=str(Path(destination).resolve()),
        allow_patterns=[
            "model.bin",
            "config.json",
            "tokenizer.json",
            "vocabulary.json",
            "preprocessor_config.json",
        ],
    )
    print("Local large-v3 speech weights ready:", destination)


if __name__ == "__main__":
    main()

import os
from pathlib import Path
from urllib.parse import urlparse

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field, model_validator

from nisha.errors import ConfigurationError

ROOT = Path(__file__).resolve().parents[1]


def loopback_url(value: str) -> str:
    parsed = urlparse(value)
    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
    ):
        raise ValueError("NISHA model services must use a loopback URL without credentials.")
    return value.rstrip("/")


class ModelProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model: str = Field(min_length=1)
    local: bool
    context_window: int = Field(ge=1024, le=2_000_000)
    max_output: int = Field(ge=32, le=32_000)

    @model_validator(mode="after")
    def validate_limits(self):
        if self.max_output + 512 >= self.context_window:
            raise ValueError("Reserve at least 512 tokens for input and instructions.")
        # 'local' is an enforced provider constraint, never an arbitrary label.
        if self.local and not self.model.startswith("ollama_chat/"):
            raise ValueError(
                "Local profiles must use ollama_chat/ through the local Ollama service."
            )
        if self.local and (":cloud" in self.model.lower() or "-cloud" in self.model.lower()):
            raise ValueError("Cloud-backed Ollama models cannot be used as local models.")
        if not self.local and self.model.startswith(("ollama/", "ollama_chat/")):
            raise ValueError("Ollama profiles must be marked local.")
        return self

    @property
    def input_budget(self):
        return self.context_window - self.max_output - 128


class VoiceSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model: str = "small"
    device: str = "cpu"
    compute_type: str = "int8"
    sample_rate: int = Field(default=16000, ge=16000, le=16000)
    record_seconds: int = Field(default=6, ge=1, le=30)
    microphone: int | None = None
    auto_microphone: bool = False
    rate: int = Field(default=175, ge=80, le=300)
    voice_locale: str | None = None
    continuous_listening: bool = True
    wake_word: str = Field(default="nisha", min_length=1, max_length=30)
    wake_aliases: list[str] = Field(
        default_factory=lambda: ["nisha", "neesha", "nishaa", "nisa", "meesha", "निशा"]
    )
    follow_up_seconds: int = Field(default=120, ge=0, le=3600)
    language: str | None = "en"
    beam_size: int = Field(default=8, ge=1, le=10)
    hotwords: str = "Nisha, Neesha, Nishaa, Nisa, Meesha, YouTube, Google, Notepad, Microsoft Word, email, Python, GitHub, Claude, Chrome, Premiere Pro, Adobe After Effects, Arduino IDE, Blender, Spotify"
    use_speech_vad: bool = True
    vad_threshold: float = Field(default=0.45, ge=0.1, le=0.9)
    min_confidence: float = Field(default=-0.65, ge=-2, le=0)
    wake_min_confidence: float = Field(default=-1.3, ge=-2, le=0)
    decode_timeout: int = Field(default=20, ge=3, le=120)
    silence_seconds: float = Field(default=0.8, ge=0.3, le=3)
    max_utterance_seconds: int = Field(default=30, ge=3, le=120)
    speech_threshold: float = Field(default=0.012, gt=0, le=1)


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    gateway_url: str = "http://127.0.0.1:4000"
    ollama_url: str = "http://127.0.0.1:11434"
    data_dir: Path = ROOT / "data"
    request_timeout: int = Field(default=90, ge=5, le=300)
    recent_exchanges: int = Field(default=6, ge=1, le=30)
    external_tasks_enabled: bool = False
    history_retention_days: int = Field(default=30, ge=1, le=3650)
    models: dict[str, ModelProfile]
    voice: VoiceSettings = Field(default_factory=VoiceSettings)
    contacts: dict[str, str] = Field(default_factory=dict)
    apps: dict[str, str] = Field(default_factory=dict)
    online_visuals: bool = True
    vision_model: str = "moondream"
    idle_checkins: bool = True
    instant_smalltalk: bool = True
    background_actions: bool = True
    idle_checkin_seconds: int = Field(default=300, ge=30, le=1800)

    @model_validator(mode="after")
    def validate_services(self):
        self.gateway_url = loopback_url(self.gateway_url)
        self.ollama_url = loopback_url(self.ollama_url)
        if not self.vision_model or any(
            marker in self.vision_model.casefold() for marker in (":cloud", "-cloud", "http", "/")
        ):
            raise ValueError("Vision requires a locally installed Ollama model name.")
        if "local_fast" not in self.models or not self.models["local_fast"].local:
            raise ValueError("A local_fast Ollama model is required.")
        if not self.external_tasks_enabled and any(
            not model.local for model in self.models.values()
        ):
            raise ValueError(
                "External models require external_tasks_enabled; base chat remains local."
            )
        if any(not name.replace("_", "").isalnum() for name in self.models):
            raise ValueError("Model aliases may contain only letters, numbers and underscores.")
        return self


def load_settings(path: Path | None = None) -> Settings:
    load_dotenv(ROOT / ".env", override=False)
    try:
        source = path or ROOT / "config" / "nisha.yaml"
        raw = yaml.safe_load(source.read_text(encoding="utf-8"))
        task_model = os.getenv("NISHA_TASK_MODEL", "").strip()
        if task_model and raw.get("external_tasks_enabled", False):
            raw["models"]["external_task"] = {
                "model": task_model,
                "local": False,
                "context_window": 8192,
                "max_output": 512,
            }
        settings = Settings.model_validate(raw)
        if not settings.data_dir.is_absolute():
            settings.data_dir = (ROOT / settings.data_dir).resolve()
        return settings
    except (OSError, ValueError, TypeError, KeyError, yaml.YAMLError) as exc:
        raise ConfigurationError(
            "Invalid config/nisha.yaml. Check model profiles and service URLs."
        ) from exc

"""Validated, non-secret user configuration."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def default_data_dir() -> Path:
    override = os.environ.get("JARVIS_DATA_DIR")
    return (
        Path(override)
        if override
        else Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "ProjectJarvis"
    )


class Settings(BaseModel):
    model_config = ConfigDict(validate_assignment=True, extra="forbid")
    data_dir: Path = Field(default_factory=default_data_dir)
    provider: Literal["ollama", "openai", "gemini"] = "ollama"
    model: str = Field(default="", max_length=128)
    ollama_url: str = "http://127.0.0.1:11434"
    cloud_allowed: bool = False
    save_history: bool = False
    mode: Literal["manual", "balanced", "advanced"] = "balanced"
    allowed_roots: list[Path] = Field(default_factory=list)
    request_timeout: float = Field(default=60, ge=1, le=180)
    max_output_tokens: int = Field(default=1024, ge=16, le=8192)
    max_requests_per_session: int = Field(default=30, ge=1, le=1000)
    speech_enabled: bool = False
    speech_voice: str | None = None
    speaker_device: str | None = Field(default=None, max_length=512)
    microphone_device: int | None = None
    speech_model: str = "base.en"
    speech_device: Literal["cpu", "cuda"] = "cpu"
    speech_compute_type: str = "int8"
    wake_enabled: bool = False
    wake_phrase: str = Field(default="hey jarvis", min_length=3, max_length=60)
    input_sensitivity: float = Field(default=0.015, ge=0.001, le=0.2)
    vad_aggressiveness: int = Field(default=2, ge=0, le=3)
    speech_end_silence: float = Field(default=1.0, ge=0.3, le=3)
    speech_start_timeout: float = Field(default=8, ge=2, le=60)
    conversation_timeout: float = Field(default=20, ge=5, le=120)
    maximum_utterance_seconds: float = Field(default=25, ge=3, le=30)
    speech_rate: float = Field(default=0, ge=-1, le=1)
    pronunciation_replacements: dict[str, str] = Field(default_factory=dict)
    greeting_style: Literal["brief", "friendly", "professional", "silent"] = "brief"
    timezone: str = "Asia/Calcutta"
    voice_interruption: bool = False
    proactive_enabled: bool = False
    quiet_start: int = Field(default=22, ge=0, le=23)
    quiet_end: int = Field(default=8, ge=0, le=23)
    proactive_interval_seconds: float = Field(default=300, ge=30, le=86400)
    start_with_windows: bool = False
    minimize_to_tray: bool = False
    history_retention_days: int = Field(default=30, ge=1, le=3650)

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("Choose a valid IANA timezone, such as Asia/Calcutta") from None
        return value

    @field_validator("wake_phrase")
    @classmethod
    def valid_wake_phrase(cls, value: str) -> str:
        value = " ".join(value.lower().split())
        if not any(char.isalpha() for char in value) or not all(
            char.isalpha() or char in " '-" for char in value
        ):
            raise ValueError("Wake phrase must contain spoken words")
        return value

    @field_validator("pronunciation_replacements")
    @classmethod
    def bounded_pronunciations(cls, value: dict[str, str]) -> dict[str, str]:
        if len(value) > 100 or any(
            not key.strip() or len(key) > 80 or not text.strip() or len(text) > 160
            for key, text in value.items()
        ):
            raise ValueError("Use up to 100 short pronunciation replacements")
        return value

    @field_validator("data_dir", "allowed_roots", mode="after")
    @classmethod
    def local_paths(cls, value):
        def validate(path: Path) -> Path:
            if str(path).startswith(("\\\\", "//")):
                raise ValueError("Network shares are not permitted in Phase 1")
            return path.expanduser().resolve()

        return [validate(path) for path in value] if isinstance(value, list) else validate(value)

    @field_validator("ollama_url")
    @classmethod
    def loopback_only(cls, value: str) -> str:
        url = urlsplit(value)
        if url.scheme != "http" or url.hostname not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("Ollama must use an HTTP loopback address")
        if url.username or url.password or url.path not in {"", "/"} or url.query or url.fragment:
            raise ValueError("Ollama URL must contain only a local host and port")
        return value.rstrip("/")

    @model_validator(mode="after")
    def workspace_default(self):
        if not self.allowed_roots:
            # object assignment avoids recursively invoking assignment validation.
            object.__setattr__(self, "allowed_roots", [(self.data_dir / "workspace").resolve()])
        return self


def load_settings(data_dir: Path | str | None = None) -> Settings:
    root = Path(data_dir).resolve() if data_dir is not None else default_data_dir().resolve()
    path = root / "settings.json"
    if path.exists():
        settings = Settings.model_validate_json(path.read_text(encoding="utf-8"))
        settings.data_dir = root
        return settings
    return Settings(data_dir=root)


def save_settings(settings: Settings) -> None:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    target = settings.data_dir / "settings.json"
    temporary = target.with_suffix(".tmp")
    temporary.write_text(settings.model_dump_json(indent=2), encoding="utf-8")
    temporary.replace(target)

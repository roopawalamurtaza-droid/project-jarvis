"""Validated, non-secret user configuration."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

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
    microphone_device: int | None = None
    speech_model: str = "base.en"
    speech_device: Literal["cpu", "cuda"] = "cpu"
    speech_compute_type: str = "int8"
    history_retention_days: int = Field(default=30, ge=1, le=3650)

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

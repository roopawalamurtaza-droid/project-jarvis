"""Build identity and read-only startup health, without recording or speaking."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

from . import __version__


def build_identity() -> dict:
    manifest = Path(__file__).with_name("build_info.json")
    if manifest.is_file():
        data = json.loads(manifest.read_text(encoding="utf-8"))
    else:
        root = Path(__file__).resolve().parents[2]
        try:
            commit = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=root,
                capture_output=True,
                text=True,
                timeout=3,
                check=True,
            ).stdout.strip()
            dirty = bool(
                subprocess.run(
                    ["git", "status", "--porcelain"],
                    cwd=root,
                    capture_output=True,
                    text=True,
                    timeout=3,
                    check=True,
                ).stdout.strip()
            )
        except (OSError, subprocess.SubprocessError):
            commit, dirty = "unavailable", None
        data = {
            "version": __version__,
            "git_commit": commit,
            "build_date_utc": "source checkout",
            "dirty": dirty,
        }
    return {**data, "executable": sys.executable, "frozen": bool(getattr(sys, "frozen", False))}


def startup_health(settings) -> dict:
    packages = {
        name: importlib.util.find_spec(name) is not None
        for name in ("faster_whisper", "webrtcvad", "sounddevice")
    }
    models = settings.data_dir / "speech-models"
    snapshots = models / ("models--Systran--faster-whisper-" + settings.speech_model) / "snapshots"
    model_ready = snapshots.is_dir() and any(
        all((item / name).is_file() for name in ("model.bin", "config.json", "tokenizer.json"))
        for item in snapshots.iterdir()
        if item.is_dir()
    )
    backend = "In-process service ready"
    if settings.provider == "ollama":
        if not settings.model:
            backend = "Select a local AI model in Settings"
        else:
            try:
                import httpx

                with httpx.Client(timeout=3, trust_env=False, follow_redirects=False) as client:
                    reply = client.get(settings.ollama_url + "/api/tags")
                    reply.raise_for_status()
                    models_found = [item.get("name") for item in reply.json().get("models", [])]
                backend = (
                    "Local Ollama connected; selected model installed"
                    if settings.model in models_found
                    else "Ollama connected; selected model not installed"
                )
            except Exception:
                backend = "Ollama unavailable; start Ollama and rerun health check"
    else:
        backend = (
            "Cloud adapter configured; live credentials not tested"
            if settings.cloud_allowed
            else "Cloud permission disabled"
        )
    microphone = (
        "Off; hands-free permission disabled"
        if not settings.wake_enabled
        else "Authorized; see live voice indicator"
    )
    return {
        "packages": packages,
        "speech_model": "offline model ready"
        if model_ready
        else "offline model missing; run explicit download command",
        "wake_engine": "Offline Whisper phrase + WebRTC VAD",
        "wake_permission": settings.wake_enabled,
        "microphone": microphone,
        "backend": backend,
    }

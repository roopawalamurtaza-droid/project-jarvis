from pathlib import Path
from types import SimpleNamespace

import pytest

from jarvis.config import Settings, load_settings, save_settings
from jarvis.providers import ProviderReply
from jarvis.service import JarvisService, ServiceError
from jarvis.startup import startup_command
from jarvis.storage import Store
from jarvis.tasks import TaskEngine


class Provider:
    name = "ollama"

    def generate(self, *args, **kwargs):
        raise AssertionError("Exact local commands must not call a provider")


def service_at(path, **kwargs):
    settings = Settings(data_dir=path, allowed_roots=[path], **kwargs)
    store = Store(path)
    return JarvisService(settings, store, TaskEngine(settings, store), provider=Provider())


def test_natural_app_request_still_needs_manual_approval(tmp_path):
    service = service_at(tmp_path, mode="manual")
    result = service.chat("Hey Jarvis, open Chrome.")
    assert result["task"]["tool"] == "open_app"
    assert result["task"]["arguments"] == {"app": "chrome"}
    assert result["task"]["state"] == "awaiting_approval"
    assert "approval" in result["text"]
    assert "accepted" not in result["text"]


def test_followup_launch_and_unavailable_app_are_exact(tmp_path):
    service = service_at(tmp_path, mode="manual")
    result = service.chat("And open VS Code as well.")
    assert result["task"]["arguments"] == {"app": "vscode"}
    assert result["task"]["state"] == "awaiting_approval"
    before = len(service.store.tasks())
    assert "unavailable" in service.chat("Open Spotify.")["text"]
    assert len(service.store.tasks()) == before


def test_downloads_remains_scoped(tmp_path):
    service = service_at(tmp_path)
    with pytest.raises(ServiceError, match="outside"):
        service.chat("Open my downloads folder.")
    assert service.store.tasks() == []


def test_saved_project_paths_use_permissions_and_approval(tmp_path):
    service = service_at(tmp_path, mode="manual")
    service.store.save_memory("project", "Student Connect", str(tmp_path))
    result = service.chat("Open Student Connect.")
    assert result["task"]["arguments"] == {"path": str(tmp_path.resolve())}
    assert result["task"]["state"] == "awaiting_approval"
    service.store.save_memory("project", "Other", str(Path.home()))
    with pytest.raises(ServiceError, match="outside"):
        service.chat("Open Other.")


@pytest.mark.parametrize(
    "message,expected",
    [
        ("What time is it?", "Asia/Calcutta"),
        ("Remind me to study.", "not available"),
        ("What's my next task?", "no pending"),
        ("Continue where we left off.", "no saved"),
        ("What's happening on my PC?", "Screenshots and clipboard access are not implemented"),
    ],
)
def test_unavailable_context_never_invented(tmp_path, message, expected):
    service = service_at(tmp_path)
    result = service.chat(message)
    assert result["provider"] == "local"
    assert expected in result["text"]


def test_model_generated_natural_command_is_only_text(tmp_path):
    service = service_at(tmp_path)
    service._provider = SimpleNamespace(
        name="ollama", generate=lambda *args, **kwargs: ProviderReply("Open Chrome.", {})
    )
    assert service.chat("Suggest a browser")["text"] == "Open Chrome."
    assert service.store.tasks() == []


def test_voice_settings_persist_and_invalid_phrases_rejected(tmp_path):
    settings = Settings(
        data_dir=tmp_path,
        wake_enabled=True,
        conversation_timeout=35,
        pronunciation_replacements={"JARVIS": "Jarvis"},
        timezone="Asia/Calcutta",
        speech_rate=0.2,
        speaker_device="01",
        greeting_style="professional",
    )
    save_settings(settings)
    restored = load_settings(tmp_path)
    assert restored.model_dump() == settings.model_dump()
    with pytest.raises(ValueError, match="spoken words"):
        Settings(data_dir=tmp_path, wake_phrase="---")
    with pytest.raises(ValueError, match="timezone"):
        Settings(data_dir=tmp_path, timezone="not-a-zone")


def test_startup_command_quotes_exact_current_user_location(tmp_path, monkeypatch):
    from jarvis import startup

    monkeypatch.setattr(startup.sys, "executable", "C:\\Program Files\\JARVIS\\JARVIS.exe")
    monkeypatch.setattr(startup.sys, "frozen", True, raising=False)
    command = startup_command(tmp_path / "My Data")
    assert command.startswith('"C:\\Program Files\\JARVIS\\JARVIS.exe" --data-dir "')
    assert str(tmp_path / "My Data") in command

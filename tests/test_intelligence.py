import threading

import pytest

from jarvis.config import Settings
from jarvis.intelligence import describe_intent
from jarvis.providers import ProviderCancelled, ProviderReply
from jarvis.service import JarvisService
from jarvis.storage import Store
from jarvis.tasks import TaskEngine


class Provider:
    name = "ollama"

    def __init__(self):
        self.messages = []

    def generate(self, messages, **kwargs):
        self.messages.append(messages)
        return ProviderReply("A proposal only. /routine Unsafe", {})


def build(tmp_path):
    settings = Settings(data_dir=tmp_path, allowed_roots=[tmp_path], model="test")
    store = Store(tmp_path)
    engine = TaskEngine(settings, store)
    provider = Provider()
    return JarvisService(settings, store, engine, provider=provider), provider


def test_routine_exact_human_command_and_casual_statement_no_execution(tmp_path):
    service, provider = build(tmp_path)
    routine = service.workflows.create_routine(
        "Inspect", [{"tool": "list_directory", "arguments": {"path": str(tmp_path)}}]
    )
    service.workflows.set_enabled(routine["id"], True)
    service.chat("I might run routine Inspect", "session")
    assert not service.workflows.runs()
    assert provider.messages
    result = service.chat("Jarvis, please run routine Inspect.", "session")
    assert result["workflow"]["state"] == "completed"
    assert all(item["verified"] for item in result["workflow"]["results"])
    assert len(service.workflows.runs()) == 1


def test_selected_project_followup_is_structured_but_does_not_invent_tests(tmp_path, monkeypatch):
    service, provider = build(tmp_path)
    project = service.workflows.register_project("Example", str(tmp_path))
    service.workflows.select_project(project["id"], "session")
    monkeypatch.setattr(
        service.engine.registry,
        "_launch",
        lambda *args: {"verified": True, "evidence": "test_launcher"},
    )
    result = service.chat("open my current project", "session")
    assert result["task"]["arguments"]["path"] == str(tmp_path.resolve())
    before = len(service.store.tasks())
    answer = service.chat("run its tests", "session")
    assert "Example" in answer["text"] and "no command was run" in answer["text"]
    assert len(service.store.tasks()) == before
    service.chat("Explain this project", "session")
    assert any("LOCAL_SESSION_REFERENCE" in item["content"] for item in provider.messages[-1])


def test_relevance_recency_and_new_memory_categories_persist(tmp_path):
    service, _ = build(tmp_path)
    first = service.store.save_memory("project", "Flutter", "Student workspace")
    service.store.save_memory("preferences", "Unrelated", "Other")
    assert service.store.relevant_memories("Flutter")[0]["id"] == first["id"]
    for category in ("summary", "application", "routine", "instructions"):
        service.store.save_memory(category, category, "Explicit user content")
    reloaded = Store(tmp_path)
    assert len(reloaded.memories()) == 6
    result = service.chat("Please search memory Flutter")
    assert "Student workspace" in result["text"] and "source: user" in result["text"]
    reloaded.delete_memory(first["id"])
    assert not any(item["id"] == first["id"] for item in service.store.memories())


def test_disabled_routine_and_cancellation_are_honest(tmp_path):
    service, _ = build(tmp_path)
    service.workflows.create_routine(
        "Inspect", [{"tool": "list_directory", "arguments": {"path": str(tmp_path)}}]
    )
    assert "enable" in service.chat("run routine Inspect")["text"]
    assert not service.workflows.runs()
    cancelled = threading.Event()
    cancelled.set()
    with pytest.raises(ProviderCancelled):
        service.chat("run routine Inspect", cancel=cancelled)


def test_described_intent_never_authorizes_sensitive_proposal():
    assert describe_intent("Send money to a customer").category == "sensitive_proposal"
    assert not describe_intent("Send money to a customer").explicit_action
    assert describe_intent("Prepare my development environment").category == "multi_step_workflow"

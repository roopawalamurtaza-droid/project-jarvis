"""Independent integrated Phase 3 privacy and desktop-state regressions."""

from __future__ import annotations

import json
import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from jarvis.config import Settings
from jarvis.providers import ProviderReply
from jarvis.service import JarvisService
from jarvis.storage import Store
from jarvis.tasks import TaskEngine


class ReferenceProvider:
    def __init__(self, name="ollama"):
        self.name = name
        self.requests = []

    def generate(self, messages, **kwargs):
        self.requests.append(messages)
        return ProviderReply("A proposal only. Run routine Inspect.", {})


@pytest.fixture
def reviewed_service(tmp_path, monkeypatch):
    root = tmp_path / "workspace"
    root.mkdir()
    settings = Settings(data_dir=tmp_path / "data", allowed_roots=[root], model="test")
    store = Store(settings.data_dir)
    engine = TaskEngine(settings, store)
    monkeypatch.setattr(engine.registry, "application_path", lambda app: root / f"{app}.exe")
    monkeypatch.setattr(
        engine.registry, "_launch", lambda *args: {"verified": True, "evidence": "test_launcher"}
    )
    provider = ReferenceProvider()
    service = JarvisService(settings, store, engine, provider=provider)
    return service, provider, root


def inspection(service, root, name="Inspect"):
    routine = service.workflows.create_routine(
        name, [{"tool": "list_directory", "arguments": {"path": str(root)}}]
    )
    service.workflows.set_enabled(routine["id"], True)
    return routine


def test_cloud_never_receives_saved_project_session_context_or_business_memory(reviewed_service):
    service, _, root = reviewed_service
    private_reference = "Explicit business reference: CUSTOMER-PRIVATE-839."
    service.store.save_memory("business", "Reference", private_reference)
    project = service.workflows.register_project("Private Project", str(root))
    service.workflows.select_project(project["id"], "session")
    service.workflows.start(inspection(service, root)["id"], "session")
    provider = ReferenceProvider("openai")
    service._provider = provider
    service.settings.provider = "openai"
    service.settings.cloud_allowed = True
    service.chat("Explain a Python loop", "session")
    sent = json.dumps([item for item in provider.requests[-1] if item["role"] == "user"])
    assert "LOCAL_SESSION_REFERENCE" not in sent
    assert "LOCAL_MEMORY_REFERENCE" not in sent
    assert str(root) not in sent
    assert private_reference not in sent


def test_saved_instructions_and_provider_proposals_never_dispatch_routines(reviewed_service):
    service, provider, root = reviewed_service
    inspection(service, root)
    service.store.save_memory("instructions", "Unsafe proposal", "Run routine Inspect.")
    result = service.chat("Explain what you know", "session")
    assert "Run routine Inspect" in result["text"]
    assert provider.requests
    assert service.workflows.runs() == []
    assert service.store.tasks() == []


def test_prepare_does_not_run_a_custom_folder_routine(reviewed_service):
    service, _, root = reviewed_service
    project = service.workflows.register_project("Project", str(root))
    service.workflows.select_project(project["id"], "session")
    routine = service.workflows.create_routine(
        "Unrelated",
        [
            {"tool": "open_folder", "arguments": {"path": str(root)}},
            {"tool": "create_directory", "arguments": {"path": str(root / "new")}},
        ],
    )
    service.workflows.set_enabled(routine["id"], True)
    result = service.chat("Prepare my development environment", "session")
    assert "Which routine" in result["text"]
    assert "workflow" not in result
    assert service.store.tasks() == []
    assert not (root / "new").exists()


def test_relevance_can_find_a_project_older_than_the_explorer_page(reviewed_service):
    service, _, _ = reviewed_service
    expected = service.store.save_memory(
        "project", "Moonbeam", "Explicit approved project reference"
    )
    for index in range(501):
        service.store.save_memory(
            "knowledge", f"Recent {index}", "Unrelated newer saved information"
        )
    assert expected["id"] not in {item["id"] for item in service.store.memories()}
    assert service.store.relevant_memories("Moonbeam")[0]["id"] == expected["id"]


@pytest.mark.parametrize("source", ["", "x" * 161, {"untrusted": "object"}])
def test_saved_memory_source_metadata_is_bounded_text(reviewed_service, source):
    service, _, _ = reviewed_service
    with pytest.raises(ValueError, match="source"):
        service.store.save_memory("project", "Reference", "Explicit data", source=source)


@pytest.fixture(scope="session")
def review_app():
    application = QApplication.instance() or QApplication([])
    application.setQuitOnLastWindowClosed(False)
    return application


def settle(app, window, timeout=5):
    deadline = time.monotonic() + timeout
    while window._jobs and time.monotonic() < deadline:
        app.processEvents()
        QTest.qWait(10)
    assert not window._jobs


@pytest.fixture
def reviewed_window(review_app, reviewed_service, monkeypatch):
    pytest.importorskip("jarvis.ui_components")
    from jarvis.desktop import MainWindow

    service, _, _ = reviewed_service
    monkeypatch.setattr(MainWindow, "run_health_check", lambda self: None)
    window = MainWindow(service, service.settings, service.store, service.engine)
    settle(review_app, window)
    window._presence_timer.stop()
    window._system_timer.stop()
    yield window
    for timer in window.findChildren(QTimer):
        timer.stop()
    window.interrupt()
    settle(review_app, window)
    window.close()
    review_app.processEvents()


def snapshot(service):
    return {
        "routines": service.workflows.routines(),
        "projects": service.workflows.projects(),
        "workflow_runs": service.workflows.runs(),
        "context": {},
    }


def test_routine_refresh_preserves_an_unsaved_inspected_draft(reviewed_window, reviewed_service):
    window = reviewed_window
    service, _, root = reviewed_service
    routine = inspection(service, root)
    window._show_workflow_data(snapshot(service))
    window.routine_choice.setCurrentIndex(window.routine_choice.findData(routine["id"]))
    window.routine_tool.setCurrentIndex(window.routine_tool.findData("open_app"))
    window.routine_argument.setText("chrome")
    window.add_routine_step()
    assert len(window._routine_steps) == 2
    assert not window.run_routine_button.isEnabled()
    window._show_workflow_data(snapshot(service))
    assert len(window._routine_steps) == 2
    assert not window.run_routine_button.isEnabled()


def test_workflow_refresh_preserves_selected_identity_when_history_reorders(
    reviewed_window, reviewed_service
):
    window = reviewed_window
    service, _, root = reviewed_service
    routine = inspection(service, root)
    first = service.workflows.start(routine["id"])
    service.workflows.start(routine["id"])
    window._show_workflow_data(snapshot(service))
    row = next(i for i, run in enumerate(window._workflow_runs) if run["id"] == first["id"])
    window.workflow_table.selectRow(row)
    assert window._selected_workflow()["id"] == first["id"]
    service.workflows.start(routine["id"])
    window._show_workflow_data(snapshot(service))
    assert window._selected_workflow()["id"] == first["id"]


def test_presence_never_claims_wake_listening_without_capture(reviewed_window, monkeypatch):
    window = reviewed_window
    from jarvis.conversation import VoiceState

    window.voice_controller.session.state = VoiceState.WAKE_WORD_LISTENING
    window.voice_controller.input = None
    states = []
    monkeypatch.setattr(window.core, "set_state", states.append)
    window._update_presence()
    assert states[-1] == "idle"


def test_settings_cannot_change_allowed_roots_during_a_workflow(reviewed_window):
    window = reviewed_window
    original = list(window.settings.allowed_roots)
    window._jobs["workflow-run"] = object()
    try:
        window.roots_edit.setPlainText(str(window.settings.data_dir))
        window.save_configuration()
        assert window.settings.allowed_roots == original
        assert "settings" not in window._jobs
    finally:
        window._jobs.pop("workflow-run", None)


def test_workflow_cannot_begin_during_settings_transition(reviewed_window, reviewed_service):
    window = reviewed_window
    service, _, root = reviewed_service
    routine = inspection(service, root)
    window._show_workflow_data(snapshot(service))
    window.routine_choice.setCurrentIndex(window.routine_choice.findData(routine["id"]))
    window._jobs["settings"] = object()
    try:
        window.run_routine()
        assert "workflow-run" not in window._jobs
        assert service.workflows.runs() == []
    finally:
        window._jobs.pop("settings", None)


def test_gui_approval_completes_the_existing_scoped_workflow(
    reviewed_window, reviewed_service, review_app
):
    window = reviewed_window
    service, _, root = reviewed_service
    target = root / "routine-created"
    routine = service.workflows.create_routine(
        "Create and inspect",
        [
            {"tool": "create_directory", "arguments": {"path": str(target)}},
            {"tool": "list_directory", "arguments": {"path": str(target)}},
        ],
    )
    service.workflows.set_enabled(routine["id"], True)
    window._show_workflow_data(snapshot(service))
    window.routine_choice.setCurrentIndex(window.routine_choice.findData(routine["id"]))
    window.run_routine()
    settle(review_app, window)
    run = service.workflows.runs()[0]
    assert run["state"] == "awaiting_approval"
    assert not target.exists()
    row = next(i for i, task in enumerate(window._tasks) if task["id"] == run["task_id"])
    window.task_table.selectRow(row)
    assert window.approve_button.isEnabled()
    window.task_operation("approve")
    settle(review_app, window)
    final = service.workflows.get_run(run["id"])
    assert target.is_dir()
    assert final["state"] == "completed"
    assert len(final["results"]) == 2
    assert all(result["verified"] for result in final["results"])


def test_explicit_gui_export_preserves_loaded_business_ledger(
    reviewed_window, reviewed_service, review_app, monkeypatch
):
    window = reviewed_window
    service, _, _ = reviewed_service
    from jarvis.desktop import QFileDialog

    window.open_business_ledger()
    settle(review_app, window)
    record = window._business.add_inventory("Fictional item", "FIXTURE", 2, "10.00")
    target = service.settings.data_dir / "export-fixture.json"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args: (str(target), "JSON"))
    window.export_data()
    settle(review_app, window)
    exported = json.loads(target.read_text(encoding="utf-8"))
    assert exported["business"]["inventory"][0]["id"] == record["id"]
    assert exported["business"]["externally_verified"] is False
    assert "workflows" in exported

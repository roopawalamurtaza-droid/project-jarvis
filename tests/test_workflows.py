"""Routine behavior, bounded context, approvals, and cancellation regressions."""

import json
import threading

import pytest

from jarvis.config import Settings
from jarvis.storage import Store
from jarvis.tasks import TaskEngine
from jarvis.workflows import WorkflowEngine


@pytest.fixture
def system(tmp_path, monkeypatch):
    root = tmp_path / "project"
    root.mkdir()
    settings = Settings(data_dir=tmp_path / "data", allowed_roots=[root])
    store = Store(settings.data_dir)
    tasks = TaskEngine(settings, store)
    calls = []
    execute = tasks.registry.execute

    def desktop(tool, arguments):
        if tool in {"open_app", "open_folder"}:
            calls.append((tool, arguments))
            return {"verified": True, "evidence": "launcher_accepted", "pid": 123}
        return execute(tool, arguments)

    monkeypatch.setattr(tasks.registry, "execute", desktop)
    monkeypatch.setattr(tasks.registry, "application_path", lambda app: root / f"{app}.exe")
    workflows = WorkflowEngine(store, tasks, settings)
    return workflows, tasks, store, settings, root, calls


def app_step(app="vscode"):
    return {"tool": "open_app", "arguments": {"app": app}}


def enable(workflows, name="Development", steps=None):
    routine = workflows.create_routine(name, steps or [app_step()])
    return workflows.set_enabled(routine["id"], True)


def test_saved_definition_is_disabled_and_has_no_side_effect(system):
    workflows, _, _, _, _, calls = system
    routine = workflows.create_routine("Development", [app_step()])
    assert not routine["enabled"]
    assert calls == []
    with pytest.raises(PermissionError, match="enable"):
        workflows.start(routine["id"])
    assert workflows.runs() == []


def test_runs_serially_with_verified_task_references_and_persistence(system):
    workflows, tasks, store, settings, _, calls = system
    routine = enable(workflows, steps=[app_step(), app_step("chrome")])
    run = workflows.start(routine["name"].lower(), session_id="chat-1")
    assert run["state"] == "completed"
    assert run["step_index"] == 2
    assert [arguments["app"] for _, arguments in calls] == ["vscode", "chrome"]
    assert all(result["verified"] for result in run["results"])
    assert all(
        store.get_task(result["task_id"])["state"] == "completed" for result in run["results"]
    )
    context = workflows.session_context("chat-1")
    assert context["last_workflow_id"] == run["id"]
    assert context["last_task_id"] == run["results"][-1]["task_id"]
    restored = WorkflowEngine(store, tasks, settings)
    assert restored.get_run(run["id"])["state"] == "completed"
    assert "last_workflow_id" not in restored.session_context("chat-1")
    assert restored.routines()[0]["name"] == "Development"


@pytest.mark.parametrize(
    "steps",
    [
        [],
        [app_step()] * 13,
        [{"tool": "shell", "arguments": {"command": "echo bad"}}],
        [{"tool": "open_app", "arguments": {"app": "powershell"}}],
        [{"tool": "open_app", "arguments": {"app": "chrome", "command": "--bad"}}],
        [{"tool": "open_app", "arguments": {"app": "chrome"}, "script": "anything"}],
    ],
)
def test_routine_rejects_unbounded_and_arbitrary_execution(system, steps):
    workflows, _, _, _, _, calls = system
    with pytest.raises(ValueError):
        workflows.create_routine("Invalid", steps)
    assert not calls
    assert workflows.routines() == []


def test_all_steps_are_validated_before_any_execution_and_again_at_runtime(system):
    workflows, _, _, settings, root, calls = system
    routine = enable(
        workflows,
        steps=[app_step(), {"tool": "open_folder", "arguments": {"path": str(root)}}],
    )
    settings.allowed_roots = [settings.data_dir / "different"]
    with pytest.raises(PermissionError):
        workflows.start(routine["id"])
    assert calls == []
    assert workflows.runs() == []


def test_manual_mode_needs_a_separate_one_use_approval_for_each_step(system):
    workflows, tasks, _, settings, _, calls = system
    settings.mode = "manual"
    routine = enable(workflows, steps=[app_step(), app_step("chrome")])
    first = workflows.start(routine["id"])
    assert first["state"] == "awaiting_approval"
    assert calls == []
    assert workflows.resume(first["id"])["task_id"] == first["task_id"]
    tasks.approve(first["task_id"])
    second = workflows.resume_for_task(first["task_id"])
    assert second["state"] == "awaiting_approval"
    assert second["step_index"] == 1
    assert second["task_id"] != first["task_id"]
    assert len(calls) == 1
    with pytest.raises(ValueError, match="replayed"):
        tasks.approve(first["task_id"])
    tasks.approve(second["task_id"])
    assert workflows.resume(second["id"])["state"] == "completed"
    assert len(calls) == 2


def test_sensitive_filesystem_step_still_requires_approval_in_balanced_mode(system):
    workflows, tasks, _, _, root, _ = system
    target = root / "new"
    routine = enable(
        workflows, steps=[{"tool": "create_directory", "arguments": {"path": str(target)}}]
    )
    run = workflows.start(routine["id"])
    assert run["state"] == "awaiting_approval"
    assert not target.exists()
    task = tasks.approve(run["task_id"])
    assert task["state"] == "completed"
    assert target.is_dir()
    assert workflows.resume(run["id"])["state"] == "completed"


def test_rejection_cancels_entire_run_and_never_executes_later_step(system):
    workflows, tasks, _, settings, _, calls = system
    settings.mode = "manual"
    routine = enable(workflows, steps=[app_step(), app_step("chrome")])
    run = workflows.start(routine["id"])
    tasks.reject(run["task_id"])
    assert workflows.resume(run["id"])["state"] == "cancelled"
    assert calls == []


def test_cancel_removes_pending_task_authorization(system):
    workflows, tasks, store, settings, _, _ = system
    settings.mode = "manual"
    run = workflows.start(enable(workflows)["id"])
    assert workflows.cancel(run["id"])["state"] == "cancelled"
    assert store.get_task(run["task_id"])["state"] == "cancelled"
    with pytest.raises(ValueError):
        tasks.approve(run["task_id"])


def test_failed_or_unverified_step_stops_the_plan(system, monkeypatch):
    workflows, tasks, _, _, _, calls = system
    monkeypatch.setattr(tasks.registry, "execute", lambda *args: {"verified": False})
    run = workflows.start(enable(workflows, steps=[app_step(), app_step("chrome")])["id"])
    assert run["state"] == "failed"
    assert run["step_index"] == 0
    assert len(run["results"]) == 1
    assert not run["results"][0]["verified"]
    assert "verify" in run["error"]
    assert not calls


def test_cancellation_during_an_accepted_operation_stops_before_next_step(system, monkeypatch):
    workflows, tasks, _, _, _, _ = system
    entered, release = threading.Event(), threading.Event()
    calls = []

    def blocking(tool, arguments):
        calls.append(arguments["app"])
        entered.set()
        assert release.wait(5)
        return {"verified": True, "evidence": "launcher_accepted"}

    monkeypatch.setattr(tasks.registry, "execute", blocking)
    routine = enable(workflows, steps=[app_step(), app_step("chrome")])
    outcome = []
    thread = threading.Thread(target=lambda: outcome.append(workflows.start(routine["id"])))
    thread.start()
    try:
        assert entered.wait(5)
        run = workflows.runs()[0]
        assert workflows.cancel(run["id"])["state"] == "cancelled"
        release.set()
        thread.join(5)
        assert not thread.is_alive()
        assert outcome[0]["state"] == "cancelled"
        assert outcome[0]["results"][0]["verified"]
        assert calls == ["vscode"]
    finally:
        release.set()
        thread.join(5)


def test_caller_cancellation_before_start_prevents_all_actions(system):
    workflows, _, _, _, _, calls = system
    signal = threading.Event()
    signal.set()
    run = workflows.start(enable(workflows)["id"], cancel=signal)
    assert run["state"] == "cancelled"
    assert not calls
    assert run["results"] == []


def test_caller_cancellation_between_steps_keeps_evidence_but_stops_plan(system, monkeypatch):
    workflows, tasks, _, _, _, _ = system
    signal = threading.Event()
    calls = []

    def execute(tool, arguments):
        calls.append(arguments["app"])
        signal.set()
        return {"verified": True, "evidence": "launcher_accepted"}

    monkeypatch.setattr(tasks.registry, "execute", execute)
    run = workflows.start(
        enable(workflows, steps=[app_step(), app_step("chrome")])["id"], cancel=signal
    )
    assert run["state"] == "cancelled"
    assert calls == ["vscode"]
    assert run["results"][0]["verified"]


def test_caller_cancellation_while_approval_waiting_revokes_approval(system):
    workflows, tasks, store, settings, _, _ = system
    settings.mode = "manual"
    signal = threading.Event()
    run = workflows.start(enable(workflows)["id"], cancel=signal)
    signal.set()
    resumed = workflows.resume(run["id"], cancel=signal)
    assert resumed["state"] == "cancelled"
    assert store.get_task(run["task_id"])["state"] == "cancelled"
    with pytest.raises(ValueError):
        tasks.approve(run["task_id"])


def test_restart_cancels_interrupted_run_and_never_replays(system):
    workflows, _, store, settings, _, calls = system
    settings.mode = "manual"
    run = workflows.start(enable(workflows)["id"])
    tasks = TaskEngine(settings, store)
    restored = WorkflowEngine(store, tasks, settings)
    assert restored.get_run(run["id"])["state"] == "cancelled"
    assert "Interrupted" in restored.get_run(run["id"])["error"]
    assert store.get_task(run["task_id"])["state"] == "cancelled"
    assert restored.resume(run["id"])["state"] == "cancelled"
    assert calls == []


def test_emergency_stop_cancels_workflows_and_preserves_global_stop(system):
    workflows, tasks, _, settings, _, calls = system
    settings.mode = "manual"
    routine = enable(workflows)
    run = workflows.start(routine["id"])
    tasks.emergency_stop()
    workflows.emergency_stop()
    assert workflows.get_run(run["id"])["state"] == "cancelled"
    assert workflows.start(routine["id"])["state"] == "failed"
    assert calls == []


def test_edit_disable_delete_cancel_runs_and_keep_audit_history(system):
    workflows, _, store, settings, _, _ = system
    settings.mode = "manual"
    routine = enable(workflows)
    run = workflows.start(routine["id"])
    edited = workflows.update_routine(routine["id"], name="Edited", steps=[app_step("chrome")])
    assert not edited["enabled"]
    assert workflows.get_run(run["id"])["state"] == "cancelled"
    assert store.get_task(run["task_id"])["state"] == "cancelled"
    workflows.set_enabled(edited["id"], True)
    newer = workflows.start(edited["id"])
    workflows.set_enabled(edited["id"], False)
    assert workflows.get_run(newer["id"])["state"] == "cancelled"
    workflows.delete_routine(edited["id"])
    assert workflows.routines() == []
    assert len(workflows.runs()) == 2


def test_only_one_routine_can_hold_pending_actions(system):
    workflows, _, _, settings, _, _ = system
    settings.mode = "manual"
    first = enable(workflows, "First")
    second = enable(workflows, "Second")
    workflows.start(first["id"])
    with pytest.raises(RuntimeError, match="active"):
        workflows.start(second["id"])


def test_project_context_is_explicit_scoped_and_no_implicit_action(system):
    workflows, _, _, settings, root, calls = system
    project = workflows.register_project("Student Connect", str(root))
    context = workflows.select_project(project["id"], "chat")
    assert context["project"]["path"] == str(root.resolve())
    assert workflows.session_context("chat")["project"]["id"] == project["id"]
    assert "project" not in workflows.session_context("other-chat")
    assert calls == []
    with pytest.raises(PermissionError):
        workflows.register_project("Private", str(root / ".env"))
    with pytest.raises(PermissionError):
        workflows.register_project("Outside", str(settings.data_dir))
    settings.allowed_roots = [settings.data_dir]
    context = workflows.session_context("chat")
    assert "project" not in context
    assert context["project_unavailable"]


def test_development_routine_uses_existing_folder_and_allowlisted_app(system):
    workflows, _, _, _, root, calls = system
    project = workflows.register_project("Flutter app", str(root))
    routine = workflows.create_development_routine(project["id"])
    assert routine["kind"] == "development"
    assert routine["project_id"] == project["id"]
    assert not routine["enabled"]
    assert "not verified" in routine["description"]
    workflows.set_enabled(routine["id"], True)
    run = workflows.start(routine["id"])
    assert run["state"] == "completed"
    assert [tool for tool, _ in calls] == ["open_folder", "open_app"]
    assert calls[0][1] == {"path": str(root.resolve())}
    assert calls[1][1] == {"app": "vscode"}
    workflows.select_project(project["id"])
    workflows.delete_project(project["id"])
    assert workflows.projects() == []
    assert "project" not in workflows.session_context()


def test_missing_application_is_detected_before_an_earlier_folder_launch(system, monkeypatch):
    workflows, tasks, _, _, root, calls = system
    routine = enable(
        workflows, steps=[{"tool": "open_folder", "arguments": {"path": str(root)}}, app_step()]
    )
    monkeypatch.setattr(tasks.registry, "application_path", lambda app: None)
    with pytest.raises(ValueError, match="no routine steps ran"):
        workflows.start(routine["id"])
    assert not calls
    assert workflows.runs() == []


def test_development_intent_metadata_does_not_survive_custom_edit(system):
    workflows, _, _, _, root, _ = system
    project = workflows.register_project("Project", str(root))
    routine = workflows.create_development_routine(project["id"])
    edited = workflows.update_routine(routine["id"], steps=[app_step("chrome")])
    assert edited["kind"] == "routine"
    assert "project_id" not in edited
    assert not edited["enabled"]


def test_retargeting_a_registered_project_does_not_silently_change_a_saved_plan(system):
    workflows, _, _, _, root, calls = system
    project = workflows.register_project("Project", str(root))
    routine = workflows.create_development_routine(project["id"])
    workflows.set_enabled(routine["id"], True)
    newer = root / "newer"
    newer.mkdir()
    workflows.register_project("Project", str(newer))
    with pytest.raises(ValueError, match="no longer matches"):
        workflows.start(routine["id"])
    assert not calls


def test_read_file_results_are_not_duplicated_or_leaked_into_workflow_export(system):
    workflows, _, store, _, root, _ = system
    content = "This private document is viewed for one task."
    path = root / "document.txt"
    path.write_text(content, encoding="utf-8")
    routine = enable(workflows, steps=[{"tool": "read_file", "arguments": {"path": str(path)}}])
    run = workflows.start(routine["id"])
    assert run["state"] == "completed"
    assert run["results"][0]["verified"]
    assert content not in json.dumps(workflows.export())
    assert "content" not in store.get_task(run["results"][0]["task_id"])["result"]


def test_name_and_enabled_validation_is_strict_and_returns_isolated_data(system):
    workflows, _, _, _, _, _ = system
    routine = workflows.create_routine("Routine", [app_step()])
    routine["steps"][0]["arguments"]["app"] = "powershell"
    assert workflows.routines()[0]["steps"][0]["arguments"]["app"] == "vscode"
    with pytest.raises(ValueError, match="unique"):
        workflows.create_routine("routine", [app_step()])
    with pytest.raises(ValueError):
        workflows.set_enabled(routine["id"], "yes")
    with pytest.raises(ValueError):
        workflows.session_context("invalid/session")


def test_history_retention_removes_only_terminal_runs(system):
    workflows, _, _, settings, _, _ = system
    routine = enable(workflows)
    completed = workflows.start(routine["id"])
    settings.mode = "manual"
    active = workflows.start(routine["id"])
    with workflows._connect() as db:
        db.execute("UPDATE workflow_runs SET updated_at=?", ("2000-01-01T00:00:00+00:00",))
    workflows.prune(30)
    assert workflows.get_run(active["id"])["state"] == "awaiting_approval"
    with pytest.raises(ValueError, match="Unknown"):
        workflows.get_run(completed["id"])
    assert workflows.routines()[0]["id"] == routine["id"]


def test_definition_and_history_counts_are_bounded(system, monkeypatch):
    workflows, _, _, _, root, _ = system
    monkeypatch.setattr("jarvis.workflows.MAX_ROUTINES", 2)
    monkeypatch.setattr("jarvis.workflows.MAX_PROJECTS", 2)
    monkeypatch.setattr("jarvis.workflows.MAX_RUNS", 3)
    routine = enable(workflows, "First")
    enable(workflows, "Second")
    with pytest.raises(ValueError, match="limit"):
        enable(workflows, "Third")
    workflows.register_project("First", str(root))
    workflows.register_project("Second", str(root))
    with pytest.raises(ValueError, match="limit"):
        workflows.register_project("Third", str(root))
    for _ in range(5):
        workflows.start(routine["id"])
    assert len(workflows.export()["runs"]) == 3

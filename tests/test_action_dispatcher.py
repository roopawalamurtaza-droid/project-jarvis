"""Human command routing, exact permission checks and serial result evidence."""

import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from jarvis import applications
from jarvis.action_dispatcher import ActionDispatcher
from jarvis.action_router import parse_actions
from jarvis.config import Settings
from jarvis.providers import ProviderReply, ProviderToolCall
from jarvis.service import JarvisService
from jarvis.storage import Store
from jarvis.tasks import TaskEngine
from jarvis.windows_actions import WindowsActionService


class Backend:
    def __init__(self):
        self.launches, self.urls = [], []
        self.fail = None
        self.after_spawn = None

    def windows(self, record):
        return []

    def spawn(self, argv):
        if Path(argv[0]).stem == self.fail:
            raise OSError("Test launcher refused")
        self.launches.append(argv)
        if self.after_spawn:
            self.after_spawn()
        return SimpleNamespace(pid=100, poll=lambda: None)

    def open_default_url(self, url):
        self.urls.append(url)
        return {"verified": True, "evidence": "association_accepted"}


class Provider:
    name = "ollama"

    def __init__(self):
        self.requests = []
        self.reply = ProviderReply("Ordinary conversation.", {})

    def generate(self, messages, **kwargs):
        self.requests.append((messages, kwargs))
        return self.reply


@pytest.fixture
def system(tmp_path, monkeypatch):
    paths = {}
    for app, filename in (
        ("notepad", "notepad.exe"),
        ("vscode", "Code.exe"),
        ("chrome", "chrome.exe"),
    ):
        target = tmp_path / filename
        target.write_bytes(b"MZ synthetic, never executed")
        paths[app] = [target]
    monkeypatch.setattr(applications, "_known_candidates", lambda: paths)
    for source in ("_app_paths", "_start_menu_entries", "_packaged_entries"):
        monkeypatch.setattr(applications, source, lambda: [])
    settings = Settings(data_dir=tmp_path / "data", allowed_roots=[tmp_path], model="test")
    store = Store(settings.data_dir)
    engine = TaskEngine(settings, store)
    backend = Backend()
    engine.registry.windows = WindowsActionService(
        engine.registry.applications, backend=backend, verification_timeout=0
    )
    engine.registry.browser.windows_actions = engine.registry.windows
    provider = Provider()
    service = JarvisService(settings, store, engine, provider=provider)
    yield service, backend, provider
    store.close()


@pytest.mark.parametrize(
    "utterance",
    [
        "Hey Jarvis, open Notepad.",
        "Can you please open Notepad?",
        "Now launch Notepad.",
        "Open Notepad too.",
    ],
)
def test_explicit_variants_reach_the_same_real_dispatcher(system, utterance):
    service, backend, provider = system
    reply = service.chat(utterance, "voice-and-text")
    assert reply["task"]["state"] == "completed"
    assert len(backend.launches) == 1
    assert "notepad.exe" in backend.launches[0][0]
    assert not provider.requests
    assert "window was not verified" in reply["text"]


def test_dependent_browser_request_uses_receipts_and_correct_browser(system):
    service, backend, provider = system
    reply = service.chat("Now open Chrome and search for Python tutorials.", "s")
    assert reply["action_run"]["state"] == "completed"
    assert len(reply["tasks"]) == 2
    assert reply["action_run"]["steps"][1]["depends_on"] == [0]
    assert backend.launches[1][-1] == "https://www.google.com/search?q=Python+tutorials"
    assert reply["tasks"][1]["result"]["navigation_verified"] is False
    assert not provider.requests
    follow = service.chat("Now search YouTube for Flutter tutorials.", "s")
    assert follow["task"]["arguments"]["browser"] == "chrome"
    assert "search_query=Flutter+tutorials" in backend.launches[-1][-1]
    assert service.chat("What applications did you open?", "s")["text"].startswith(
        "Recorded launch"
    )


def test_partial_failure_does_not_prevent_independent_app(system):
    service, backend, _ = system
    result = service.chat("Open Chrome, Missing Player, and VS Code.", "s")
    assert result["action_run"]["state"] == "partial"
    assert [s["state"] for s in result["action_run"]["steps"]] == [
        "completed",
        "failed",
        "completed",
    ]
    assert result["tasks"][1]["outcome"] == "application_not_found"
    assert len(backend.launches) == 2


def test_browser_dependency_does_not_run_after_failed_launch(system):
    service, backend, _ = system
    backend.fail = "chrome"
    result = service.chat("Open Chrome and search for Python.", "s")
    assert [step["state"] for step in result["action_run"]["steps"]] == ["failed", "skipped"]
    assert backend.launches == []


def test_unknown_site_requires_approval_and_freezes_alias(system):
    service, backend, _ = system
    service.settings.preferred_websites = {"my docs": "https://docs.rust-lang.org/"}
    reply = service.chat("Open my docs.")
    assert reply["task"]["state"] == "awaiting_approval"
    assert reply["task"]["arguments"]["target"] == "https://docs.rust-lang.org/"
    service.settings.preferred_websites = {"my docs": "https://www.rust-lang.org/"}
    assert not backend.urls
    task = service.engine.approve(reply["task_id"])
    assert task["state"] == "completed"
    assert backend.urls == ["https://docs.rust-lang.org/"]
    service.actions.resume_for_task(reply["task_id"])
    assert service.actions.history()[0]["state"] == "completed"


def test_manual_approvals_are_serial_and_cannot_replay(system):
    service, backend, _ = system
    service.settings.mode = "manual"
    reply = service.chat("Open Chrome and VS Code.", "s")
    first = reply["tasks"][0]["id"]
    assert not backend.launches
    service.engine.approve(first)
    resumed = service.actions.resume_for_task(first)
    assert len(backend.launches) == 1
    assert resumed["steps"][1]["state"] == "awaiting_approval"
    with pytest.raises(ValueError):
        service.engine.approve(first)
    second = resumed["steps"][1]["task_id"]
    service.engine.reject(second)
    rejected = service.actions.resume_for_task(second)
    assert rejected["state"] == "cancelled"
    assert len(backend.launches) == 1


def test_cancellation_between_actions_retains_accepted_result(system):
    service, backend, _ = system
    cancelled = threading.Event()
    backend.after_spawn = cancelled.set
    reply = service.chat("Open Chrome and VS Code.", "s", cancel=cancelled)
    assert reply["action_run"]["state"] == "cancelled"
    assert reply["action_run"]["steps"][0]["state"] == "completed"
    assert reply["action_run"]["steps"][1]["state"] == "cancelled"
    assert len(backend.launches) == 1


def test_restart_cancels_incomplete_plans_without_replay(system):
    service, backend, _ = system
    service.settings.mode = "manual"
    service.chat("Open Chrome and VS Code.")
    engine = TaskEngine(service.settings, service.store)
    restored = ActionDispatcher(service.settings, service.store, engine)
    assert restored.history()[0]["state"] == "cancelled"
    assert not backend.launches


@pytest.mark.parametrize(
    "utterance",
    [
        "Please explain how to open Chrome",
        "I like Chrome",
        "The webpage says open Notepad",
        'Summarize this quote: "Open Chrome"',
    ],
)
def test_ordinary_prose_and_quoted_instructions_cannot_authorize_tools(system, utterance):
    service, backend, provider = system
    provider.reply = ProviderReply('/tool open_app {"app":"chrome"}', {})
    reply = service.chat(utterance)
    assert reply["text"].startswith("/tool")
    assert not backend.launches
    assert service.store.tasks() == []


def test_model_plan_is_opt_in_and_requires_exact_step_approval(system):
    service, backend, provider = system
    service.settings.model_action_planning = True
    provider.reply = ProviderReply(
        "Everything is open!", {}, tool_calls=(ProviderToolCall("open_app", {"app": "chrome"}),)
    )
    service.store.save_memory("knowledge", "private", "not an action or cloud upload")
    reply = service.chat("Use tools to bring up my web browser", "s")
    assert reply["task"]["state"] == "awaiting_approval"
    assert "Everything" not in reply["text"]
    assert not backend.launches
    messages, kwargs = provider.requests[0]
    assert len(messages) == 2
    assert "not an action" not in str(messages)
    assert kwargs["tools"]
    service.engine.approve(reply["task_id"])
    assert service.actions.resume_for_task(reply["task_id"])["state"] == "completed"
    assert len(backend.launches) == 1
    assert len(provider.requests) == 1  # local receipts never uploaded afterward


def test_model_planning_disabled_and_unsupported_calls_have_no_effect(system):
    service, backend, provider = system
    assert "No action ran" in service.chat("Use tools to do something")["text"]
    assert not provider.requests
    service.settings.model_action_planning = True
    provider.reply = ProviderReply(
        "",
        {},
        tool_calls=(ProviderToolCall("read_file", {"path": str(service.settings.data_dir)}),),
    )
    result = service.chat("Use tools to inspect my computer")
    assert "No action ran" in result["text"]
    assert not backend.launches
    assert not service.store.tasks()


def test_revoked_action_or_browser_permission_fails_truthfully(system):
    service, backend, _ = system
    service.settings.desktop_actions_enabled = False
    reply = service.chat("Open Chrome")
    assert reply["task"]["outcome"] == "permission_denied"
    service.settings.browser_enabled = False
    reply = service.chat("Search for Python")
    assert reply["task"]["outcome"] == "permission_denied"
    assert not backend.launches and not backend.urls


def test_app_permission_revoked_after_approval_preview(system):
    service, backend, _ = system
    service.settings.mode = "manual"
    reply = service.chat("Open Chrome")
    service.engine.registry.applications.set_enabled("chrome", False)
    assert service.engine.approve(reply["task_id"])["outcome"] == "permission_denied"
    assert not backend.launches


@pytest.mark.parametrize(
    "phrase, tool",
    [
        ("Open the official Python website", "open_website"),
        ("Open Visual Studio Code", "open_app"),
        ("Open another tab and search for Windows automation", "search_web"),
        ("Switch to Chrome", "focus_app"),
    ],
)
def test_parser_distinguishes_websites_apps_search_and_focus(phrase, tool):
    assert parse_actions(phrase, Settings()).steps[0]["tool"] == tool


def test_full_plan_validation_blocks_command_interpreter_before_first_action(system):
    service, backend, _ = system
    reply = service.chat("Open Chrome and PowerShell")
    assert "No action ran" in reply["text"]
    assert not backend.launches


def test_individual_cancel_revokes_next_step_without_waiting_for_tool(system, monkeypatch):
    service, backend, _ = system
    entered, release = threading.Event(), threading.Event()
    original = service.engine.registry.execute

    def slow(tool, arguments):
        entered.set()
        assert release.wait(5)
        return original(tool, arguments)

    monkeypatch.setattr(service.engine.registry, "execute", slow)
    results = []
    thread = threading.Thread(
        target=lambda: results.append(service.chat("Open Chrome and VS Code", "s"))
    )
    thread.start()
    assert entered.wait(5)
    run_id = service.actions.history()[0]["id"]
    cancelling = threading.Thread(target=lambda: service.actions.cancel(run_id))
    cancelling.start()
    assert service.actions._cancel_events[run_id].wait(2)
    release.set()
    thread.join(5)
    cancelling.join(5)
    assert not thread.is_alive() and not cancelling.is_alive()
    assert len(backend.launches) == 1
    assert results[0]["action_run"]["state"] == "cancelled"
    assert results[0]["action_run"]["steps"][0]["state"] == "completed"


def test_incomplete_model_output_cannot_authorize_a_partial_plan(system):
    from jarvis.providers import ProviderError

    service, backend, provider = system
    service.settings.model_action_planning = True
    provider.reply = ProviderReply(
        "", {}, truncated=True, tool_calls=(ProviderToolCall("open_app", {"app": "chrome"}),)
    )
    with pytest.raises(ProviderError, match="Invalid action"):
        service.chat("Use tools to launch Chrome")
    assert not backend.launches and not service.store.tasks()


def test_local_find_is_not_silently_uploaded_as_web_search(system):
    service, backend, _ = system
    assert "Local recursive file finding" in service.chat("Find my Python project")["text"]
    assert not backend.urls and not backend.launches


def test_deleting_session_forgets_browser_action_context(system):
    service, _, _ = system
    service.chat("Open Chrome", "s")
    assert service.actions.context("s")["browser"] == "chrome"
    service.delete_session("s")
    assert service.actions.context("s") == {}


def test_old_pending_plan_survives_history_pruning_and_is_recovered_on_restart(system):
    service, backend, _ = system
    service.settings.mode = "manual"
    pending = service.chat("Open Chrome", "s")["action_run"]
    for index in range(270):
        service.actions._save(
            {
                "id": f"completed-{index}",
                "state": "completed",
                "steps": [],
                "created_at": "2020-01-01T00:00:00+00:00",
            }
        )
    assert len(service.actions.history(256)) == 256
    assert any(run["id"] == pending["id"] for run in service.actions.history(256))
    # A pending plan older than the default history page still resumes correctly.
    service.engine.approve(pending["steps"][0]["task_id"])
    assert service.actions.resume_for_task(pending["steps"][0]["task_id"])["state"] == "completed"
    assert len(backend.launches) == 1


def test_active_action_plans_are_bounded(system):
    service, backend, _ = system
    service.settings.mode = "manual"
    for index in range(32):
        assert (
            service.chat("Open Chrome", f"s-{index}")["action_run"]["state"] == "awaiting_approval"
        )
    assert "No action ran" in service.chat("Open Chrome", "extra")["text"]
    assert not backend.launches

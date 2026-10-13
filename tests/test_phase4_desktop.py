"""Native Phase 4 UI tests without audio, discovered apps, URLs or OS launches."""

from __future__ import annotations

import copy
import gc
import os
import sys
import threading
import time
import uuid
import weakref
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QThread
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox

from jarvis.action_dispatcher import ActionDispatcher
from jarvis.config import Settings
from jarvis.desktop import MainWindow
from jarvis.storage import Store


class LocalCatalog:
    def __init__(self):
        self.records = [
            dict(
                id="custom_a",
                name="Reviewed Editor",
                target="C:/Tests/Editor.exe",
                kind="exe",
                enabled=False,
                favorite=False,
                aliases=[],
                source="custom",
            )
        ]
        self.calls = []
        self.release = threading.Event()
        self.release.set()
        self.started = threading.Event()

    def _worker(self, operation):
        assert threading.current_thread() is not threading.main_thread()
        self.calls.append(operation)

    def list_apps(self, query=""):
        self._worker("read")
        self.started.set()
        assert self.release.wait(3)
        return copy.deepcopy(
            [
                record
                for record in self.records
                if not query or query.casefold() in record["name"].casefold()
            ]
        )

    def health(self):
        self._worker("health")
        return {"available": True, "enabled": sum(r["enabled"] for r in self.records)}

    def refresh(self):
        self._worker("refresh")

    def register_custom(self, name, path):
        self._worker("register")
        record = dict(
            id="custom_b",
            name=name,
            target=path,
            kind="exe",
            enabled=False,
            favorite=False,
            aliases=[],
            source="custom",
        )
        self.records.append(record)
        return copy.deepcopy(record)

    def _set(self, identity, key, value):
        self._worker(key)
        record = next(r for r in self.records if r["id"] == identity)
        record[key] = value
        return copy.deepcopy(record)

    def set_enabled(self, identity, enabled, **review):
        return self._set(identity, "enabled", enabled)

    def set_favorite(self, identity, favorite):
        return self._set(identity, "favorite", favorite)

    def set_alias(self, identity, alias):
        record = next(r for r in self.records if r["id"] == identity)
        return self._set(identity, "aliases", [*record["aliases"], alias])

    def remove_alias(self, identity, alias):
        record = next(r for r in self.records if r["id"] == identity)
        return self._set(identity, "aliases", [a for a in record["aliases"] if a != alias])


class TestEngine:
    __test__ = False

    def __init__(self, store, catalog):
        self.store = store
        self.submissions = []
        self.registry = SimpleNamespace(
            applications=catalog,
            windows=SimpleNamespace(health=self.health),
            browser=SimpleNamespace(health=self.health),
            validate=lambda tool, args: copy.deepcopy(args),
        )

    def health(self):
        assert threading.current_thread() is not threading.main_thread()
        return {"available": True, "backend": "injected test service"}

    def submit(self, tool, arguments, **kwargs):
        assert threading.current_thread() is not threading.main_thread()
        self.submissions.append((tool, arguments))
        task = dict(
            id=str(uuid.uuid4()),
            tool=tool,
            arguments=arguments,
            state="awaiting_approval",
            result=None,
            error=None,
        )
        self.store.put_task(task)
        return task

    def _update(self, identity, state):
        task = self.store.get_task(identity)
        task.update(
            state=state,
            result={"verified": state == "completed", "evidence": "injected_test_result"},
        )
        self.store.put_task(task)
        return task

    def approve(self, identity):
        return self._update(identity, "completed")

    def reject(self, identity):
        return self._update(identity, "cancelled")

    cancel = reject

    def emergency_stop(self):
        return None

    def reset_stop(self):
        return None


@pytest.fixture(scope="session")
def phase4_app():
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    return app


def wait(app, predicate, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return
        QTest.qWait(10)
    raise AssertionError("Phase 4 desktop worker did not settle")


def settle(app, window):
    wait(app, lambda: not window._jobs)


@pytest.fixture
def phase4_window(phase4_app, tmp_path, monkeypatch):
    class ForbiddenAudio:
        def __init__(self, *args, **kwargs):
            raise AssertionError("UI test must not initialize audio")

    monkeypatch.setitem(
        sys.modules,
        "jarvis.voice",
        SimpleNamespace(VoiceInput=ForbiddenAudio, SpeechOutput=ForbiddenAudio),
    )
    settings = Settings(data_dir=tmp_path / "data", allowed_roots=[tmp_path])
    store = Store(settings.data_dir)
    catalog = LocalCatalog()
    engine = TestEngine(store, catalog)
    service = SimpleNamespace(
        settings=settings,
        secret_store=SimpleNamespace(set=lambda *args: None, delete=lambda *args: None),
    )
    service.actions = ActionDispatcher(settings, store, engine)
    window = MainWindow(service, settings, store, engine)
    window._system_timer.stop()
    window.show()
    settle(phase4_app, window)
    yield window, catalog
    catalog.release.set()
    window.interrupt()
    settle(phase4_app, window)
    window.close()
    wait(phase4_app, lambda: not window._jobs and not window.isVisible())
    window.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    phase4_app.processEvents()
    store.close()


def open_catalog(app, window):
    window._navigate(9)
    settle(app, window)
    window.application_table.selectRow(0)


def test_catalog_is_lazy_and_old_page_indices_are_preserved(phase4_app, phase4_window):
    window, catalog = phase4_window
    assert window.page_titles[4] == "Settings" and window.page_titles[8] == "Business"
    assert window.page_titles[9] == "Application Library"
    assert catalog.calls == []
    assert window.engine.submissions == []
    assert "not been read" in window.application_notice.text()
    open_catalog(phase4_app, window)
    assert window.application_table.rowCount() == 1
    assert "Disabled" == window.application_table.item(0, 1).text()
    assert not window.application_launch_button.isEnabled()
    assert "C:/Tests/Editor.exe" in window.application_detail.toPlainText()


def test_new_custom_registration_stays_disabled(phase4_app, phase4_window):
    window, catalog = phase4_window
    window.custom_application_name.setText("New Editor")
    window.custom_application_path.setText("C:/Tests/New.exe")
    window.register_application()
    settle(phase4_app, window)
    assert catalog.records[-1]["enabled"] is False
    assert window._selected_application()["id"] == "custom_b"
    assert not window.application_launch_button.isEnabled()
    assert window.engine.submissions == []


def test_enable_requires_target_review_then_launch_uses_exact_id(
    phase4_app, phase4_window, monkeypatch
):
    window, catalog = phase4_window
    open_catalog(phase4_app, window)
    questions = []

    def review(*args):
        questions.append(args[2])
        return QMessageBox.StandardButton.No

    monkeypatch.setattr(QMessageBox, "question", review)
    window.toggle_application_permission()
    settle(phase4_app, window)
    assert "C:/Tests/Editor.exe" in questions[0]
    assert catalog.records[0]["enabled"] is False
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
    window.toggle_application_permission()
    settle(phase4_app, window)
    assert catalog.records[0]["enabled"] is True
    window.launch_library_application()
    settle(phase4_app, window)
    assert window.engine.submissions == [("open_app", {"app": "custom_a"})]
    assert window._tasks[0]["state"] == "awaiting_approval"


def test_alias_favorite_and_disabling_do_not_launch(phase4_app, phase4_window):
    window, catalog = phase4_window
    open_catalog(phase4_app, window)
    window.application_alias.setText("editor")
    window.application_alias_operation()
    settle(phase4_app, window)
    window.toggle_application_favorite()
    settle(phase4_app, window)
    assert catalog.records[0]["aliases"] == ["editor"]
    assert catalog.records[0]["favorite"] is True
    assert catalog.records[0]["enabled"] is False
    window.application_alias_operation(True)
    settle(phase4_app, window)
    assert catalog.records[0]["aliases"] == []
    assert window.engine.submissions == []


def test_application_target_cannot_change_between_review_and_enable(
    phase4_app, phase4_window, monkeypatch
):
    window, catalog = phase4_window
    open_catalog(phase4_app, window)

    def changed_target(*args):
        catalog.records[0]["target"] = "C:/Tests/Different.exe"
        return QMessageBox.StandardButton.Yes

    monkeypatch.setattr(QMessageBox, "question", changed_target)
    window.toggle_application_permission()
    settle(phase4_app, window)
    assert catalog.records[0]["enabled"] is False
    assert "target changed after review" in window.status_label.text()
    assert window.engine.submissions == []


def test_catalog_read_does_not_block_qt_and_selection_survives_refresh(phase4_app, phase4_window):
    window, catalog = phase4_window
    open_catalog(phase4_app, window)
    catalog.release.clear()
    catalog.started.clear()
    window.refresh_applications(rescan=True)
    wait(phase4_app, catalog.started.is_set)
    before = time.monotonic()
    QTest.qWait(50)
    phase4_app.processEvents()
    assert time.monotonic() - before < 0.5
    catalog.release.set()
    settle(phase4_app, window)
    assert window._selected_application()["id"] == "custom_a"


def test_filtered_application_does_not_silently_select_another_target(phase4_app, phase4_window):
    window, _ = phase4_window
    open_catalog(phase4_app, window)
    window.application_search.setText("No matching app")
    window.refresh_applications()
    settle(phase4_app, window)
    assert window._selected_application() is None
    assert not window.application_enable_button.isEnabled()
    assert not window.application_launch_button.isEnabled()


def test_active_action_progress_reads_receipts_before_worker_returns(phase4_app, phase4_window):
    window, _ = phase4_window
    release, started = threading.Event(), threading.Event()

    def run():
        task = window.engine.submit("open_app", {"app": "custom_a"})
        window.engine._update(task["id"], "running")
        started.set()
        assert release.wait(3)

    window._run("action", run)
    try:
        wait(phase4_app, started.is_set)
        window._refresh_active_actions()
        wait(phase4_app, lambda: bool(window._tasks))
        assert window._tasks[0]["state"] == "running"
        assert "action" in window._jobs
    finally:
        release.set()
        settle(phase4_app, window)


def test_settings_transition_and_emergency_stop_block_library_mutations(phase4_app, phase4_window):
    window, catalog = phase4_window
    open_catalog(phase4_app, window)
    before = list(catalog.calls)
    window._jobs["settings"] = SimpleNamespace()
    window.toggle_application_favorite()
    window.register_application()
    window._jobs.pop("settings")
    window._stopped = True
    window.toggle_application_favorite()
    window.register_application()
    assert catalog.calls == before
    assert window.engine.submissions == []


def test_approval_resumes_only_its_matching_action_plan_and_preserves_receipts(
    phase4_app, phase4_window
):
    window, _ = phase4_window
    runs = []

    def start():
        for app in ("custom_a", "other"):
            runs.append(
                window.service.actions.start(
                    [{"tool": "open_app", "arguments": {"app": app}}], session_id="test"
                )
            )

    window._run("test-plan", start)
    settle(phase4_app, window)
    window.refresh()
    settle(phase4_app, window)
    identity = runs[0]["steps"][0]["task_id"]
    row = next(i for i, task in enumerate(window._tasks) if task["id"] == identity)
    window.task_table.selectRow(row)
    window.task_operation("approve")
    settle(phase4_app, window)
    results = {r["id"]: r for r in window._action_runs}
    assert results[runs[0]["id"]]["state"] == "completed"
    assert results[runs[1]["id"]]["state"] == "awaiting_approval"
    row = next(i for i, run in enumerate(window._action_runs) if run["id"] == runs[0]["id"])
    window.action_run_table.selectRow(row)
    detail = window.action_run_detail.toPlainText()
    assert "injected_test_result" in detail and "custom_a" in detail


def test_cancel_plan_revokes_pending_task(phase4_app, phase4_window):
    window, _ = phase4_window
    window._run(
        "test-plan",
        lambda: window.service.actions.start(
            [{"tool": "open_app", "arguments": {"app": "custom_a"}}], session_id="test"
        ),
    )
    settle(phase4_app, window)
    window.refresh()
    settle(phase4_app, window)
    window.action_run_table.selectRow(0)
    window.cancel_action_run()
    settle(phase4_app, window)
    assert window._action_runs[0]["state"] == "cancelled"
    assert window._tasks[0]["state"] == "cancelled"


def test_new_settings_preserve_browser_and_explicit_permission_choices(phase4_app, phase4_window):
    window, _ = phase4_window
    window.browser_choice.setCurrentText("firefox")
    window.search_engine_choice.setCurrentText("duckduckgo")
    window.browser_window_check.setChecked(True)
    window.model_actions_check.setChecked(True)
    window.desktop_actions_check.setChecked(False)
    window.browser_actions_check.setChecked(False)
    window.website_aliases_edit.setPlainText('{"docs": "https://docs.python.org/3/"}')
    window.save_configuration()
    settle(phase4_app, window)
    assert window.settings.default_browser == "firefox"
    assert window.settings.default_search_engine == "duckduckgo"
    assert window.settings.browser_new_window is True
    assert window.settings.model_action_planning is True
    assert window.settings.desktop_actions_enabled is False
    assert window.settings.browser_enabled is False
    assert window.settings.preferred_websites == {"docs": "https://docs.python.org/3/"}


def test_diagnostics_reports_injected_services_without_launches(phase4_app, phase4_window):
    window, _ = phase4_window
    window._navigate(7)
    settle(phase4_app, window)
    assert "injected test service" in window.action_diagnostics.toPlainText()
    assert window.engine.submissions == []


def test_direct_browser_and_read_only_submissions_use_typed_arguments(phase4_app, phase4_window):
    window, _ = phase4_window
    for tool, text, arguments in (
        ("open_website", "youtube", {"target": "youtube"}),
        ("search_web", "Windows documentation", {"query": "Windows documentation"}),
        ("get_system_status", "", {}),
    ):
        window.tool_choice.setCurrentIndex(window.tool_choice.findData(tool))
        window.tool_path.setText(text)
        window.submit_action()
        settle(phase4_app, window)
        assert window.engine.submissions[-1] == (tool, arguments)


def test_worker_signal_objects_are_gui_owned_and_deleted_on_gui_thread(phase4_app, phase4_window):
    import shiboken6

    window, _ = phase4_window
    release, started = threading.Event(), threading.Event()
    destroyed_on_gui = []

    def work():
        started.set()
        assert release.wait(3)

    job = window._run("ownership-review", work)
    signals = job.signals
    assert signals.parent() is window
    signals.destroyed.connect(
        lambda: destroyed_on_gui.append(QThread.currentThread() == phase4_app.thread())
    )
    try:
        wait(phase4_app, started.is_set)
        assert shiboken6.isValid(signals)
    finally:
        release.set()
        settle(phase4_app, window)
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert not shiboken6.isValid(signals)
    assert destroyed_on_gui == [True]


def test_closed_qt_window_is_destroyed_before_background_python_collection(phase4_app, tmp_path):
    import shiboken6

    settings = Settings(data_dir=tmp_path / "gc-review")
    store = Store(settings.data_dir)
    engine = TestEngine(store, LocalCatalog())
    view = MainWindow(SimpleNamespace(), settings, store, engine)
    overlay = view.ambient_overlay
    assert overlay.parent() is view
    assert overlay.isWindow()
    view.show()
    settle(phase4_app, view)
    view._presence_timer.stop()
    view.hide()
    view._update_overlay("activated")
    phase4_app.processEvents()
    assert overlay.isVisible()
    assert not view.isVisible()
    view._update_overlay("wake")
    assert not overlay.isVisible()
    view.show()
    destroyed_on_gui = []
    view.destroyed.connect(
        lambda: destroyed_on_gui.append(QThread.currentThread() == phase4_app.thread())
    )
    view.close()
    wait(phase4_app, lambda widget=view: not widget._jobs and not widget.isVisible())
    view.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert not shiboken6.isValid(view)
    assert not shiboken6.isValid(overlay)
    reference = weakref.ref(view)
    del view
    worker = threading.Thread(target=gc.collect)
    worker.start()
    worker.join(3)
    assert not worker.is_alive()
    assert reference() is None
    assert destroyed_on_gui == [True]
    store.close()

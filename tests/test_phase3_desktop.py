"""Real desktop/services integration without microphone, cloud, or app launches."""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from jarvis import awareness
from jarvis.awareness import AwarenessSnapshot, DesktopContextSnapshot, SystemMetricsSnapshot
from jarvis.config import Settings, load_settings
from jarvis.conversation import VoiceState
from jarvis.desktop import MainWindow
from jarvis.providers import ProviderReply
from jarvis.service import JarvisService
from jarvis.storage import Store
from jarvis.tasks import TaskEngine


class StubProvider:
    name = "ollama"

    def __init__(self):
        self.messages = []
        self.started = threading.Event()
        self.release = threading.Event()
        self.release.set()

    def generate(self, messages, *, cancel=None, **options):
        assert threading.current_thread() is not threading.main_thread()
        self.messages.append(messages)
        self.started.set()
        while not self.release.wait(0.01):
            if cancel and cancel.is_set():
                from jarvis.providers import ProviderCancelled

                raise ProviderCancelled()
        return ProviderReply("A deterministic test reply.", {})


@pytest.fixture(scope="session")
def phase3_app():
    application = QApplication.instance() or QApplication([])
    application.setQuitOnLastWindowClosed(False)
    return application


def wait(phase3_app, predicate, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        phase3_app.processEvents()
        if predicate():
            return
        QTest.qWait(10)
    raise AssertionError("Phase 3 desktop worker did not settle")


def settle(app, view):
    wait(app, lambda: not view._jobs)


@pytest.fixture
def phase3_window(phase3_app, tmp_path, monkeypatch):
    class ForbiddenAudio:
        def __init__(self, *args, **kwargs):
            raise AssertionError("Phase 3 desktop tests must not initialize microphone or TTS")

    monkeypatch.setitem(
        sys.modules,
        "jarvis.voice",
        SimpleNamespace(VoiceInput=ForbiddenAudio, SpeechOutput=ForbiddenAudio),
    )
    settings = Settings(data_dir=tmp_path / "data", allowed_roots=[tmp_path], model="stub-local")
    store = Store(settings.data_dir)
    engine = TaskEngine(settings, store)
    provider = StubProvider()
    service = JarvisService(settings, store, engine, provider=provider)
    launches = []

    def no_os_launch(argv, label):
        launches.append((argv, label))
        return {
            "verified": True,
            "evidence": "launcher_accepted",
            "app": label,
            "pid": 1234,
            "detail": "Test launcher; actual window visibility was not tested.",
        }

    monkeypatch.setattr(engine.registry, "_launch", no_os_launch)
    monkeypatch.setattr(engine.registry, "application_path", lambda app: tmp_path / f"{app}.exe")
    view = MainWindow(service, settings, store, engine)
    view._test_provider = provider
    view._test_launches = launches
    view._system_timer.stop()
    view.show()
    settle(phase3_app, view)
    yield view
    provider.release.set()
    view.interrupt()
    settle(phase3_app, view)
    view.close()
    wait(phase3_app, lambda: not view._jobs and not view.isVisible())
    view.deleteLater()
    phase3_app.processEvents()
    store.close()


def selected_task(view, identity):
    row = next(i for i, task in enumerate(view._tasks) if task["id"] == identity)
    view.task_table.selectRow(row)


def select_routine(view, identity):
    view.routine_choice.setCurrentIndex(view.routine_choice.findData(identity))


def readonly_routine(view, tmp_path, name="Inspect project"):
    text = tmp_path / "notes.txt"
    text.write_text("Untrusted test file content", encoding="utf-8")
    return view.workflows.create_routine(
        name,
        [
            {"tool": "list_directory", "arguments": {"path": str(tmp_path)}},
            {"tool": "read_file", "arguments": {"path": str(text)}},
        ],
    )


def test_phase3_startup_is_distinct_and_does_not_open_audio_or_business(phase3_window):
    view = phase3_window
    assert view.windowTitle() == "JARVIS · Command Center"
    assert {"Mission Control", "Memory Explorer", "Workflows", "System", "Business"} <= set(
        view.page_titles
    )
    assert view._voice is None and view._speech is None and view.voice_controller.input is None
    assert view._test_provider.messages == []
    assert view._business is None
    assert not (view.settings.data_dir / "business.sqlite3").exists()
    sample = json.loads(view.business_summary.toPlainText())
    assert sample["is_sample"] is True
    assert "SAMPLE DATA" in view.business_notice.text()


def test_project_development_routine_executes_through_two_separate_ui_approvals(
    phase3_app,
    phase3_window,
    tmp_path,
):
    view = phase3_window
    root = tmp_path / "registered-project"
    root.mkdir()
    view.project_name.setText("Registered project")
    view.project_path.setText(str(root))
    view.register_project()
    settle(phase3_app, view)
    project = view.workflows.projects()[0]
    view.project_choice.setCurrentIndex(view.project_choice.findData(project["id"]))
    view.select_project_context()
    settle(phase3_app, view)
    assert "Registered project" in view.context_ribbon.text()
    view.create_development_routine()
    settle(phase3_app, view)
    routine = view.workflows.routines()[0]
    select_routine(view, routine["id"])
    assert view.routine_preview.count() == 2
    assert not view.routine_enabled.isChecked()
    assert view._test_launches == []
    view.routine_enabled.setChecked(True)
    view.enable_routine()
    settle(phase3_app, view)
    view.mode_choice.setCurrentText("manual")
    view.save_configuration()
    settle(phase3_app, view)
    assert view.settings.mode == "manual"
    view.run_routine()
    settle(phase3_app, view)
    first = view.workflows.runs()[0]
    assert first["state"] == "awaiting_approval"
    assert view._test_launches == []
    selected_task(view, first["task_id"])
    assert view.approve_button.isEnabled()
    view.task_operation("approve")
    settle(phase3_app, view)
    second = view.workflows.get_run(first["id"])
    assert second["state"] == "awaiting_approval"
    assert second["task_id"] != first["task_id"]
    assert len(view._test_launches) == 1
    selected_task(view, second["task_id"])
    view.task_operation("approve")
    settle(phase3_app, view)
    completed = view.workflows.get_run(first["id"])
    assert completed["state"] == "completed"
    assert completed["step_index"] == 2
    assert all(item["verified"] for item in completed["results"])
    assert [label for _, label in view._test_launches] == ["Explorer", "vscode"]
    assert view._test_provider.messages == []
    assert view.workflow_table.rowCount() == 1
    view.workflow_table.selectRow(0)
    assert json.loads(view.workflow_detail.toPlainText())["state"] == "completed"


def test_custom_routine_reads_real_approved_files_and_reports_verified_steps(
    phase3_app,
    phase3_window,
    tmp_path,
):
    view = phase3_window
    routine = readonly_routine(view, tmp_path)
    view.refresh()
    settle(phase3_app, view)
    select_routine(view, routine["id"])
    view.routine_enabled.setChecked(True)
    view.enable_routine()
    settle(phase3_app, view)
    view.run_routine()
    settle(phase3_app, view)
    run = view.workflows.runs()[0]
    assert run["state"] == "completed"
    assert [item["tool"] for item in run["results"]] == ["list_directory", "read_file"]
    assert all(item["verified"] for item in run["results"])
    assert len(view._tasks) == 2
    assert view._test_launches == []
    # Inspection permission does not persist file text in routine replay/history.
    assert "Untrusted test file content" not in json.dumps(view.workflows.export())
    assert "Untrusted test file content" not in json.dumps(view.store.export())


def test_unsaved_routine_edits_survive_refresh_and_cannot_execute(
    phase3_app,
    phase3_window,
    tmp_path,
):
    view = phase3_window
    routine = readonly_routine(view, tmp_path, name="Z saved routine")
    view.workflows.set_enabled(routine["id"], True)
    view.refresh()
    settle(phase3_app, view)
    select_routine(view, routine["id"])
    view._navigate(5)
    view.routine_name.selectAll()
    QTest.keyClicks(view.routine_name, "Unsaved draft")
    assert view._routine_dirty
    assert not view.run_routine_button.isEnabled()
    view.workflows.create_routine("A new earlier routine", routine["steps"])
    view.refresh()
    settle(phase3_app, view)
    assert view.routine_choice.currentData() == routine["id"]
    assert view.routine_name.text() == "Unsaved draft"
    assert view.routine_preview.count() == 2
    assert view._routine_dirty
    view.run_routine()
    settle(phase3_app, view)
    assert view.workflows.runs() == []
    assert view.workflows.routines()[-1]["name"] == "Z saved routine"
    view.save_routine()
    settle(phase3_app, view)
    stored = next(item for item in view.workflows.routines() if item["id"] == routine["id"])
    assert stored["name"] == "Unsaved draft"
    assert not stored["enabled"]
    assert not view._routine_dirty
    assert not view.run_routine_button.isEnabled()


def test_selected_workflow_identity_survives_new_run_and_refresh(
    phase3_app,
    phase3_window,
    tmp_path,
):
    view = phase3_window
    routine = readonly_routine(view, tmp_path)
    view.workflows.set_enabled(routine["id"], True)
    first = view.workflows.start(routine["id"])
    view.refresh()
    settle(phase3_app, view)
    view.workflow_table.selectRow(0)
    view.workflows.start(routine["id"])
    view.refresh()
    settle(phase3_app, view)
    assert view._selected_workflow()["id"] == first["id"]
    assert json.loads(view.workflow_detail.toPlainText())["id"] == first["id"]


def test_pending_foreground_snapshot_is_discarded_after_permission_revocation(
    phase3_app,
    phase3_window,
    monkeypatch,
):
    view = phase3_window
    started, release = threading.Event(), threading.Event()
    marker = "FICTIONAL_PRIVATE_WINDOW_TITLE"
    result = AwarenessSnapshot(
        system=SystemMetricsSnapshot(sampled_at="test time", cpu_percent=30, memory_percent=60),
        desktop=DesktopContextSnapshot(
            sampled_at="test time",
            available=True,
            consent_granted=True,
            window_title=marker,
            process_name="test.exe",
            pid=123,
        ),
    )

    def blocked(metrics, context, *, consent=False):
        assert consent is True
        assert threading.current_thread() is not threading.main_thread()
        started.set()
        release.wait(3)
        return result

    monkeypatch.setattr(awareness, "collect_awareness", blocked)
    view.settings.desktop_context_enabled = True
    view.refresh_system(force=True)
    try:
        wait(phase3_app, started.is_set)
        view.settings.desktop_context_enabled = False
    finally:
        release.set()
    settle(phase3_app, view)
    assert "desktop" not in view._awareness_data
    assert marker not in view.system_details.toPlainText()
    assert marker not in view.conversation.toPlainText()
    assert marker not in json.dumps(view.store.export())
    assert "30.0%" in view.system_summary.text()


def test_business_ui_opens_only_after_explicit_action_and_records_exact_profit(
    phase3_app,
    phase3_window,
):
    view = phase3_window
    assert view._business is None
    assert not (view.settings.data_dir / "business.sqlite3").exists()
    view.open_business_ledger()
    settle(phase3_app, view)
    assert (view.settings.data_dir / "business.sqlite3").is_file()
    assert "LOCAL RECORDS" in view.business_notice.text()
    assert json.loads(view.business_summary.toPlainText())["is_sample"] is False
    view.inventory_name.setText("User-entered test item")
    view.inventory_sku.setText("test-sku")
    view.inventory_quantity.setValue(3)
    view.inventory_cost.setText("10.01")
    view.add_business_inventory()
    settle(phase3_app, view)
    assert view.order_product.count() == 1
    view.order_quantity.setValue(2)
    view.order_sale.setText("15.01")
    view.order_cost.setText("0.25")
    view.add_business_order()
    settle(phase3_app, view)
    assert view.business_table.rowCount() == 1
    view.business_table.selectRow(0)
    view.business_operation("confirm_payment")
    settle(phase3_app, view)
    assert view.business_table.item(0, 3).text() == "Manual confirmation"
    assert json.loads(view.business_order_detail.toPlainText())["payment_confirmed_manually"]
    view.business_operation("fulfill_order")
    settle(phase3_app, view)
    summary = json.loads(view.business_summary.toPlainText())
    assert summary["externally_verified"] is False
    assert summary["totals_by_currency"][0]["realized_profit_minor"] == 975
    assert summary["totals_by_currency"][0]["display"]["realized_profit"] == "9.75"
    assert view.business_table.item(0, 2).text() == "recorded_fulfilled"
    assert view._test_launches == [] and view._test_provider.messages == []


def test_long_conversation_keeps_phase3_ui_responsive_and_interruptible(
    phase3_app,
    phase3_window,
):
    view = phase3_window
    view._test_provider.release.clear()
    view.composer.setPlainText("Explain an engineering tradeoff")
    view.send_message()
    wait(phase3_app, view._test_provider.started.is_set)
    ticks = []
    timer = QTimer()
    timer.setInterval(10)
    timer.timeout.connect(lambda: ticks.append(1))
    timer.start()
    try:
        wait(phase3_app, lambda: len(ticks) >= 5)
        assert "chat" in view._jobs
        wait(phase3_app, lambda: view.core.state == "thinking")
        view.toggle_compact()
        assert view._compact
        view.toggle_compact()
        assert not view._compact
        view.interrupt()
        settle(phase3_app, view)
    finally:
        timer.stop()
        view._test_provider.release.set()
    assert view.send_button.isEnabled()
    assert "cancelled" in view.conversation.toPlainText().lower()


def test_business_selection_survives_new_records_without_rebinding_payment_action(
    phase3_app,
    phase3_window,
    monkeypatch,
):
    view = phase3_window
    view.open_business_ledger()
    settle(phase3_app, view)
    product = view._business.add_inventory("First item", "first", 10, "10.00")
    first = view._business.create_order(product["id"], 1, "20.00")
    view.refresh_business()
    settle(phase3_app, view)
    view.business_table.selectRow(0)
    assert json.loads(view.business_order_detail.toPlainText())["id"] == first["id"]
    second_product = view._business.add_inventory("Second item", "second", 10, "10.00")
    second = view._business.create_order(second_product["id"], 1, "30.00")
    # New rows can precede the selected row; a row index must not become consent
    # to record payment for a different order.
    original_orders = view._business.orders
    monkeypatch.setattr(
        view._business,
        "orders",
        lambda: sorted(original_orders(), key=lambda order: order["id"] != second["id"]),
    )
    view.refresh_business()
    settle(phase3_app, view)
    assert view._business_orders[view.business_table.currentRow()]["id"] == first["id"]
    assert json.loads(view.business_order_detail.toPlainText())["id"] == first["id"]
    assert view.order_product.currentData() == product["id"]
    view.business_operation("confirm_payment")
    settle(phase3_app, view)
    recorded = view._business.export()["orders"]
    by_id = {order["id"]: order for order in recorded}
    assert by_id[first["id"]]["payment_confirmed_manually"]
    assert not by_id[second["id"]]["payment_confirmed_manually"]


def test_compact_roundtrip_and_reduced_motion_preserve_privacy_configuration(
    phase3_app,
    phase3_window,
):
    view = phase3_window
    view.reduce_motion_check.setChecked(True)
    view.save_configuration()
    settle(phase3_app, view)
    assert load_settings(view.settings.data_dir).reduce_motion
    assert not view.settings.wake_enabled and not view.settings.desktop_context_enabled
    view.voice_controller.session.state = VoiceState.WAKE_WORD_LISTENING
    view._update_presence()
    # The core must not claim active capture solely because a state name exists.
    assert view.core.state == "idle"
    assert view.core.reduce_motion
    assert not view.core.timer.isActive()
    view.toggle_compact()
    assert view._compact and not view.sidebar.isVisible()
    assert view.expand_button.isVisible()
    view.toggle_compact()
    assert not view._compact and view.sidebar.isVisible()
    assert not view.expand_button.isVisible()
    assert view.core.state == "idle"
    assert view.core.reduce_motion
    assert not view.core.timer.isActive()
    assert view.voice_controller.input is None

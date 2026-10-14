"""Measured dashboard, literal text, bounded histories and exact approval IDs."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QPushButton

from jarvis.ui_dashboard import IntelligenceDashboard


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def dashboard(app):
    widget = IntelligenceDashboard()
    widget.resize(372, 720)
    widget.show()
    app.processEvents()
    yield widget
    widget.close()
    widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()


def _task(identity="task-1", state="running", **values):
    return dict(id=identity, tool="open_app", arguments={"app": "chrome"}, state=state, **values)


def test_empty_cards_are_meaningful_not_screenshot_example_data(dashboard):
    assert dashboard.active_badge.text() == "Standby"
    assert "No active tasks" in dashboard.active_empty.text()
    assert dashboard.approval_badge.text() == "None"
    assert dashboard.task_rows == []
    assert dashboard.execution_rows == []
    assert dashboard.metrics["cpu"].value_label.text() == "—"
    assert dashboard.temperature_label.text() == "—"
    assert dashboard.network_label.text() == "—"
    assert "GPT-4o" not in dashboard.model_label.text()
    assert dashboard.usage_label._source == "Tokens      —"


def test_panel_icons_are_native_pixmaps_and_titles_remain_real_text(dashboard):
    for card, title in (
        (dashboard.active_card, "Active Tasks"),
        (dashboard.system_card, "System Status"),
        (dashboard.ai_card, "AI Status"),
        (dashboard.tools_card, "Tool Execution"),
        (dashboard.approvals_card, "Approval Requests"),
    ):
        icon = card.findChild(QLabel, "DashboardGlyph")
        assert icon.text() == ""
        assert not icon.pixmap().isNull()
        assert card.findChild(QLabel, "DashboardTitle")._source == title
        assert not card.details.icon().isNull()
    assert dashboard.ai_icon.text() == ""
    assert not dashboard.ai_icon.pixmap().isNull()


def test_only_user_jobs_are_visible_and_unknown_progress_is_indeterminate(dashboard):
    dashboard.update_activity(["refresh", "awareness", "chat"], [], [], [])
    assert dashboard.active_badge.text() == "1 active"
    assert dashboard.task_rows[0].title_label._source == "Chat"
    progress = dashboard.task_rows[0].progress_bar
    assert progress.minimum() == 0 and progress.maximum() == 0


def test_plan_progress_uses_completed_steps_and_deduplicates_its_task(dashboard):
    action = {
        "id": "run-1",
        "name": "Open requested apps",
        "state": "running",
        "steps": [
            {"state": "completed", "task_id": "task-1"},
            {"state": "running", "task_id": "task-2"},
            {"state": "queued", "task_id": None},
        ],
    }
    dashboard.update_activity([], [_task("task-2")], [action], [])
    assert dashboard.active_badge.text() == "1 active"
    assert len(dashboard.task_rows) == 1
    assert dashboard.task_rows[0].progress_bar.value() == 33
    assert dashboard.task_rows[0].identity == "run-1"


def test_approval_has_no_side_effect_until_click_then_emits_exact_task_id(app, dashboard):
    approved, denied, selected = [], [], []
    dashboard.approve_requested.connect(approved.append)
    dashboard.deny_requested.connect(denied.append)
    dashboard.task_selected.connect(selected.append)
    task = _task("exact-task-id", "awaiting_approval")
    dashboard.update_activity([], [task], [], [])
    assert approved == denied == selected == []
    frame = dashboard.approval_rows[0]
    assert frame.property("taskId") == "exact-task-id"
    QTest.mouseClick(frame.findChild(QPushButton, "DashboardApprove"), Qt.MouseButton.LeftButton)
    QTest.mouseClick(frame.findChild(QPushButton, "DashboardDeny"), Qt.MouseButton.LeftButton)
    assert approved == ["exact-task-id"]
    assert denied == ["exact-task-id"]
    dashboard.update_activity([], [task], [], [], stopped=True)
    assert not dashboard.approval_rows[0].findChild(QPushButton, "DashboardApprove").isEnabled()
    assert not dashboard.approval_rows[0].findChild(QPushButton, "DashboardDeny").isEnabled()
    assert dashboard.active_badge.text() == "Stopped"


def test_unusable_task_id_is_never_truncated_into_an_approval(dashboard):
    dashboard.update_activity([], [_task("x" * 129, "awaiting_approval")], [], [])
    assert dashboard.approval_rows == []
    assert dashboard.approval_badge.text() == "None"


def test_actual_measurements_have_bounded_history_gaps_and_no_duplicate_stamp(dashboard):
    sample = {
        "sampled_at": "one",
        "cpu_percent": 31,
        "memory_percent": 42,
        "disk_percent": 68,
        "disk_total_bytes": 1024**4,
        "disk_used_bytes": 680 * 1024**3,
        "network_bytes_per_second": 2 * 1024**2,
    }
    dashboard.update_system(sample)
    assert dashboard.system_badge.text() == "Measured"
    assert dashboard.metrics["cpu"].history[-1] == 31
    assert dashboard.metrics["disk"].value_label.text() == "68%"
    assert dashboard.network_label.text() == "2.0 MB/s"
    count = len(dashboard.metrics["cpu"].history)
    dashboard.update_system(sample)
    assert len(dashboard.metrics["cpu"].history) == count
    dashboard.update_system({"sampled_at": "gap", "cpu_percent": None})
    assert dashboard.metrics["cpu"].history[-1] is None
    assert dashboard.metrics["cpu"].value_label.text() == "—"
    for index in range(100):
        dashboard.update_system({"sampled_at": str(index), "cpu_percent": index})
    assert len(dashboard.metrics["cpu"].history) == 60
    assert dashboard.metrics["cpu"].history[0] == 40
    assert dashboard.metrics["cpu"].history[-1] == 99


@pytest.mark.parametrize("value", [True, -1, 101, float("nan"), float("inf"), "14%", 2**10000])
def test_invalid_resource_values_are_unavailable_not_fake_zero(dashboard, value):
    dashboard.update_system({"cpu_percent": value, "memory_percent": value, "disk_percent": value})
    assert dashboard.metrics["cpu"].history[-1] is None
    assert dashboard.metrics["ram"].history[-1] is None
    assert dashboard.metrics["disk"].history[-1] is None
    assert dashboard.system_badge.text() == "Not sampled"


def test_ai_card_uses_configured_provider_measured_latency_and_reported_tokens(dashboard):
    dashboard.update_ai(
        "Ollama", "qwen3:8b", "Ready", 1.25, {"input_tokens": 100, "output_tokens": 32}
    )
    assert dashboard.provider_label._source == "Ollama"
    assert dashboard.model_label._source == "qwen3:8b"
    assert dashboard.ai_badge.text() == "Ready"
    assert "1.2s" in dashboard.latency_label._source
    assert "132" in dashboard.usage_label._source
    dashboard.update_ai("Ollama", "qwen3:8b", "Not checked", None, {})
    assert "—" in dashboard.latency_label._source
    assert "—" in dashboard.usage_label._source


def test_failed_tool_uses_actual_duration_and_failure_evidence(dashboard):
    task = _task("failure", "failed", duration_seconds=2.75, error="Focus refused by Windows")
    dashboard.update_activity([], [task], [], [])
    row = dashboard.execution_rows[0]
    assert row.state_label.text() == "Failed"
    assert row.duration_label.text() == "2.8s"
    assert row.toolTip() == "Focus refused by Windows"


def test_external_text_is_literal_bounded_and_column_resizes(app, dashboard):
    markup = "<b>not markup</b>" + "x" * 1000
    dashboard.update_ai(markup, markup, "<b>online</b>", None, {})
    dashboard.update_activity([], [_task("literal", "awaiting_approval", error=markup)], [], [])
    dashboard.resize(280, 500)
    app.processEvents()
    assert dashboard.horizontalScrollBar().maximum() == 0
    assert all(
        label.textFormat() == Qt.TextFormat.PlainText for label in dashboard.findChildren(QLabel)
    )
    assert dashboard.provider_label._source.startswith("<b>not markup</b>")
    assert len(dashboard.provider_label._source) == 80
    assert dashboard.approval_rows[0].property("taskId") == "literal"


def test_unchanged_activity_snapshot_keeps_focused_approval_widgets(dashboard):
    tasks = [_task("same", "awaiting_approval")]
    dashboard.update_activity([], tasks, [], [])
    original = dashboard.approval_rows[0]
    dashboard.update_activity([], tasks, [], [])
    assert dashboard.approval_rows[0] is original


def test_website_approval_displays_requested_target_and_actual_one_use_effect(dashboard):
    dashboard.update_activity(
        [],
        [
            dict(
                id="website-id",
                tool="open_website",
                state="awaiting_approval",
                arguments={"target": "https://docs.python.org/3/"},
            )
        ],
        [],
        [],
    )
    labels = dashboard.approval_rows[0].findChildren(QLabel)
    assert any(getattr(label, "_source", "") == "https://docs.python.org/3/" for label in labels)
    assert any(
        "Approve once" in getattr(label, "_source", "")
        and "external website" in getattr(label, "_source", "")
        for label in labels
    )


def test_reduced_motion_stops_busy_animation_without_inventing_progress(dashboard):
    dashboard.set_reduce_motion(True)
    dashboard.update_activity(["chat"], [], [], [])
    row = dashboard.task_rows[0]
    assert row._indeterminate
    assert row.progress_bar.maximum() == 1
    assert "unavailable" in row.progress_bar.accessibleDescription()
    dashboard.set_reduce_motion(False)
    assert row.progress_bar.maximum() == 0


@pytest.mark.parametrize(
    "health,badge",
    [
        ("Local Ollama connected; selected model installed", "Connected"),
        ("Ollama connected; selected model not installed", "Model missing"),
        ("Ollama unavailable; start Ollama and rerun health check", "Offline"),
        ("Cloud adapter configured; live credentials not tested", "Unverified"),
        ("Cloud permission disabled", "Permission off"),
    ],
)
def test_connection_badge_keeps_missing_model_and_unverified_credentials_explicit(
    dashboard, health, badge
):
    dashboard.update_ai("provider", "model", health, None, {})
    assert dashboard.ai_badge.text() == badge
    assert dashboard.ai_badge.toolTip() == health

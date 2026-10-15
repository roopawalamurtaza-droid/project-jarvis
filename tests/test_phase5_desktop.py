"""Phase 5 Qt integration without real input, browser navigation or user files."""

from __future__ import annotations

import threading

from PySide6.QtCore import Qt, QThread, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QDialog, QLineEdit, QListWidget, QPlainTextEdit, QPushButton
from test_desktop import app as desktop_app
from test_desktop import wait_until
from test_desktop import window as desktop_window

from jarvis.config import load_settings
from jarvis.desktop import BROWSER_HUMAN_GRANT

app = desktop_app
window = desktop_window


def attach_computer_service(window, *, paused=False):
    state = {
        "paused": paused,
        "reads": 0,
        "pause": 0,
        "resume": 0,
        "manual": False,
        "challenge": False,
    }

    def status():
        assert threading.current_thread() is not threading.main_thread()
        state["reads"] += 1
        return {
            "enabled": window.settings.computer_use_enabled,
            "paused": state["paused"],
            "windows": {"available": True, "status": "ready", "busy": False},
            "browser": {
                "available": True,
                "status": "awaiting_user" if state["challenge"] else "ready",
                "busy": False,
                "manual_mode": state["manual"],
                "last_observation": {"url": "https://www.python.org/", "title": "Python"},
            },
        }

    def pause():
        assert threading.current_thread() is not threading.main_thread()
        state["pause"] += 1
        state["paused"] = True
        return status()

    def resume():
        assert threading.current_thread() is not threading.main_thread()
        state["resume"] += 1
        state["paused"] = False
        return status()

    window.service.computer_status = status
    window.service.pause_computer_use = pause
    window.service.resume_computer_use = resume
    return state


def test_computer_use_is_opt_in_and_does_not_observe_at_startup(app, window):
    assert not window.computer_use_check.isChecked()
    assert not window.browser_automation_check.isChecked()
    assert window._computer_status == {}
    assert window._voice is None and window._speech is None
    assert not window.computer_pause_button.isEnabled()
    assert not window.computer_resume_button.isEnabled()
    assert window.page_titles[:11] == (
        "Assistant",
        "Mission Control",
        "Memory Explorer",
        "Timeline",
        "Settings",
        "Workflows",
        "System",
        "Diagnostics",
        "Business",
        "Application Library",
        "Browser",
    )
    assert window.page_titles[11] == "Computer Use"
    assert len([button for button in window.nav if button.isVisible()]) == 7


def test_computer_use_view_uses_worker_status_and_gui_delivery(app, window):
    state = attach_computer_service(window)
    received = []
    show = window._show_computer_status

    def checked(result):
        received.append(QThread.currentThread() == app.thread())
        show(result)

    window._show_computer_status = checked
    window._navigate(11)
    wait_until(app, lambda: not window._jobs)
    assert state["reads"] == 1
    assert received == [True]
    assert "Idle" in window.computer_control_status.text()
    assert "https://www.python.org/" in window.computer_target.text()
    assert "permission off" in window.computer_availability.text()
    assert "last_observation" in window.computer_observation.toPlainText()
    assert window.computer_pause_button.isEnabled()
    assert window._voice is None and window._speech is None


def test_command_palette_reaches_new_view_without_changing_reference_sidebar(app, window):
    attach_computer_service(window)
    selected = []

    def choose_computer_use():
        dialog = next(
            child
            for child in window.findChildren(QDialog)
            if child.windowTitle() == "JARVIS commands"
        )
        dialog.findChild(QLineEdit).setText("Computer Use")
        choices = dialog.findChild(QListWidget)
        item = next(
            choices.item(i) for i in range(choices.count()) if not choices.item(i).isHidden()
        )
        selected.append(item.text())
        choices.itemActivated.emit(item)

    QTimer.singleShot(0, choose_computer_use)
    window.command_palette()
    wait_until(app, lambda: not window._jobs)
    assert selected == ["Computer Use"]
    assert window.pages.currentIndex() == 11


def test_new_permissions_save_and_reconfigure_without_losing_existing_settings(app, window):
    observed = []

    def reconfigure(settings):
        assert threading.current_thread() is not threading.main_thread()
        observed.append(settings.model_copy(deep=True))

    window.service.reconfigure = reconfigure
    window.service.secret_store.values["OPENAI_API_KEY"] = "existing-test-only-secret"
    previous_roots = list(window.settings.allowed_roots)
    window.model_edit.setText("existing-provider-model")
    window.pronunciation_edit.setPlainText('{"JARVIS":"Jarvis"}')
    window.computer_use_check.setChecked(True)
    window.browser_automation_check.setChecked(True)
    window.save_configuration()
    wait_until(app, lambda: not window._jobs)
    persisted = load_settings(window.settings.data_dir)
    assert persisted.computer_use_enabled and persisted.browser_automation_enabled
    assert persisted.model == "existing-provider-model"
    assert persisted.allowed_roots == previous_roots
    assert persisted.pronunciation_replacements == {"JARVIS": "Jarvis"}
    assert not persisted.wake_enabled and not persisted.cloud_allowed
    assert observed[0].computer_use_enabled and observed[0].browser_automation_enabled
    assert window.service.secret_store.values["OPENAI_API_KEY"] == "existing-test-only-secret"
    assert "existing-test-only-secret" not in window.build_health_label.text()
    window.computer_use_check.setChecked(False)
    window.browser_automation_check.setChecked(False)
    window.save_configuration()
    wait_until(app, lambda: not window._jobs)
    persisted = load_settings(window.settings.data_dir)
    assert not persisted.computer_use_enabled and not persisted.browser_automation_enabled


def test_status_poll_is_bounded_and_hidden_views_do_not_observe(app, window):
    state = attach_computer_service(window)
    window.refresh_computer_status()
    assert state["reads"] == 0
    started, release = threading.Event(), threading.Event()

    def slow_status():
        started.set()
        assert release.wait(3)
        return {"paused": False, "windows": {"status": "ready"}, "browser": {}}

    window.service.computer_status = slow_status
    window._navigate(11)
    try:
        wait_until(app, started.is_set)
        first = window._jobs["computer-status"]
        window.refresh_computer_status(force=True)
        assert window._jobs["computer-status"] is first
        window._computer_status_generation += 1
        release.set()
        wait_until(app, lambda: not window._jobs)
        assert window._computer_status == {}
    finally:
        release.set()


def test_pause_resume_and_stop_use_shared_service_without_task_replay(app, window):
    state = attach_computer_service(window)
    task = window.engine.submit("desktop_write_note", {"path": "C:/test/new.txt", "text": "Exact"})
    window._navigate(11)
    wait_until(app, lambda: not window._jobs)
    QTest.mouseClick(window.computer_pause_button, Qt.MouseButton.LeftButton)
    wait_until(app, lambda: not window._jobs)
    assert state["pause"] == 1 and state["paused"]
    assert "Paused" in window.computer_control_status.text()
    assert not window.computer_pause_button.isEnabled()
    assert window.computer_resume_button.isEnabled()
    QTest.mouseClick(window.computer_resume_button, Qt.MouseButton.LeftButton)
    wait_until(app, lambda: not window._jobs)
    assert state["resume"] == 1 and not state["paused"]
    assert window.store.get_task(task["id"])["state"] == "awaiting_approval"
    QTest.mouseClick(window.computer_stop_button, Qt.MouseButton.LeftButton)
    wait_until(app, lambda: not window._jobs)
    assert window.service.emergency_count == 1
    assert window._stopped
    assert not window.computer_pause_button.isEnabled()
    assert not window.computer_resume_button.isEnabled()
    assert not window.computer_stop_button.isEnabled()


def test_notepad_note_exact_text_and_path_are_reviewed_before_dashboard_approval(app, window):
    text = "Testing JARVIS automation\nLiteral <b>note</b> & punctuation."
    path = "C:/Approved folder/jarvis-test.txt"
    task = window.engine.submit("desktop_write_note", {"path": path, "text": text})

    def preview(task_id):
        assert threading.current_thread() is not threading.main_thread()
        assert task_id == task["id"]
        return dict(task)

    window.service.approval_preview = preview
    window.refresh()
    wait_until(app, lambda: not window._jobs)
    seen = []

    def review_pending_note():
        dialog = window.findChild(QDialog, "NoteApprovalReview")
        preview = dialog.findChild(QPlainTextEdit).toPlainText()
        seen.append(preview)
        assert path in preview and text in preview
        assert window.store.get_task(task["id"])["state"] == "awaiting_approval"
        dialog.reject()

    review_timer = QTimer(window)
    review_timer.setInterval(10)
    review_timer.timeout.connect(
        lambda: (
            (review_timer.stop(), review_pending_note())
            if any(
                dialog.isVisible() and dialog.objectName() == "NoteApprovalReview"
                for dialog in window.findChildren(QDialog)
            )
            else None
        )
    )
    review_timer.start()
    window._dashboard_task_operation(task["id"], "approve")
    wait_until(app, lambda: not window._jobs)
    assert seen and window.store.get_task(task["id"])["state"] == "awaiting_approval"
    assert path in window.task_detail.toPlainText()
    assert text not in window.task_detail.toPlainText()

    def approve_exact_note():
        dialog = next(
            dialog
            for dialog in window.findChildren(QDialog)
            if dialog.objectName() == "NoteApprovalReview" and dialog.isVisible()
        )
        QTest.mouseClick(
            dialog.findChild(QPushButton, "ApproveExactNote"), Qt.MouseButton.LeftButton
        )

    review_timer.timeout.disconnect()
    review_timer.timeout.connect(
        lambda: (
            (review_timer.stop(), approve_exact_note())
            if any(
                dialog.isVisible() and dialog.objectName() == "NoteApprovalReview"
                for dialog in window.findChildren(QDialog)
            )
            else None
        )
    )
    review_timer.start()
    window.task_operation("approve")
    wait_until(app, lambda: not window._jobs)
    assert window.store.get_task(task["id"])["state"] == "completed"
    assert '"verified": true' in window.task_detail.toPlainText()


def test_note_approval_fails_safely_without_literal_live_preview(app, window):
    task = window.engine.submit(
        "desktop_write_note", {"path": "C:/Approved/new.txt", "text": "Private note"}
    )
    window.refresh()
    wait_until(app, lambda: not window._jobs)
    window._dashboard_task_operation(task["id"], "approve")
    assert "preview is unavailable" in window.status_label.text()
    assert window.store.get_task(task["id"])["state"] == "awaiting_approval"
    window.service.approval_preview = lambda identity: window.store.get_task(identity)
    window.task_operation("approve")
    wait_until(app, lambda: not window._jobs)
    assert "Live note text is unavailable" in window.status_label.text()
    assert window.store.get_task(task["id"])["state"] == "awaiting_approval"


def test_external_status_is_plain_text_and_observation_display_is_bounded(app, window):
    window._show_computer_status(
        {
            "windows": {"busy": True, "target": "<img src='https://untrusted.invalid'>"},
            "browser": {"status": "<b>login required</b>"},
            "last_observation": "x" * 70000,
        }
    )
    assert window.computer_target.textFormat() == Qt.TextFormat.PlainText
    assert window.computer_availability.textFormat() == Qt.TextFormat.PlainText
    assert "<img" in window.computer_target.text()
    assert "Controlling" in window.computer_control_status.text()
    assert len(window.computer_observation.toPlainText()) < 32200
    assert "Display limited" in window.computer_observation.toPlainText()


def test_browser_human_permission_requires_exact_modal_approval_before_mode_changes(app, window):
    state = attach_computer_service(window)
    state["challenge"] = True
    window.settings.computer_use_enabled = True
    window.settings.browser_automation_enabled = True
    window._navigate(11)
    wait_until(app, lambda: not window._jobs)
    assert window.computer_human_request_button.isEnabled()
    assert not window.computer_human_end_button.isEnabled()
    QTest.mouseClick(window.computer_human_request_button, Qt.MouseButton.LeftButton)
    wait_until(app, lambda: not window._jobs)
    task = window.store.tasks()[0]
    assert task["tool"] == "browser_user_interaction"
    assert task["arguments"] == {"enabled": True}
    assert task["state"] == "awaiting_approval"
    assert not state["manual"]

    def preview(identity):
        assert threading.current_thread() is not threading.main_thread()
        return window.store.get_task(identity)

    window.service.approval_preview = preview
    approve = window.engine.approve
    executed = []

    def grant(identity):
        executed.append(identity)
        state["manual"] = True
        return approve(identity)

    window.engine.approve = grant
    seen = []
    review_timer = QTimer(window)
    review_timer.setInterval(10)
    accept = [False]

    def review_permission():
        dialog = next(
            (
                dialog
                for dialog in window.findChildren(QDialog)
                if dialog.objectName() == "BrowserHumanApprovalReview" and dialog.isVisible()
            ),
            None,
        )
        if dialog is None:
            return
        review_timer.stop()
        content = dialog.findChild(QPlainTextEdit).toPlainText()
        seen.append(content)
        assert BROWSER_HUMAN_GRANT in content
        assert "including requests from page scripts" in content
        assert executed == [] and not state["manual"]
        if accept[0]:
            QTest.mouseClick(
                dialog.findChild(QPushButton, "ApproveHumanBrowserInteraction"),
                Qt.MouseButton.LeftButton,
            )
        else:
            dialog.reject()

    review_timer.timeout.connect(review_permission)
    review_timer.start()
    window._dashboard_task_operation(task["id"], "approve")
    wait_until(app, lambda: not window._jobs)
    assert seen and not state["manual"] and executed == []
    assert window.store.get_task(task["id"])["state"] == "awaiting_approval"
    accept[0] = True
    review_timer.start()
    window.task_operation("approve")
    wait_until(app, lambda: not window._jobs)
    assert executed == [task["id"]] and state["manual"]
    assert "HUMAN BROWSER INTERACTION ACTIVE" in window.computer_human_status.text()
    assert BROWSER_HUMAN_GRANT in window.computer_human_status.text()
    assert "automated input is idle" in window.computer_control_status.text()
    assert window.computer_human_end_button.isEnabled()
    assert not window.computer_human_request_button.isEnabled()


def test_end_human_interaction_uses_shared_tool_while_paused_without_grant_modal(app, window):
    state = attach_computer_service(window, paused=True)
    state["manual"] = True
    original_submit = window.engine.submit
    submitted = []

    def end(tool, arguments):
        assert threading.current_thread() is not threading.main_thread()
        submitted.append((tool, arguments))
        result = original_submit(tool, arguments)
        state["manual"] = False
        return window.engine.approve(result["id"])

    window.engine.submit = end
    window._navigate(11)
    wait_until(app, lambda: not window._jobs)
    assert window.computer_human_end_button.isEnabled()
    QTest.mouseClick(window.computer_human_end_button, Qt.MouseButton.LeftButton)
    wait_until(app, lambda: not window._jobs)
    assert submitted == [("browser_user_interaction", {"enabled": False})]
    assert not state["manual"]
    assert "interaction · off" in window.computer_human_status.text()
    assert state["paused"]

"""Real Qt/controller behavior for the reference layout, with no hardware side effects."""

import threading

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QPushButton
from test_desktop import app as desktop_app
from test_desktop import wait_until
from test_desktop import window as desktop_window

from jarvis.ui_chat import SafeMarkdown

app = desktop_app
window = desktop_window


def test_reference_navigation_retains_all_existing_views(app, window):
    for index in (0, 1, 2, 5, 9, 10, 4):
        QTest.mouseClick(window.nav[index], Qt.MouseButton.LeftButton)
        assert window.pages.currentIndex() == index
    for index in range(len(window.page_titles)):
        window._navigate(index)
        assert window.pages.currentIndex() == index
    assert window._voice is None and window._speech is None


def test_compact_and_restore_have_no_colliding_dashboard(app, window):
    window.resize(1440, 840)
    app.processEvents()
    assert window.dashboard.isVisible() == (window.width() >= 1260)
    window.toggle_compact()
    window.resize(430, 530)
    app.processEvents()
    assert window.width() == 430
    assert not window.dashboard.isVisible()
    assert not window.top_bar.isVisible()
    assert not window.quick_actions.isVisible()
    assert window.mic_button.isVisible() and window.send_button.isVisible()
    mic = window.mic_button.mapTo(window, window.mic_button.rect().topLeft())
    send = window.send_button.mapTo(window, window.send_button.rect().topLeft())
    assert mic.y() != send.y()
    window.toggle_compact()
    app.processEvents()
    assert window.dashboard.isVisible() == (window.width() >= 1260)
    assert window.core.maximumHeight() > 350
    assert window.composer.height() == 46
    assert window.assistant_heading.window() is window
    assert window.presence_caption.window() is window
    assert window.provider_ribbon.window() is window
    assert not any(
        widget.isVisible() and widget is not window and widget is not window.ambient_overlay
        for widget in app.topLevelWidgets()
    )


def test_cards_use_real_permissions_and_do_not_discard_drafts(app, window):
    window._quick_browser()
    wait_until(app, lambda: not window._jobs)
    task = window.store.tasks()[0]
    assert task["tool"] == "open_website" and task["arguments"]["target"] == "google"
    assert task["state"] == "awaiting_approval"
    window.composer.setPlainText("Keep this draft")
    window._quick_coding()
    assert window.composer.toPlainText() == "Keep this draft"
    assert window.service.calls == []
    window._quick_study()
    assert "No routine was started" in window.status_label.text()


def test_exact_dashboard_approval_ignores_current_selection(app, window):
    first = window.engine.submit("open_app", {"app": "notepad"})
    second = dict(first, id="task-2", arguments={"app": "chrome"})
    window.store.put_task(second)
    window.refresh()
    wait_until(app, lambda: not window._jobs)
    window._dashboard_select_task(second["id"])
    window._dashboard_task_operation(first["id"], "approve")
    wait_until(app, lambda: not window._jobs)
    assert window.store.get_task(first["id"])["state"] == "completed"
    assert window.store.get_task(second["id"])["state"] == "awaiting_approval"


def test_mini_shares_voice_state_and_true_mute_without_capture(app, window):
    window.toggle_mini()
    assert window.ambient_overlay.parent() is window
    assert window.ambient_overlay.isVisible()
    window._mini_mute()
    window._update_presence()
    assert window.voice_controller.session.state.value == "MUTED"
    assert window.core.state == "muted"
    assert window.overlay_core.state == "muted"
    assert window._voice is None
    window.dismiss_overlay()
    assert not window.ambient_overlay.isVisible()


def test_markdown_does_not_read_embedded_resources_and_copy_is_literal(app, window):
    raw = '<script>alert(1)</script>\n```python\nprint("safe")\n```\n![x](file:///C:/private)'
    window._append_message("JARVIS", raw)
    browser = window.conversation.findChildren(SafeMarkdown)[-1]
    assert browser.loadResource(2, "file:///C:/private") is None
    assert not browser.openExternalLinks() and not browser.openLinks()
    row = window.conversation._messages[-1][2]
    copy = next(b for b in row.findChildren(QPushButton) if b.text() == "Copy")
    QTest.mouseClick(copy, Qt.MouseButton.LeftButton)
    assert app.clipboard().text() == raw
    assert raw in window.conversation.toPlainText()


@pytest.mark.parametrize("cancel", [False, True])
def test_real_worker_delta_draft_finishes_once_or_is_discarded(app, window, cancel):
    emitted, release = threading.Event(), threading.Event()

    def stream_chat(message, session_id=None, cancel=None, *, on_delta=None):
        assert threading.current_thread() is not threading.main_thread()
        on_delta("First real ")
        emitted.set()
        assert release.wait(5)
        if cancel.is_set():
            raise RuntimeError("Interrupted stream")
        on_delta("delta")
        return {"text": "First real delta", "session_id": "stream-test", "usage": {}}

    window.service.chat = stream_chat
    window.composer.setPlainText("Stream a reply")
    window.send_message()
    try:
        wait_until(app, emitted.is_set)
        wait_until(app, lambda: "First real " in window.conversation.toPlainText())
        if cancel:
            window.interrupt()
            assert window.conversation._stream_row is None
        release.set()
        wait_until(app, lambda: not window._jobs)
        transcript = window.conversation.toPlainText()
        if cancel:
            assert "First real " not in transcript
        else:
            assert transcript.count("First real delta") == 1
            assert window.conversation._stream_row is None
    finally:
        release.set()


def test_no_fake_resource_or_capability_availability(app, window):
    window._update_presence()
    assert "unavailable" in window.capability_labels["vision"].text()
    assert "unavailable" in window.context_status_labels["web"].text()
    assert not list(window.dashboard.metrics["cpu"].history) or not window._awareness_data
    window.settings.reduce_motion = True
    window._apply_motion_preferences()
    assert not window.core.timer.isActive()

"""Offscreen desktop tests; providers and audio are deterministic fakes."""

from __future__ import annotations

import os
import sys
import threading
import time
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt, QThread, QTimer
from PySide6.QtGui import QFontMetrics
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from jarvis import desktop
from jarvis.config import Settings, load_settings
from jarvis.desktop import MainWindow
from jarvis.storage import Store


class FakeSecrets:
    def __init__(self):
        self.values = {}

    def set(self, name, value):
        self.values[name] = value

    def delete(self, name):
        self.values.pop(name, None)


class FakeEngine:
    def __init__(self, store):
        self.store = store
        self.stop_count = 0
        self.reset_count = 0

    def submit(self, tool, arguments):
        task = dict(
            id="task-1",
            tool=tool,
            arguments=arguments,
            state="awaiting_approval",
            result=None,
            error=None,
        )
        self.store.put_task(task)
        return task

    def _update(self, task_id, state):
        task = self.store.get_task(task_id)
        task["state"] = state
        task["result"] = {"verified": state == "completed"}
        self.store.put_task(task)
        return task

    def approve(self, task_id):
        return self._update(task_id, "completed")

    def reject(self, task_id):
        return self._update(task_id, "cancelled")

    def cancel(self, task_id):
        return self._update(task_id, "cancelled")

    def emergency_stop(self):
        self.stop_count += 1

    def reset_stop(self):
        self.reset_count += 1


class FakeService:
    def __init__(self, settings, engine):
        self.settings = settings
        self.engine = engine
        self.secret_store = FakeSecrets()
        self.calls = []
        self.started = threading.Event()
        self.release = threading.Event()
        self.release.set()
        self.emergency_count = 0

    def chat(self, message, session_id=None, cancel=None):
        assert threading.current_thread() is not threading.main_thread()
        self.calls.append((message, session_id))
        self.started.set()
        while not self.release.wait(0.01):
            if cancel.is_set():
                raise RuntimeError("Request cancelled")
        return dict(
            text=f"Reply: {message}",
            session_id="session-test",
            provider="fake",
            model="test",
            usage={},
        )

    def emergency_stop(self):
        self.emergency_count += 1
        self.engine.emergency_stop()

    def reset_stop(self):
        self.engine.reset_stop()


@pytest.fixture(scope="session")
def app():
    application = QApplication.instance() or QApplication([])
    application.setQuitOnLastWindowClosed(False)
    return application


def wait_until(app, predicate, timeout=4):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return
        QTest.qWait(10)
    raise AssertionError("Desktop worker did not settle before the test deadline")


@pytest.fixture
def window(app, tmp_path, monkeypatch):
    class ForbiddenAudio:
        def __init__(self, *args, **kwargs):
            raise AssertionError("Audio must never initialize at window startup")

    monkeypatch.setitem(
        sys.modules,
        "jarvis.voice",
        SimpleNamespace(VoiceInput=ForbiddenAudio, SpeechOutput=ForbiddenAudio),
    )
    settings = Settings(data_dir=tmp_path, allowed_roots=[tmp_path])
    store = Store(tmp_path)
    engine = FakeEngine(store)
    service = FakeService(settings, engine)
    view = MainWindow(service, settings, store, engine)
    view.show()
    wait_until(app, lambda: not view._jobs)
    yield view
    service.release.set()
    view.interrupt()
    wait_until(app, lambda: not view._jobs)
    view.close()
    wait_until(app, lambda: not view._jobs and not view.isVisible())
    view.deleteLater()
    app.processEvents()
    store.close()


def test_startup_no_provider_or_audio_and_plain_text_chat(app, window):
    assert window.service.calls == []
    assert window._voice is None
    assert window._speech is None
    assert not window.settings.cloud_allowed
    assert not window.settings.save_history
    assert QFontMetrics(window.font()).inFontUcs4(ord("J"))
    message = "<script>alert('plain text')</script>"
    window.composer.setPlainText(message)
    QTest.keyClick(window.composer, Qt.Key.Key_Return)
    wait_until(app, lambda: not window._jobs)
    assert window.service.calls == [(message, None)]
    assert f"Reply: {message}" in window.conversation.toPlainText()
    assert window.session_id == "session-test"
    assert window.send_button.isEnabled()


def test_workers_deliver_results_on_desktop_thread(app, window):
    received = []
    window._run(
        "thread-check",
        lambda: 42,
        lambda result: received.append((result, QThread.currentThread() == app.thread())),
    )
    wait_until(app, lambda: not window._jobs)
    assert received == [(42, True)]


def test_responsive_chat_and_cooperative_interrupt(app, window):
    window.service.release.clear()
    window.composer.setPlainText("Slow request")
    window.send_message()
    wait_until(app, window.service.started.is_set)
    ticks = []
    timer = QTimer()
    timer.setInterval(10)
    timer.timeout.connect(lambda: ticks.append(1))
    timer.start()
    wait_until(app, lambda: len(ticks) >= 5)
    assert "chat" in window._jobs
    assert not window.send_button.isEnabled()
    window.model_edit.setText("must-not-change-during-chat")
    window.save_configuration()
    assert window.settings.model != "must-not-change-during-chat"
    window.interrupt()
    wait_until(app, lambda: not window._jobs)
    timer.stop()
    assert "Request cancelled" in window.conversation.toPlainText()
    assert window.send_button.isEnabled()


def test_exact_action_approval_and_service_stop(app, window, tmp_path):
    window.tool_choice.setCurrentIndex(4)
    window.tool_path.setText(str(tmp_path / "approved-folder"))
    window.submit_action()
    wait_until(app, lambda: not window._jobs)
    assert window.task_table.rowCount() == 1
    assert window.approve_button.isEnabled()
    assert "approved-folder" in window.task_detail.toPlainText()
    window.task_operation("approve")
    wait_until(app, lambda: not window._jobs)
    assert window.store.get_task("task-1")["state"] == "completed"
    assert not window.approve_button.isEnabled()
    window.emergency_stop()
    wait_until(app, lambda: not window._jobs)
    assert window.service.emergency_count == 1
    assert window._stopped
    window.resume()
    wait_until(app, lambda: not window._jobs)
    assert window.engine.reset_count == 1
    assert not window._stopped


def test_memory_create_edit_search_delete(app, window):
    window.memory_category.setCurrentText("project")
    window.memory_key.setText("JARVIS")
    window.memory_content.setPlainText("Local assistant")
    window.save_memory()
    wait_until(app, lambda: not window._jobs)
    assert window.memory_table.rowCount() == 1
    window.memory_table.selectRow(0)
    window.memory_key.setText("Renamed project")
    window.memory_content.setPlainText("Updated content")
    window.save_memory()
    wait_until(app, lambda: not window._jobs)
    assert [memory["key"] for memory in window.store.memories()] == ["Renamed project"]
    window.memory_search.setText("missing")
    window.refresh()
    wait_until(app, lambda: not window._jobs)
    assert window.memory_table.rowCount() == 0
    window.memory_search.clear()
    window.refresh()
    wait_until(app, lambda: not window._jobs)
    window.memory_table.selectRow(0)
    window.delete_memory()
    wait_until(app, lambda: not window._jobs)
    assert window.store.memories() == []


def test_settings_persist_and_keys_never_appear_in_display(app, window, tmp_path):
    window.provider_choice.setCurrentText("openai")
    window.model_edit.setText("configured-model")
    window.cloud_check.setChecked(True)
    window.history_check.setChecked(True)
    window.mode_choice.setCurrentText("manual")
    window.openai_key_edit.setText("a-test-only-key")
    window.voice_choice.addItem("Test voice")
    window.voice_choice.setCurrentIndex(1)
    window.save_configuration()
    wait_until(app, lambda: not window._jobs)
    persisted = load_settings(tmp_path)
    assert persisted.provider == "openai"
    assert persisted.model == "configured-model"
    assert persisted.cloud_allowed and persisted.save_history
    assert persisted.mode == "manual"
    assert persisted.speech_voice == "Test voice"
    assert window.service.secret_store.values["OPENAI_API_KEY"] == "a-test-only-key"
    assert not window.openai_key_edit.text()
    assert "a-test-only-key" not in window.conversation.toPlainText()
    assert "a-test-only-key" not in window.status_label.text()
    assert "a-test-only-key" not in (tmp_path / "settings.json").read_text()


def test_close_with_active_request_waits_and_retains_workers(app, window):
    window.service.release.clear()
    window.composer.setPlainText("Request during shutdown")
    window.send_message()
    wait_until(app, window.service.started.is_set)
    window.close()
    assert window._closing
    assert window._jobs
    wait_until(app, lambda: not window._jobs and not window.isVisible())


def test_shutdown_deadline_returns_control_without_destroying_live_worker(app, window):
    release = threading.Event()
    window._run("native-work", lambda: release.wait(4))
    window.close()
    window._close_deadline = time.monotonic() - 1
    window._poll_shutdown()
    assert window.isVisible()
    assert not window._closing
    assert "native-work" in window._jobs
    assert "remains open safely" in window.status_label.text()
    release.set()
    wait_until(app, lambda: not window._jobs)


def test_push_to_talk_local_transcription_requires_send(app, window, monkeypatch):
    class FakeVoice:
        def __init__(self, settings):
            self.recording = False

        def start(self, device=None):
            self.recording = True

        def stop(self):
            self.recording = False
            return [0.0]

        def transcribe(self, audio):
            assert threading.current_thread() is not threading.main_thread()
            return "Reviewed voice message"

        def cancel(self):
            self.recording = False

    monkeypatch.setitem(sys.modules, "jarvis.voice", SimpleNamespace(VoiceInput=FakeVoice))
    window.start_recording()
    wait_until(app, lambda: window._voice is not None and window._voice.recording)
    window.stop_recording()
    wait_until(app, lambda: not window._jobs)
    assert window.composer.toPlainText() == "Reviewed voice message"
    assert window.service.calls == []
    assert not window._voice.recording


def test_missing_audio_dependency_is_clear_and_recoverable(app, window, monkeypatch):
    class UnavailableVoice:
        def __init__(self, settings):
            raise RuntimeError("Install voice dependencies to use transcription")

    monkeypatch.setitem(sys.modules, "jarvis.voice", SimpleNamespace(VoiceInput=UnavailableVoice))
    window.start_recording()
    window.stop_recording()
    wait_until(app, lambda: not window._jobs)
    assert "Install voice dependencies" in window.status_label.text()
    assert window.mic_button.isEnabled()
    window.toggle_compact()
    assert window._compact
    assert not window.sidebar.isVisible()
    window.toggle_compact()
    assert window.sidebar.isVisible()


def test_saved_history_transition_blocks_session_changes_and_chat(app, window, monkeypatch):
    window.store.add_message("saved-session", "user", "Saved user message")
    window.refresh()
    wait_until(app, lambda: not window._jobs)
    window.session_id = "old-session"
    entered, release = threading.Event(), threading.Event()
    original_history = window.store.history

    def slow_history(*args, **kwargs):
        entered.set()
        release.wait(4)
        return original_history(*args, **kwargs)

    monkeypatch.setattr(window.store, "history", slow_history)
    window.load_session(window.session_list.item(0))
    wait_until(app, entered.is_set)
    window.composer.setPlainText("Send after loading")
    window.send_message()
    window.new_conversation()
    window.session_list.setCurrentRow(0)
    window.delete_session()
    assert not window.service.calls
    assert window.session_id == "old-session"
    assert window.store.sessions()
    release.set()
    wait_until(app, lambda: not window._jobs)
    assert window.session_id == "saved-session"
    assert "Saved user message" in window.conversation.toPlainText()
    window.send_message()
    wait_until(app, lambda: not window._jobs)
    assert window.service.calls == [("Send after loading", "saved-session")]


def test_settings_transition_blocks_chat_tools_and_recording(app, window, monkeypatch, tmp_path):
    entered, release = threading.Event(), threading.Event()
    original_save = desktop.save_settings

    def slow_save(settings):
        entered.set()
        release.wait(4)
        original_save(settings)

    monkeypatch.setattr(desktop, "save_settings", slow_save)
    window.model_edit.setText("new-model")
    window.save_configuration()
    wait_until(app, entered.is_set)
    window.composer.setPlainText("Send after saving")
    window.send_message()
    window.tool_path.setText(str(tmp_path))
    window.submit_action()
    window.start_recording()
    assert not window.service.calls
    assert window.store.tasks() == []
    assert window._voice is None
    assert window.settings.model != "new-model"
    release.set()
    wait_until(app, lambda: not window._jobs)
    assert window.settings.model == "new-model"
    window.send_message()
    wait_until(app, lambda: not window._jobs)
    assert window.service.calls == [("Send after saving", None)]


def test_deleting_active_session_clears_window_after_transition(app, window):
    window.store.add_message("active-session", "user", "Delete this")
    window.refresh()
    wait_until(app, lambda: not window._jobs)
    window.session_id = "active-session"
    window._append_message("YOU", "Delete this")
    window.session_list.setCurrentRow(0)
    window.delete_session()
    wait_until(app, lambda: not window._jobs)
    assert window.session_id is None
    assert not window.conversation.toPlainText()
    assert window.store.sessions() == []

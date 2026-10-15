"""The new-note gate verifies bytes and never substitutes attempted UI actions."""

from __future__ import annotations

import hashlib
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from jarvis import computer_windows
from jarvis.computer_windows import WindowsComputerService


class NoteBackend:
    """Deterministic UI substitute for policy/verification tests, not native proof."""

    def __init__(self, mode="normal"):
        self.mode = mode
        self.calls = 0
        self.entered = threading.Event()
        self.release = threading.Event()

    def write_note(self, path, text, check, revalidate, observe):
        self.calls += 1
        self.entered.set()
        check()
        observe({"step": "isolated_empty_editor", "editor_empty": True, "tab_count": 1})
        if self.mode == "blocked":
            self.release.wait(5)
            check()
        if self.mode == "unexpected":
            raise RuntimeError("private document contents must not enter the result")
        if self.mode == "unexpected_value":
            raise ValueError("private document contents must not enter the result")
        if self.mode == "missing":
            return
        revalidate()
        if self.mode == "wrong":
            path.write_bytes(b"different text")
        elif self.mode == "utf16":
            path.write_bytes(text.encode("utf-16"))
        elif self.mode == "large":
            path.write_bytes(b"a" * 16004)
        else:
            path.write_bytes(text.replace("\n", "\r\n").encode("utf-8"))
        observe({"step": "save_dialog_completed", "file_present": True})


@pytest.fixture
def service(tmp_path):
    settings = SimpleNamespace(desktop_actions_enabled=True, computer_use_enabled=True)
    scopes = []

    def scoped(raw):
        target = Path(raw).resolve()
        scopes.append(target)
        if not target.is_relative_to(tmp_path):
            raise PermissionError("Path is outside the configured allowed folders")
        return target

    backend = NoteBackend()
    result = WindowsComputerService(settings, object(), scoped, backend=backend)
    return result, backend, settings, scopes


def test_verified_completion_requires_actual_exact_utf8_bytes(service, tmp_path):
    actions, backend, _, scopes = service
    path = tmp_path / "new.txt"
    text = "Generic note café.\nSecond line."
    result = actions.write_note(str(path), text)
    actual = path.read_bytes()
    assert backend.calls == 1
    assert result["verified"] is True
    assert result["sha256"] == hashlib.sha256(actual).hexdigest()
    assert result["content_sha256"] == result["expected_content_sha256"]
    assert result["content_sha256"] == hashlib.sha256(text.encode("utf-8")).hexdigest()
    assert result["bytes"] == len(actual)
    assert result["evidence"] == "notepad_ui_save_and_file_content_verified"
    assert len(scopes) >= 4  # initial permission, entry, immediate save, final verification
    assert text not in repr(result)
    assert text not in repr(actions.status())


@pytest.mark.parametrize("field", ["desktop_actions_enabled", "computer_use_enabled"])
def test_permission_disabled_never_enters_native_backend(service, tmp_path, field):
    actions, backend, settings, _ = service
    setattr(settings, field, False)
    with pytest.raises(PermissionError):
        actions.write_note(str(tmp_path / "new.txt"), "generic")
    assert backend.calls == 0


def test_missing_computer_optin_defaults_to_disabled(service, tmp_path):
    actions, backend, settings, _ = service
    del settings.computer_use_enabled
    with pytest.raises(PermissionError):
        actions.write_note(str(tmp_path / "new.txt"), "generic")
    assert backend.calls == 0


def test_existing_file_is_not_overwritten(service, tmp_path):
    actions, backend, _, _ = service
    path = tmp_path / "existing.txt"
    path.write_text("preserved user data", encoding="utf-8")
    with pytest.raises(FileExistsError):
        actions.write_note(str(path), "generic")
    assert path.read_text(encoding="utf-8") == "preserved user data"
    assert backend.calls == 0


@pytest.mark.parametrize("name", ["new.md", "new.py", "new.pdf", "new"])
def test_only_new_txt_notes_supported(service, tmp_path, name):
    actions, backend, _, _ = service
    with pytest.raises(PermissionError):
        actions.write_note(str(tmp_path / name), "generic")
    assert backend.calls == 0


def test_parent_folder_must_exist_without_implicit_creation(service, tmp_path):
    actions, backend, _, _ = service
    with pytest.raises(FileNotFoundError):
        actions.write_note(str(tmp_path / "missing" / "new.txt"), "generic")
    assert not (tmp_path / "missing").exists()
    assert backend.calls == 0


def test_path_scope_is_required(service, tmp_path):
    actions, backend, _, _ = service
    with pytest.raises(PermissionError):
        actions.write_note(str(tmp_path.parent / "outside.txt"), "generic")
    assert backend.calls == 0


@pytest.mark.parametrize("text", ["", "   ", "a" * 4001, "a\x00b", "a\x01b", "a\x7fb", None])
def test_text_bounds_and_control_characters_rejected(service, tmp_path, text):
    actions, backend, _, _ = service
    with pytest.raises(ValueError):
        actions.write_note(str(tmp_path / "new.txt"), text)
    assert backend.calls == 0


def test_crlf_input_canonicalized_without_losing_lines(service, tmp_path):
    actions, _, _, _ = service
    result = actions.write_note(str(tmp_path / "new.txt"), "first\r\nsecond\rthird\tend")
    assert result["verified"] is True
    assert result["content_sha256"] == hashlib.sha256(b"first\nsecond\nthird\tend").hexdigest()


@pytest.mark.parametrize("mode", ["wrong", "missing", "utf16", "large"])
def test_attempted_save_is_not_verified_without_matching_file(service, tmp_path, mode):
    actions, backend, _, _ = service
    backend.mode = mode
    result = actions.write_note(str(tmp_path / "new.txt"), "generic approved note")
    assert result["verified"] is False
    assert result["evidence"] == "native_note_not_verified"


@pytest.mark.parametrize(
    "mode, detail", [("unexpected", "RuntimeError"), ("unexpected_value", "ValueError")]
)
def test_native_error_messages_cannot_leak_observed_document_content(
    service, tmp_path, mode, detail
):
    actions, backend, _, _ = service
    backend.mode = mode
    result = actions.write_note(str(tmp_path / "new.txt"), "generic")
    assert result["verified"] is False
    assert result["detail"] == detail
    assert "private document contents" not in repr(result)


def test_pre_cancelled_operation_sends_no_native_input(service, tmp_path):
    actions, backend, _, _ = service
    event = threading.Event()
    event.set()
    result = actions.write_note(str(tmp_path / "new.txt"), "generic", cancel=event)
    assert result["cancelled"] is True
    assert backend.calls == 0


def _background_write(actions, path, output):
    output.append(actions.write_note(str(path), "generic"))


def test_stop_cancels_current_task_without_reviving_it_on_future_call(service, tmp_path):
    actions, backend, _, _ = service
    backend.mode = "blocked"
    output = []
    worker = threading.Thread(
        target=_background_write, args=(actions, tmp_path / "old.txt", output)
    )
    worker.start()
    assert backend.entered.wait(1)
    actions.stop()
    worker.join(1)
    assert not worker.is_alive()
    assert output[0]["cancelled"] is True
    assert actions.status()["busy"] is True
    with pytest.raises(RuntimeError):
        actions.write_note(str(tmp_path / "new.txt"), "generic")
    backend.release.set()
    deadline = time.monotonic() + 1
    while actions.status()["busy"] and time.monotonic() < deadline:
        time.sleep(0.01)
    assert not (tmp_path / "old.txt").exists()
    backend.mode = "normal"
    assert actions.write_note(str(tmp_path / "new.txt"), "generic")["verified"] is True


def test_timeout_returns_without_waiting_for_unresponsive_native_provider(service, tmp_path):
    actions, backend, _, _ = service
    actions._timeout = 0.15
    backend.mode = "blocked"
    started = time.monotonic()
    result = actions.write_note(str(tmp_path / "new.txt"), "generic")
    assert time.monotonic() - started < 1
    assert result["verified"] is False
    assert "time limit" in result["detail"]
    assert actions.status()["busy"] is True
    backend.release.set()


def test_permission_revocation_before_save_prevents_file(service, tmp_path):
    actions, backend, settings, _ = service
    backend.mode = "blocked"
    output = []
    worker = threading.Thread(
        target=_background_write, args=(actions, tmp_path / "new.txt", output)
    )
    worker.start()
    assert backend.entered.wait(1)
    settings.computer_use_enabled = False
    backend.release.set()
    worker.join(1)
    assert output[0]["verified"] is False
    assert not (tmp_path / "new.txt").exists()


def test_status_reports_narrow_capability_and_no_global_input(service):
    actions, _, _, _ = service
    status = actions.status()
    assert status["capabilities"] == ["approved_new_notepad_utf8_note"]
    assert status["arbitrary_mouse_keyboard"] is False
    assert status["last_observation"] is None


def test_secure_desktop_refused_before_any_control_binding(monkeypatch):
    backend = computer_windows._NotepadUIAutomation.__new__(computer_windows._NotepadUIAutomation)
    monkeypatch.setattr(computer_windows, "_desktop_is_unlocked", lambda: False)
    with pytest.raises(computer_windows._Unsupported, match="locked"):
        backend._wrap({"pid": 1, "hwnd": 2})


def test_elevated_or_unknown_token_refused_before_control_binding(monkeypatch):
    backend = computer_windows._NotepadUIAutomation.__new__(computer_windows._NotepadUIAutomation)
    monkeypatch.setattr(computer_windows, "_desktop_is_unlocked", lambda: True)
    monkeypatch.setattr(computer_windows, "_process_is_unelevated", lambda pid: False)
    with pytest.raises(computer_windows._Unsupported, match="Elevated"):
        backend._wrap({"pid": 1, "hwnd": 2})


def test_reused_window_handle_cannot_redirect_approved_action(monkeypatch):
    backend = computer_windows._NotepadUIAutomation.__new__(computer_windows._NotepadUIAutomation)
    monkeypatch.setattr(computer_windows, "_desktop_is_unlocked", lambda: True)
    monkeypatch.setattr(computer_windows, "_process_is_unelevated", lambda pid: True)
    wrapper = SimpleNamespace(element_info=SimpleNamespace(process_id=99))
    backend.desktop = SimpleNamespace(
        window=lambda **kwargs: SimpleNamespace(wrapper_object=lambda: wrapper)
    )
    with pytest.raises(computer_windows._Unsupported, match="identity changed"):
        backend._wrap({"pid": 1, "hwnd": 2})

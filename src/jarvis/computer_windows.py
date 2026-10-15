"""Approved, scoped Notepad note entry through native UI Automation.

This is a narrow acceptance gate, not a global keyboard/mouse API. The central
task engine must approve the exact path/text before calling ``write_note``.
Only a newly isolated, empty Notepad editor is changed. File bytes, rather than
an attempted Save command, determine completion.
"""

from __future__ import annotations

import ctypes
import hashlib
import os
import queue
import stat
import threading
import time
from ctypes import wintypes
from pathlib import Path

MAX_NOTE_CHARS = 4000
MAX_NOTE_BYTES = MAX_NOTE_CHARS * 4 + 3
ACTION_TIMEOUT = 30.0


class _Cancelled(RuntimeError):
    pass


class _Unsupported(RuntimeError):
    pass


def _note_text(text):
    if not isinstance(text, str) or not text.strip() or len(text) > MAX_NOTE_CHARS:
        raise ValueError("Use nonempty note text of at most 4000 characters")
    if any(ord(char) < 32 and char not in "\n\r\t" for char in text) or "\x7f" in text:
        raise ValueError("Note text contains unsupported control characters")
    # A single canonical representation makes native CRLF output verifiable.
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _content_hash(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _check_cancel(event, external, deadline):
    if event.is_set() or external is not None and external.is_set():
        raise _Cancelled("Computer action was cancelled")
    if time.monotonic() >= deadline:
        event.set()
        raise TimeoutError("Native note action exceeded its bounded time limit")


def _desktop_is_unlocked():
    """Read only the input-desktop identity; never cross a lock/UAC desktop."""
    user = ctypes.WinDLL("user32", use_last_error=True)
    user.OpenInputDesktop.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    user.OpenInputDesktop.restype = wintypes.HANDLE
    user.GetUserObjectInformationW.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    ]
    user.GetUserObjectInformationW.restype = wintypes.BOOL
    user.CloseDesktop.argtypes = [wintypes.HANDLE]
    user.CloseDesktop.restype = wintypes.BOOL
    handle = user.OpenInputDesktop(0, False, 1)
    if not handle:
        return False
    try:
        name = ctypes.create_unicode_buffer(256)
        needed = wintypes.DWORD()
        return bool(
            user.GetUserObjectInformationW(
                handle, 2, name, ctypes.sizeof(name), ctypes.byref(needed)
            )
            and name.value.casefold() == "default"
        )
    finally:
        user.CloseDesktop(handle)


def _process_is_unelevated(pid):
    """Unknown process-token access fails closed; no elevation is requested."""
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    advapi.OpenProcessToken.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.HANDLE),
    ]
    advapi.OpenProcessToken.restype = wintypes.BOOL
    advapi.GetTokenInformation.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    ]
    advapi.GetTokenInformation.restype = wintypes.BOOL
    process = kernel.OpenProcess(0x1000, False, pid)
    if not process:
        return False
    token = wintypes.HANDLE()
    try:
        if not advapi.OpenProcessToken(process, 8, ctypes.byref(token)):
            return False
        elevation = wintypes.DWORD()
        length = wintypes.DWORD()
        return bool(
            advapi.GetTokenInformation(
                token, 20, ctypes.byref(elevation), ctypes.sizeof(elevation), ctypes.byref(length)
            )
            and elevation.value == 0
        )
    finally:
        if token.value:
            kernel.CloseHandle(token)
        kernel.CloseHandle(process)


class WindowsComputerService:
    """One-use approved Notepad task with a single COM owner and cancellation.

    A timed-out native provider cannot justify retries into unknown UI state.
    The native worker stays busy until that provider returns; its cancellation
    event is checked before each subsequent action. ``stop`` never closes user
    windows or abandons their unsaved documents.
    """

    def __init__(self, settings, windows, scoped_path, *, backend=None, timeout=ACTION_TIMEOUT):
        self.settings = settings
        self.windows = windows
        self.scoped_path = scoped_path
        self._backend = backend
        self._timeout = max(1.0, min(float(timeout), ACTION_TIMEOUT))
        self._lock = threading.RLock()
        self._active = None
        self._requests = queue.Queue(maxsize=1)
        self._worker = None
        self.last_result = None
        self.last_observation = None

    def _path(self, raw):
        if not isinstance(raw, str) or not raw or len(raw) > 2048:
            raise ValueError("Use an absolute allowed note path")
        path = Path(self.scoped_path(raw))
        if not path.is_absolute() or path.suffix.casefold() != ".txt":
            raise PermissionError("Only a new UTF-8 .txt note in an allowed folder is supported")
        if path.exists() or path.is_symlink():
            raise FileExistsError("Existing files are never overwritten by the note action")
        if not path.parent.is_dir():
            raise FileNotFoundError("The approved note folder must already exist")
        return path

    def _observe(self, observation):
        # Backend observations contain fixed capabilities/counts, not document text,
        # unrelated window titles, passwords, screenshots, or arbitrary UI trees.
        with self._lock:
            self.last_observation = dict(observation)

    def _owner(self):
        while True:
            operation = self._requests.get()
            try:
                operation["result"] = self._run(operation)
            except Exception as error:
                # Native exception messages may contain user UI text. Keep only type.
                operation["result"] = self._failed(operation, type(error).__name__)
            finally:
                # Keep pending text only while the exact approved task needs it.
                operation["text"] = ""
                with self._lock:
                    if self._active is operation:
                        self._active = None
                operation["done"].set()

    def _failed(self, operation, reason, *, cancelled=False):
        return {
            "verified": False,
            "path": str(operation["path"]),
            "expected_content_sha256": operation["expected_hash"],
            "evidence": "native_note_cancelled" if cancelled else "native_note_not_verified",
            "detail": reason,
            "cancelled": cancelled,
            "last_observation": dict(self.last_observation) if self.last_observation else None,
        }

    def _run(self, operation):
        event, external, deadline = operation["event"], operation["external"], operation["deadline"]

        def check():
            _check_cancel(event, external, deadline)
            if not self.settings.desktop_actions_enabled or not getattr(
                self.settings, "computer_use_enabled", False
            ):
                raise PermissionError("Computer-use permission was disabled")

        def revalidate():
            check()
            current = self._path(str(operation["path"]))
            if current != operation["path"]:
                raise PermissionError("The approved note path changed")
            return current

        try:
            revalidate()
            if self._backend is None:
                self._backend = _NotepadUIAutomation(self.windows)
            self._backend.write_note(
                operation["path"], operation["text"], check, revalidate, self._observe
            )
            check()
            path = Path(self.scoped_path(str(operation["path"])))
            if path != operation["path"]:
                raise PermissionError("Saved note no longer matches the approved path")
            metadata = path.lstat()
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > MAX_NOTE_BYTES:
                raise _Unsupported("The saved note is not a bounded regular text file")
            if stat.S_ISLNK(metadata.st_mode) or getattr(metadata, "st_file_attributes", 0) & 0x400:
                raise PermissionError("Saved links and junctions are forbidden")
            with path.open("rb") as source:
                actual = source.read(MAX_NOTE_BYTES + 1)
            if len(actual) > MAX_NOTE_BYTES:
                raise _Unsupported("Saved note exceeds the verification limit")
            content = actual.decode("utf-8-sig").replace("\r\n", "\n").replace("\r", "\n")
            if content != operation["text"]:
                raise _Unsupported("Saved note content differs from the approved text")
            check()
            return {
                "verified": True,
                "path": str(path),
                "bytes": len(actual),
                "sha256": hashlib.sha256(actual).hexdigest(),
                "content_sha256": _content_hash(content),
                "expected_content_sha256": _content_hash(operation["text"]),
                "encoding": "utf-8",
                "evidence": "notepad_ui_save_and_file_content_verified",
                "detail": "A new isolated Notepad note was entered, saved and verified from file bytes",
                "last_observation": dict(self.last_observation) if self.last_observation else None,
            }
        except _Cancelled:
            return self._failed(operation, "Computer action was cancelled", cancelled=True)
        except _Unsupported as error:
            return self._failed(operation, str(error))
        except Exception as error:
            return self._failed(operation, type(error).__name__)

    def write_note(self, path: str, text: str, *, cancel=None) -> dict:
        if not self.settings.desktop_actions_enabled or not getattr(
            self.settings, "computer_use_enabled", False
        ):
            raise PermissionError("Enable approved computer use and desktop actions first")
        path = self._path(path)
        text = _note_text(text)
        operation = {
            "path": path,
            "text": text,
            "expected_hash": _content_hash(text),
            "event": threading.Event(),
            "external": cancel,
            "deadline": time.monotonic() + self._timeout,
            "done": threading.Event(),
        }
        with self._lock:
            if self._active is not None:
                raise RuntimeError("A native computer action is still stopping or running")
            self._active = operation
            self.last_observation = None
            if self._worker is None:
                self._worker = threading.Thread(target=self._owner, daemon=True, name="JARVIS-UIA")
                self._worker.start()
            self._requests.put_nowait(operation)
        while not operation["done"].wait(0.05):
            try:
                _check_cancel(operation["event"], cancel, operation["deadline"])
            except (_Cancelled, TimeoutError) as error:
                operation["event"].set()
                result = self._failed(
                    operation,
                    "Computer action was cancelled"
                    if isinstance(error, _Cancelled)
                    else str(error),
                    cancelled=isinstance(error, _Cancelled),
                )
                with self._lock:
                    self.last_result = result
                return result
        with self._lock:
            self.last_result = operation["result"]
            return dict(operation["result"])

    def status(self) -> dict:
        with self._lock:
            return {
                "available": os.name == "nt",
                "enabled": bool(getattr(self.settings, "computer_use_enabled", False)),
                "desktop_actions_enabled": bool(self.settings.desktop_actions_enabled),
                "busy": self._active is not None,
                "backend_initialized": self._backend is not None,
                "capabilities": ["approved_new_notepad_utf8_note"],
                "arbitrary_mouse_keyboard": False,
                "last_observation": dict(self.last_observation) if self.last_observation else None,
                "last_result": dict(self.last_result) if self.last_result else None,
            }

    def stop(self) -> None:
        with self._lock:
            if self._active is not None:
                self._active["event"].set()


class _NotepadUIAutomation:
    """English accessible Notepad controls; unknown layouts fail closed."""

    def __init__(self, windows):
        if os.name != "nt":
            raise _Unsupported("Notepad automation requires a local Windows desktop")
        import comtypes
        from pywinauto import Desktop

        comtypes.CoInitialize()
        self.desktop = Desktop(backend="uia")
        self.windows = windows
        self.record = windows._record("notepad")
        if self.record["id"] != "notepad":
            raise PermissionError(
                "Only the exact approved Windows Notepad application is supported"
            )
        if self.record["kind"] == "exe":
            expected = Path(os.environ.get("WINDIR", "C:/Windows")) / "System32" / "notepad.exe"
            if os.path.normcase(self.record["target"]) != os.path.normcase(str(expected)):
                raise PermissionError("Only the system Windows Notepad launcher is supported")
        else:
            from .applications import PACKAGED

            if self.record["target"] != PACKAGED["notepad"]:
                raise PermissionError("Only the fixed Windows Notepad package is supported")

    @staticmethod
    def _walk(root, check):
        pending = [(root, 0)]
        seen = 0
        while pending:
            check()
            item, depth = pending.pop(0)
            seen += 1
            if seen > 180:
                raise _Unsupported("Notepad accessibility observation exceeded its safety limit")
            yield item
            info = item.element_info
            # Save dialogs expose the user's directory tree. It is unrelated to
            # this exact path task and must not be enumerated or used as input.
            browse_content = info.control_type in {"Tree", "TreeItem", "ListItem"} or (
                info.control_type == "List" and info.automation_id != "TabListView"
            )
            if depth < 8 and not browse_content:
                pending.extend((child, depth + 1) for child in item.children())

    def _wrap(self, match):
        if not _desktop_is_unlocked():
            raise _Unsupported("Windows desktop is locked or a security desktop is active")
        if not _process_is_unelevated(match["pid"]):
            raise _Unsupported("Elevated or inaccessible Notepad windows are outside this action")
        wrapper = self.desktop.window(handle=match["hwnd"]).wrapper_object()
        if wrapper.element_info.process_id != match["pid"] or wrapper.class_name() != "Notepad":
            raise _Unsupported("Notepad window identity changed")
        return wrapper

    def _unique(
        self,
        root,
        check,
        *,
        control_type,
        names=(),
        auto_id=None,
        class_name=None,
        allow_missing=False,
    ):
        matches = []
        for item in self._walk(root, check):
            info = item.element_info
            if info.control_type != control_type or not item.is_visible() or not item.is_enabled():
                continue
            if auto_id is not None and info.automation_id != auto_id:
                continue
            if class_name is not None and info.class_name != class_name:
                continue
            if names and info.name not in names:
                continue
            if getattr(info, "is_password", False):
                continue
            matches.append(item)
        if not matches and allow_missing:
            return None
        if len(matches) != 1:
            raise _Unsupported("The required Notepad control is missing or ambiguous")
        return matches[0]

    @staticmethod
    def _wait(find, check, duration=5.0):
        deadline = time.monotonic() + duration
        while True:
            check()
            found = find()
            if found is not None:
                return found
            if time.monotonic() >= deadline:
                raise _Unsupported("Expected Notepad state did not appear within the timeout")
            time.sleep(0.08)

    def _fresh_window(self, check, observe):
        before = self.windows.backend.windows(self.record)
        if not before:
            check()
            self.windows.launch("notepad", prefer_focus=False, new_window=True)
            self._wait(lambda: self.windows.backend.windows(self.record) or None, check)
            # Modern Notepad can restore saved/unsaved user tabs on startup.
            # Create an explicit additional new window before reading any editor.
            before = self.windows.backend.windows(self.record)
        old = {match["hwnd"] for match in before}
        if before:
            usable = []
            for candidate in before:
                wrapper = self._wrap(candidate)
                modal = any(
                    item.element_info.control_type == "Window" and item.is_visible()
                    for item in wrapper.children()
                )
                if not modal:
                    usable.append((candidate, wrapper))
            if not usable:
                raise _Unsupported("A Notepad dialog blocks isolated note creation")
            _, root = usable[0]
            file_menu = self._unique(root, check, control_type="MenuItem", auto_id="File")
            check()
            file_menu.invoke()
            # XAML menus are part of the observed target window, never arbitrary
            # desktop controls. Do not fall back to guessed coordinates/shortcuts.
            new_window = self._wait(
                lambda: self._unique(
                    root,
                    check,
                    control_type="MenuItem",
                    names=("New window", "New Window"),
                    allow_missing=True,
                ),
                check,
            )
            check()
            new_window.invoke()

        def newly_visible():
            current = self.windows.backend.windows(self.record)
            fresh = [match for match in current if match["hwnd"] not in old]
            if len(fresh) > 1:
                raise _Unsupported("Several new Notepad windows appeared")
            return fresh[0] if fresh else None

        match = self._wait(newly_visible, check)
        root = self._wrap(match)
        observe(
            {
                "step": "new_window_verified",
                "pid": match["pid"],
                "hwnd": match["hwnd"],
                "existing_windows": len(before),
            }
        )
        # Startup may restore old tabs even when no Notepad was running. A
        # restored nonempty editor is never cleared or reused.
        editor = self._wait(
            lambda: self._unique(
                root, check, control_type="Document", class_name="RichEditD2DPT", allow_missing=True
            ),
            check,
        )
        if editor.iface_text.DocumentRange.GetText(MAX_NOTE_CHARS + 1):
            raise _Unsupported("Notepad restored a document; refusing to change its contents")
        tabs = [
            item
            for item in self._walk(root, check)
            if item.element_info.control_type == "TabItem" and item.is_visible()
        ]
        if len(tabs) > 1:
            raise _Unsupported("The new Notepad window contains existing tabs")
        observe(
            {
                "step": "isolated_empty_editor",
                "pid": match["pid"],
                "hwnd": match["hwnd"],
                "tab_count": len(tabs),
                "editor_empty": True,
            }
        )
        return root, editor, match

    def write_note(self, path, text, check, revalidate, observe):
        original_check = check

        def check():
            original_check()
            if not _desktop_is_unlocked():
                raise _Unsupported("Windows desktop is locked or a security desktop is active")
            current = self.windows._record("notepad")
            if any(current[key] != self.record[key] for key in ("id", "target", "kind")):
                raise PermissionError("The approved Notepad application identity changed")

        root, editor, match = self._fresh_window(check, observe)
        check()
        editor.set_focus()
        if not editor.has_keyboard_focus():
            raise _Unsupported("Notepad editor focus could not be verified")
        check()
        # UIA ValuePattern enters literal text into the exact scoped editor. It
        # does not interpret note text as keyboard commands or use the clipboard.
        editor.iface_value.SetValue(text.replace("\n", "\r\n"))
        check()
        observed = editor.iface_text.DocumentRange.GetText(MAX_NOTE_CHARS + 1)
        observed = observed.replace("\r\n", "\n").replace("\r", "\n")
        if observed != text:
            raise _Unsupported("The new Notepad editor did not contain the approved text")
        observe(
            {
                "step": "editor_content_verified",
                "pid": match["pid"],
                "hwnd": match["hwnd"],
                "characters": len(text),
                "content_sha256": _content_hash(text),
            }
        )
        revalidate()
        file_menu = self._unique(root, check, control_type="MenuItem", auto_id="File")
        check()
        file_menu.invoke()
        menu_save = self._wait(
            lambda: self._unique(
                root, check, control_type="MenuItem", names=("Save",), allow_missing=True
            ),
            check,
        )
        check()
        menu_save.invoke()

        def save_dialog():
            candidates = [
                item
                for item in root.children()
                if item.element_info.control_type == "Window"
                and item.class_name() == "#32770"
                and item.is_visible()
            ]
            if len(candidates) > 1:
                raise _Unsupported("Several save dialogs are visible")
            return candidates[0] if candidates else None

        dialog = self._wait(save_dialog, check)
        filename = self._unique(dialog, check, control_type="Edit", auto_id="1001")
        save = self._unique(
            dialog, check, control_type="Button", auto_id="1", names=("Save", "&Save")
        )
        check()
        filename.set_edit_text(str(path))
        if filename.get_value() != str(path):
            raise _Unsupported("Save dialog did not retain the approved note path")
        observe(
            {
                "step": "save_dialog_target_verified",
                "pid": match["pid"],
                "hwnd": match["hwnd"],
                "path_verified": True,
            }
        )
        revalidate()
        check()
        save.invoke()

        def saved_without_confirmation():
            check()
            # A file appearing alone cannot prove Save: another process could
            # have created it and triggered Notepad's overwrite confirmation.
            modal = any(
                item.element_info.control_type == "Window" and item.is_visible()
                for item in root.children()
            )
            return True if path.is_file() and not modal else None

        self._wait(saved_without_confirmation, check)
        observe(
            {
                "step": "save_dialog_completed",
                "pid": match["pid"],
                "hwnd": match["hwnd"],
                "file_present": True,
            }
        )

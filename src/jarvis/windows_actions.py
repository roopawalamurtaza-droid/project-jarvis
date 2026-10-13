"""Narrow native Windows launch, focus and HTTPS activation with measured evidence."""

from __future__ import annotations

import ctypes
import ipaddress
import os
import subprocess
import threading
import time
from ctypes import wintypes
from urllib.parse import unquote, urlsplit

from .applications import _GUID, PACKAGED, _com_method, validate_executable


def validate_https_url(url):
    if not isinstance(url, str) or not url or len(url) > 8192:
        raise ValueError("Use a nonempty HTTPS URL of at most 8192 characters")
    if any(char.isspace() or ord(char) < 32 or ord(char) == 127 for char in url) or "\\" in url:
        raise ValueError("URL contains ambiguous whitespace or separators")
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise ValueError("Only HTTPS websites without embedded credentials are permitted")
    try:
        port = parsed.port
        host = parsed.hostname.encode("idna").decode("ascii").casefold()
    except (ValueError, UnicodeError):
        raise ValueError("Website address is invalid") from None
    if (
        port not in {None, 443}
        or "%" in parsed.netloc
        or any(char in unquote(parsed.netloc) for char in "/\\@")
    ):
        raise ValueError("Only ordinary HTTPS website addresses are permitted")
    if host in {"localhost", "localhost.localdomain"} or host.endswith(
        (".localhost", ".local", ".internal")
    ):
        raise PermissionError(
            "Local and internal website addresses are outside this browser action"
        )
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        if "." not in host or not all(
            part
            and len(part) <= 63
            and part[0] != "-"
            and part[-1] != "-"
            and all(char.isascii() and (char.isalnum() or char == "-") for char in part)
            for part in host.split(".")
        ):
            raise ValueError("Use a complete valid website hostname")
    else:
        if not address.is_global:
            raise PermissionError(
                "Private and reserved IP addresses are outside this browser action"
            )
    # Percent encoded control characters remain unsafe even if urlsplit accepts them.
    if any(ord(char) < 32 or ord(char) == 127 for char in unquote(url)):
        raise ValueError("URL contains encoded control characters")
    return url


class _NativeWindowsBackend:
    def __init__(self):
        if os.name != "nt":
            raise RuntimeError("Windows actions require a local Windows desktop session")
        self.user = ctypes.WinDLL("user32", use_last_error=True)
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.user.IsWindowVisible.argtypes = [wintypes.HWND]
        self.user.IsWindowVisible.restype = wintypes.BOOL
        self.user.GetWindowThreadProcessId.argtypes = [
            wintypes.HWND,
            ctypes.POINTER(wintypes.DWORD),
        ]
        self.user.GetWindowThreadProcessId.restype = wintypes.DWORD
        self.user.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
        self.user.GetWindow.restype = wintypes.HWND
        self.user.IsIconic.argtypes = [wintypes.HWND]
        self.user.IsIconic.restype = wintypes.BOOL
        self.user.ShowWindowAsync.argtypes = [wintypes.HWND, ctypes.c_int]
        self.user.ShowWindowAsync.restype = wintypes.BOOL
        self.user.SetForegroundWindow.argtypes = [wintypes.HWND]
        self.user.SetForegroundWindow.restype = wintypes.BOOL
        self.user.GetForegroundWindow.restype = wintypes.HWND
        self.kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        self.kernel.OpenProcess.restype = wintypes.HANDLE
        self.kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        self.kernel.CloseHandle.restype = wintypes.BOOL
        self.kernel.QueryFullProcessImageNameW.argtypes = [
            wintypes.HANDLE,
            wintypes.DWORD,
            wintypes.LPWSTR,
            ctypes.POINTER(wintypes.DWORD),
        ]
        self.kernel.QueryFullProcessImageNameW.restype = wintypes.BOOL
        self.kernel.GetApplicationUserModelId.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(wintypes.UINT),
            wintypes.LPWSTR,
        ]
        self.kernel.GetApplicationUserModelId.restype = ctypes.c_long
        self.kernel.GetProcessId.argtypes = [wintypes.HANDLE]
        self.kernel.GetProcessId.restype = wintypes.DWORD

    def windows(self, record):
        matches = []
        cache = {}
        scanned = 0
        callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        def callback(hwnd, unused):
            nonlocal scanned
            scanned += 1
            if scanned > 4096:
                return False
            if not self.user.IsWindowVisible(hwnd) or self.user.GetWindow(hwnd, 4):
                return True
            pid = wintypes.DWORD()
            self.user.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if not pid.value:
                return True
            if pid.value not in cache:
                cache[pid.value] = self._process_identity(pid.value)
            image, aumid = cache[pid.value]
            packaged_id = (
                record["target"]
                if record["kind"] == "packaged"
                else PACKAGED.get(record["id"])
                if record["source"] == "known_location"
                else None
            )
            exact_image = (
                record["kind"] == "exe"
                and image
                and os.path.normcase(image) == os.path.normcase(record["target"])
            )
            if exact_image or packaged_id and aumid == packaged_id:
                matches.append({"hwnd": int(hwnd), "pid": pid.value})
            return True

        callback_reference = callback_type(callback)
        self.user.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
        self.user.EnumWindows.restype = wintypes.BOOL
        self.user.EnumWindows(callback_reference, 0)
        return matches[:100]

    def _process_identity(self, pid):
        handle = self.kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            return None, None
        try:
            buffer = ctypes.create_unicode_buffer(2049)
            length = wintypes.DWORD(len(buffer))
            image = (
                buffer.value
                if self.kernel.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(length))
                else None
            )
            aumid_buffer = ctypes.create_unicode_buffer(161)
            aumid_length = wintypes.UINT(len(aumid_buffer))
            aumid = (
                aumid_buffer.value
                if self.kernel.GetApplicationUserModelId(
                    handle, ctypes.byref(aumid_length), aumid_buffer
                )
                == 0
                else None
            )
            return image, aumid
        finally:
            self.kernel.CloseHandle(handle)

    def focus(self, hwnd):
        if not self.user.IsWindowVisible(hwnd):
            return False
        if self.user.IsIconic(hwnd):
            self.user.ShowWindowAsync(hwnd, 9)
        accepted = bool(self.user.SetForegroundWindow(hwnd))
        return accepted and self.user.GetForegroundWindow() == hwnd

    def spawn(self, argv):
        return subprocess.Popen(
            argv,
            shell=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    def activate(self, aumid):
        if aumid not in PACKAGED.values():
            raise PermissionError("Only fixed known packaged applications may be activated")
        ole = ctypes.WinDLL("ole32", use_last_error=True)
        ole.CoInitializeEx.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        ole.CoInitializeEx.restype = ctypes.c_long
        initialized = ole.CoInitializeEx(None, 2)
        pointer = ctypes.c_void_p()
        try:
            clsid = _GUID.parse("45BA127D-10A8-46EA-8AB7-56EA9078943C")
            iid = _GUID.parse("2e941141-7f97-4756-ba1d-9decde894a3d")
            ole.CoCreateInstance.argtypes = [
                ctypes.POINTER(_GUID),
                ctypes.c_void_p,
                ctypes.c_uint32,
                ctypes.POINTER(_GUID),
                ctypes.POINTER(ctypes.c_void_p),
            ]
            ole.CoCreateInstance.restype = ctypes.c_long
            result = ole.CoCreateInstance(
                ctypes.byref(clsid), None, 5, ctypes.byref(iid), ctypes.byref(pointer)
            )
            if result < 0:
                raise OSError(
                    f"Windows packaged activation is unavailable (HRESULT 0x{result & 0xFFFFFFFF:08x})"
                )
            activate = _com_method(
                pointer,
                3,
                ctypes.c_long,
                ctypes.c_wchar_p,
                ctypes.c_wchar_p,
                ctypes.c_uint32,
                ctypes.POINTER(wintypes.DWORD),
            )
            pid = wintypes.DWORD()
            result = activate(pointer, aumid, None, 2, ctypes.byref(pid))
            if result < 0:
                raise OSError(
                    f"Windows could not activate the application (HRESULT 0x{result & 0xFFFFFFFF:08x})"
                )
            return pid.value or None
        finally:
            if pointer.value:
                _com_method(pointer, 2, ctypes.c_ulong)(pointer)
            if initialized >= 0:
                ole.CoUninitialize()

    def open_default_url(self, url):
        class ShellExecuteInfo(ctypes.Structure):
            _fields_ = [
                ("cbSize", wintypes.DWORD),
                ("fMask", wintypes.ULONG),
                ("hwnd", wintypes.HWND),
                ("lpVerb", wintypes.LPCWSTR),
                ("lpFile", wintypes.LPCWSTR),
                ("lpParameters", wintypes.LPCWSTR),
                ("lpDirectory", wintypes.LPCWSTR),
                ("nShow", ctypes.c_int),
                ("hInstApp", wintypes.HINSTANCE),
                ("lpIDList", ctypes.c_void_p),
                ("lpClass", wintypes.LPCWSTR),
                ("hkeyClass", wintypes.HKEY),
                ("dwHotKey", wintypes.DWORD),
                ("hIcon", wintypes.HANDLE),
                ("hProcess", wintypes.HANDLE),
            ]

        shell = ctypes.WinDLL("shell32", use_last_error=True)
        ole = ctypes.WinDLL("ole32", use_last_error=True)
        ole.CoInitializeEx.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        ole.CoInitializeEx.restype = ctypes.c_long
        initialized = ole.CoInitializeEx(None, 6)
        info = ShellExecuteInfo()
        info.cbSize = ctypes.sizeof(info)
        info.fMask = 0x540  # NOCLOSEPROCESS, NOASYNC, FLAG_NO_UI; never "runas".
        info.lpVerb = "open"
        info.lpFile = url
        info.nShow = 1
        try:
            shell.ShellExecuteExW.argtypes = [ctypes.POINTER(ShellExecuteInfo)]
            shell.ShellExecuteExW.restype = wintypes.BOOL
            if not shell.ShellExecuteExW(ctypes.byref(info)):
                raise ctypes.WinError(ctypes.get_last_error())
            pid = self.kernel.GetProcessId(info.hProcess) if info.hProcess else None
            return {"pid": pid or None, "evidence": "https_association_accepted"}
        finally:
            if info.hProcess:
                self.kernel.CloseHandle(info.hProcess)
            if initialized >= 0:
                ole.CoUninitialize()


class WindowsActionService:
    def __init__(self, registry, *, backend=None, verification_timeout=1.5):
        self.registry = registry
        self._backend = backend
        self._timeout = max(0, min(float(verification_timeout), 3))
        self._children = []
        self._lock = threading.RLock()
        self.last_result = None

    @property
    def backend(self):
        if self._backend is None:
            self._backend = _NativeWindowsBackend()
        return self._backend

    def _record(self, app):
        record = self.registry.resolve(app)
        if not record["enabled"]:
            raise PermissionError(
                "Application is disabled. Review and enable it in the Application Library"
            )
        if record["kind"] == "exe":
            record["target"] = str(validate_executable(record["target"]))
        elif record["target"] not in PACKAGED.values():
            raise PermissionError("Unknown packaged activation target")
        return record

    def application_path(self, app):
        record = self._record(app)
        return validate_executable(record["target"]) if record["kind"] == "exe" else None

    def _remember(self, result):
        self.last_result = dict(result)
        return result

    def _focus_record(self, record):
        windows = self.backend.windows(record)
        if not windows:
            return {
                "verified": False,
                "app": record["name"],
                "id": record["id"],
                "evidence": "no_matching_visible_window",
                "detail": "No visible window for the exact application identity could be found",
                "window_verified": False,
                "focus_verified": False,
            }
        window = windows[0]
        focused = self.backend.focus(window["hwnd"])
        return {
            "verified": focused,
            "app": record["name"],
            "id": record["id"],
            "pid": window["pid"],
            "evidence": "foreground_window_verified" if focused else "visible_window_focus_refused",
            "detail": "Existing application window focused"
            if focused
            else "A matching application window is visible, but Windows did not grant foreground focus",
            "window_verified": True,
            "focus_verified": focused,
        }

    def focus(self, app):
        with self._lock:
            return self._remember(self._focus_record(self._record(app)))

    def _window_after_launch(self, record):
        deadline = time.monotonic() + self._timeout
        while True:
            windows = self.backend.windows(record)
            if windows:
                return windows[0]
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            time.sleep(min(0.1, remaining))

    def _spawn_record(self, record, args=()):
        # The caller controls only fixed application flags or a separately validated URL.
        child = self.backend.spawn([record["target"], *args])
        time.sleep(0.15)
        code = child.poll()
        self._children = [process for process in self._children if process.poll() is None]
        if code is None:
            self._children.append(child)
        if code not in {None, 0}:
            raise OSError("Windows application launcher exited unsuccessfully")
        return child.pid, "process_running" if code is None else "launcher_accepted"

    def launch(self, app, *, prefer_focus=True, new_window=False):
        if not isinstance(prefer_focus, bool) or not isinstance(new_window, bool):
            raise ValueError("Launch flags must be true or false")
        with self._lock:
            record = self._record(app)
            if prefer_focus and not new_window:
                focused = self._focus_record(record)
                if focused["window_verified"]:
                    # A denied focus does not justify duplicating the user's application.
                    # For an open request the matching visible window is the
                    # verified outcome. Explicit focus() still requires actual
                    # foreground evidence and reports Windows refusal.
                    if not focused["focus_verified"]:
                        focused.update(
                            verified=True,
                            evidence="visible_window_verified",
                            detail="The application is already open in a matching visible window; Windows did not grant foreground focus",
                        )
                    return self._remember(focused)
            args = []
            if new_window:
                args = (
                    ["--new-window"]
                    if record["id"] in {"chrome", "edge", "vscode"}
                    else ["-new-window", "about:blank"]
                    if record["id"] == "firefox"
                    else []
                )
            if record["kind"] == "packaged":
                pid, evidence = (
                    self.backend.activate(record["target"]),
                    "packaged_activation_accepted",
                )
            else:
                pid, evidence = self._spawn_record(record, args)
            window = self._window_after_launch(record)
            result = {
                "verified": True,
                "app": record["name"],
                "id": record["id"],
                "pid": pid,
                "evidence": "visible_window_verified" if window else evidence,
                "detail": "A matching application window is visible"
                if window
                else "Windows accepted the launch; application window visibility was not verified",
                "window_verified": bool(window),
                "focus_verified": False,
                "new_window_requested": new_window,
                "new_window_verified": False,
            }
            if window:
                result["pid"] = window["pid"]
            return self._remember(result)

    def open_url(self, url, *, browser="default", new_window=False):
        url = validate_https_url(url)
        if browser not in {"default", "chrome", "edge", "firefox"} or not isinstance(
            new_window, bool
        ):
            raise ValueError(
                "Choose default, chrome, edge or firefox and a Boolean window preference"
            )
        with self._lock:
            if browser == "default":
                result = self.backend.open_default_url(url)
                result = {
                    **result,
                    "verified": True,
                    "app": "Default browser",
                    "id": "default",
                    "window_verified": False,
                    "focus_verified": False,
                    "detail": "Windows accepted the HTTPS request in the default browser; page navigation was not observed",
                    "new_window_requested": new_window,
                    "new_window_verified": False,
                }
            else:
                record = self._record(browser)
                if record["kind"] != "exe":
                    raise PermissionError("Selected browser requires a reviewed executable")
                args = (
                    (["-new-window"] if new_window else ["-new-tab"])
                    if browser == "firefox"
                    else (["--new-window"] if new_window else [])
                )
                pid, evidence = self._spawn_record(record, [*args, url])
                window = self._window_after_launch(record)
                result = {
                    "verified": True,
                    "app": record["name"],
                    "id": record["id"],
                    "pid": window["pid"] if window else pid,
                    "evidence": evidence,
                    "window_verified": bool(window),
                    "focus_verified": False,
                    "detail": "Browser launch accepted; the requested page was not observed",
                    "new_window_requested": new_window,
                    "new_window_verified": False,
                }
            result["navigation_verified"] = False
            return self._remember(result)

    def health(self):
        return {
            "available": os.name == "nt",
            "backend_initialized": self._backend is not None,
            "launch": "absolute EXE / fixed packaged identities",
            "focus": "exact visible-window identity; subject to Windows foreground restrictions",
            "navigation_observation": False,
            "last_result": dict(self.last_result) if self.last_result else None,
        }

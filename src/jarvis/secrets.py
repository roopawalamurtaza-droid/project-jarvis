"""Current-user Windows DPAPI protection; credentials never enter settings or logs."""

from __future__ import annotations

import base64
import ctypes
import json
import os
import re
import threading
from ctypes import wintypes
from pathlib import Path


class _Blob(ctypes.Structure):
    _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]


def _protect(data: bytes, decrypt: bool = False) -> bytes:
    if os.name != "nt":
        raise RuntimeError(
            "Persistent credentials require Windows DPAPI; use environment variables here"
        )
    buffer = ctypes.create_string_buffer(data)
    source = _Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    result = _Blob()
    crypt = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    method = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    method.argtypes = [
        ctypes.POINTER(_Blob),
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(_Blob),
    ]
    method.restype = wintypes.BOOL
    # CRYPTPROTECT_UI_FORBIDDEN; no machine-wide scope.
    if not method(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(result)):
        raise RuntimeError("Windows credential protection failed")
    try:
        return ctypes.string_at(result.data, result.size)
    finally:
        kernel.LocalFree(result.data)


class SecretStore:
    _ENV = {"openai": "OPENAI_API_KEY", "gemini": "GEMINI_API_KEY", "api_token": "JARVIS_API_TOKEN"}

    def __init__(self, data_dir: Path | str):
        self.path = Path(data_dir) / "secrets.dpapi.json"
        self._lock = threading.RLock()

    @staticmethod
    def _name(name: str) -> str:
        aliases = {
            "OPENAI_API_KEY": "openai",
            "GEMINI_API_KEY": "gemini",
            "JARVIS_API_TOKEN": "api_token",
        }
        name = aliases.get(name, name)
        if not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", name):
            raise ValueError("Invalid credential name")
        return name

    def _read(self) -> dict:
        return json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else {}

    def get(self, name: str) -> str | None:
        name = self._name(name)
        with self._lock:
            saved = self._read().get(name)
            if saved:
                return _protect(base64.b64decode(saved), decrypt=True).decode("utf-8")
        return os.environ.get(self._ENV.get(name, "")) or (
            os.environ.get("GOOGLE_API_KEY") if name == "gemini" else None
        )

    def set(self, name: str, value: str) -> None:
        name = self._name(name)
        if not value or len(value) > 8192:
            raise ValueError("Credential must be nonempty and under 8192 characters")
        protected = base64.b64encode(_protect(value.encode("utf-8"))).decode("ascii")
        with self._lock:
            saved = self._read()
            saved[name] = protected
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(".tmp")
            temporary.write_text(json.dumps(saved), encoding="utf-8")
            temporary.replace(self.path)

    def delete(self, name: str) -> None:
        name = self._name(name)
        with self._lock:
            saved = self._read()
            saved.pop(name, None)
            if self.path.exists():
                self.path.write_text(json.dumps(saved), encoding="utf-8")

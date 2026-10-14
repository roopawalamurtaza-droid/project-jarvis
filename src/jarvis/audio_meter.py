"""Optional Windows peak metering for this process's active playback sessions.

This reads a scalar peak value, never audio samples. It does not activate an
endpoint-wide meter, capture/loopback stream, session volume control or another
process's meter. Every accepted session must report S_OK and this exact PID.

Fixed COM ABI and identifiers follow Microsoft's Windows SDK headers:
https://github.com/microsoft/win32metadata/blob/main/generation/WinSDK/RecompiledIdlHeaders/um/audiopolicy.h
https://github.com/microsoft/win32metadata/blob/main/generation/WinSDK/RecompiledIdlHeaders/um/endpointvolume.h
https://learn.microsoft.com/en-us/windows/win32/api/audiopolicy/nf-audiopolicy-iaudiosessioncontrol2-getprocessid
"""

from __future__ import annotations

import ctypes
import math
import os
import threading
import time
import uuid

HRESULT = ctypes.c_int32
ULONG = ctypes.c_uint32
PPVOID = ctypes.POINTER(ctypes.c_void_p)
MAX_ENDPOINTS = 32
MAX_SESSIONS = 128
SCAN_BUDGET_SECONDS = 0.04


class _GUID(ctypes.Structure):
    _fields_ = [
        ("a", ctypes.c_uint32),
        ("b", ctypes.c_uint16),
        ("c", ctypes.c_uint16),
        ("d", ctypes.c_ubyte * 8),
    ]

    @classmethod
    def parse(cls, value):
        return cls.from_buffer_copy(uuid.UUID(value).bytes_le)


CLSID_ENUMERATOR = _GUID.parse("bcde0395-e52f-467c-8e3d-c4579291692e")
IID_ENUMERATOR = _GUID.parse("a95664d2-9614-4f35-a746-de8db63617e6")
IID_MANAGER = _GUID.parse("77aa99a0-1bd6-484f-8bc7-2c654c9a9b6f")
IID_CONTROL = _GUID.parse("bfb7ff88-7239-4fc9-8fa2-07c950be9c6d")
IID_METER = _GUID.parse("c02216f6-8c67-4b5b-9d00-d008e73e0064")


def _method(pointer, index, result, *arguments):
    table = ctypes.cast(pointer, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    return ctypes.WINFUNCTYPE(result, ctypes.c_void_p, *arguments)(table[index])


def _release(pointer):
    if pointer and pointer.value:
        _method(pointer, 2, ULONG)(pointer)
        pointer.value = None


def _check(result):
    if result < 0:
        raise OSError("Windows audio session information is unavailable")


def _query(pointer, interface):
    result = ctypes.c_void_p()
    code = _method(pointer, 0, HRESULT, ctypes.POINTER(_GUID), PPVOID)(
        pointer, ctypes.byref(interface), ctypes.byref(result)
    )
    _check(code)
    if not result.value:
        raise OSError("Windows audio session interface is unavailable")
    return result


class _Session:
    def __init__(self, control):
        self.control = control
        self.meter = ctypes.c_void_p()

    def process_id(self):
        process = ULONG()
        code = _method(self.control, 14, HRESULT, ctypes.POINTER(ULONG))(
            self.control, ctypes.byref(process)
        )
        return code, process.value

    def active(self):
        state = ctypes.c_int32()
        code = _method(self.control, 3, HRESULT, ctypes.POINTER(ctypes.c_int32))(
            self.control, ctypes.byref(state)
        )
        return code == 0 and state.value == 1

    def is_system(self):
        # S_FALSE means a non-system session; every other result is rejected.
        return _method(self.control, 15, HRESULT)(self.control) != 1

    def peak(self):
        if not self.meter.value:
            self.meter = _query(self.control, IID_METER)
        peak = ctypes.c_float()
        _check(
            _method(self.meter, 3, HRESULT, ctypes.POINTER(ctypes.c_float))(
                self.meter, ctypes.byref(peak)
            )
        )
        return float(peak.value)

    def close(self):
        _release(self.meter)
        _release(self.control)


class _WindowsSessions:
    """Enumerate metadata only; session.peak is called after exact-PID checks."""

    def __init__(self):
        if os.name != "nt":
            raise OSError("Per-process playback metering requires Windows")
        self.ole = ctypes.WinDLL("ole32")
        self.ole.CoInitializeEx.argtypes = [ctypes.c_void_p, ULONG]
        self.ole.CoInitializeEx.restype = HRESULT
        self.ole.CoUninitialize.argtypes = []
        self.ole.CoUninitialize.restype = None
        self.ole.CoCreateInstance.argtypes = [
            ctypes.POINTER(_GUID),
            ctypes.c_void_p,
            ULONG,
            ctypes.POINTER(_GUID),
            PPVOID,
        ]
        self.ole.CoCreateInstance.restype = HRESULT
        self.enumerator = ctypes.c_void_p()
        self._uninitialize = False
        code = self.ole.CoInitializeEx(None, 2)  # The owning GUI thread's STA.
        if code in (0, 1):
            self._uninitialize = True
        elif code != -2147417850:  # RPC_E_CHANGED_MODE: use existing apartment.
            _check(code)
        try:
            _check(
                self.ole.CoCreateInstance(
                    ctypes.byref(CLSID_ENUMERATOR),
                    None,
                    1,
                    ctypes.byref(IID_ENUMERATOR),
                    ctypes.byref(self.enumerator),
                )
            )
        except Exception:
            self.close()
            raise

    def sessions(self):
        collection = ctypes.c_void_p()
        sessions = []
        deadline = time.monotonic() + SCAN_BUDGET_SECONDS
        try:
            # eRender=0, DEVICE_STATE_ACTIVE=1. Capture devices are never queried.
            _check(
                _method(self.enumerator, 3, HRESULT, ctypes.c_int32, ULONG, PPVOID)(
                    self.enumerator, 0, 1, ctypes.byref(collection)
                )
            )
            count = ULONG()
            _check(
                _method(collection, 3, HRESULT, ctypes.POINTER(ULONG))(
                    collection, ctypes.byref(count)
                )
            )
            for index in range(min(count.value, MAX_ENDPOINTS)):
                if time.monotonic() >= deadline:
                    break
                self._endpoint_sessions(collection, index, sessions, deadline)
            return sessions
        except Exception:
            for session in sessions:
                session.close()
            raise
        finally:
            _release(collection)

    @staticmethod
    def _endpoint_sessions(collection, index, sessions, deadline):
        device, manager, enumerator = (ctypes.c_void_p() for _ in range(3))
        try:
            _check(
                _method(collection, 4, HRESULT, ULONG, PPVOID)(
                    collection, index, ctypes.byref(device)
                )
            )
            _check(
                _method(device, 3, HRESULT, ctypes.POINTER(_GUID), ULONG, ctypes.c_void_p, PPVOID)(
                    device, ctypes.byref(IID_MANAGER), 1, None, ctypes.byref(manager)
                )
            )
            _check(_method(manager, 5, HRESULT, PPVOID)(manager, ctypes.byref(enumerator)))
            count = ctypes.c_int32()
            _check(
                _method(enumerator, 3, HRESULT, ctypes.POINTER(ctypes.c_int32))(
                    enumerator, ctypes.byref(count)
                )
            )
            for index in range(min(max(count.value, 0), MAX_SESSIONS - len(sessions))):
                if time.monotonic() >= deadline:
                    break
                control = ctypes.c_void_p()
                try:
                    _check(
                        _method(enumerator, 4, HRESULT, ctypes.c_int32, PPVOID)(
                            enumerator, index, ctypes.byref(control)
                        )
                    )
                    sessions.append(_Session(_query(control, IID_CONTROL)))
                except OSError:
                    continue
                finally:
                    _release(control)
        except OSError:
            # A disconnected endpoint does not prevent inspecting another endpoint.
            pass
        finally:
            _release(enumerator)
            _release(manager)
            _release(device)

    def close(self):
        _release(self.enumerator)
        if self._uninitialize:
            self._uninitialize = False
            self.ole.CoUninitialize()


class ProcessAudioMeter:
    """Optional normalized playback peak for this exact process, on one thread."""

    def __init__(self, *, _backend=None, _clock=time.monotonic):
        self._thread = threading.get_ident()
        self._pid = os.getpid()
        self._clock = _clock
        self._backend = _backend if _backend is not None else _WindowsSessions()
        self._sessions = []
        self._next_scan = 0.0
        self._closed = False
        self.error = None

    def _belongs_here(self, session):
        code, pid = session.process_id()
        # AUDCLNT_S_NO_SINGLE_PROCESS is positive, but must not be accepted.
        return code == 0 and pid == self._pid and not session.is_system() and session.active()

    def read(self):
        if self._closed or threading.get_ident() != self._thread:
            return None
        now = self._clock()
        try:
            if now >= self._next_scan:
                self._next_scan = now + 1.0
                for session in self._sessions:
                    session.close()
                self._sessions = []
                for session in self._backend.sessions():
                    try:
                        belongs = self._belongs_here(session)
                    except Exception:
                        belongs = False
                    if belongs:
                        self._sessions.append(session)
                    else:
                        session.close()
            peaks = []
            for session in self._sessions:
                if not self._belongs_here(session):
                    continue
                value = float(session.peak())
                if math.isfinite(value) and 0 <= value <= 1:
                    peaks.append(value)
            self.error = None if peaks else "No active exact JARVIS playback session meter"
            return max(peaks) if peaks else None
        except Exception:
            self.error = "Windows per-process playback peak is unavailable"
            return None

    def close(self):
        if self._closed:
            return
        if threading.get_ident() != self._thread:
            raise RuntimeError("Audio metering must be released on its owning desktop thread")
        self._closed = True
        try:
            for session in self._sessions:
                session.close()
            self._sessions = []
        finally:
            self._backend.close()

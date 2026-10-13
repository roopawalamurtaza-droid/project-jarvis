"""Read-only Windows measurements and explicitly permitted foreground context.

Call these providers from a worker, never the GUI thread. No clipboard, pixels,
process list, command shell, or cloud transport is involved. Foreground titles
can contain sensitive information: callers must keep snapshots ephemeral unless
the user separately authorizes storage or sharing.
"""

from __future__ import annotations

import csv
import ctypes
import io
import os
import subprocess
import threading
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

GPU_QUERY_TIMEOUT_SECONDS = 2.0
GPU_OUTPUT_LIMIT = 8192
GPU_REFRESH_SECONDS = 5.0
MAX_WINDOW_TITLE = 512


def _timestamp() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


@dataclass(frozen=True, slots=True)
class GpuMetrics:
    name: str
    utilization_percent: float | None
    memory_used_bytes: int | None
    memory_total_bytes: int | None
    sampled_at: str


@dataclass(frozen=True, slots=True)
class SystemMetricsSnapshot:
    sampled_at: str
    cpu_percent: float | None = None
    memory_used_bytes: int | None = None
    memory_total_bytes: int | None = None
    memory_percent: float | None = None
    gpus: tuple[GpuMetrics, ...] = ()
    cpu_unavailable_reason: str | None = None
    memory_unavailable_reason: str | None = None
    gpu_unavailable_reason: str | None = None
    unavailable_reason: str | None = None

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class DesktopContextSnapshot:
    sampled_at: str
    available: bool
    consent_granted: bool
    window_title: str | None = None
    process_name: str | None = None
    pid: int | None = None
    unavailable_reason: str | None = None

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class AwarenessSnapshot:
    system: SystemMetricsSnapshot
    desktop: DesktopContextSnapshot

    def as_dict(self) -> dict:
        return asdict(self)


class _FileTime(ctypes.Structure):
    _fields_ = [("low", ctypes.c_uint32), ("high", ctypes.c_uint32)]

    @property
    def ticks(self) -> int:
        return int(self.low) | (int(self.high) << 32)


class _MemoryStatus(ctypes.Structure):
    _fields_ = [
        ("length", ctypes.c_uint32),
        ("load", ctypes.c_uint32),
        ("total_physical", ctypes.c_uint64),
        ("available_physical", ctypes.c_uint64),
        ("total_pagefile", ctypes.c_uint64),
        ("available_pagefile", ctypes.c_uint64),
        ("total_virtual", ctypes.c_uint64),
        ("available_virtual", ctypes.c_uint64),
        ("available_extended_virtual", ctypes.c_uint64),
    ]


def _kernel32():
    return ctypes.WinDLL("kernel32", use_last_error=True)


def _read_cpu_times() -> tuple[int, int, int]:
    kernel = _kernel32()
    kernel.GetSystemTimes.argtypes = [ctypes.POINTER(_FileTime)] * 3
    kernel.GetSystemTimes.restype = ctypes.c_int
    idle, kernel_time, user = _FileTime(), _FileTime(), _FileTime()
    if not kernel.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kernel_time), ctypes.byref(user)):
        raise OSError("Windows CPU measurement unavailable")
    return idle.ticks, kernel_time.ticks, user.ticks


def _read_memory() -> tuple[int, int]:
    kernel = _kernel32()
    kernel.GlobalMemoryStatusEx.argtypes = [ctypes.POINTER(_MemoryStatus)]
    kernel.GlobalMemoryStatusEx.restype = ctypes.c_int
    status = _MemoryStatus()
    status.length = ctypes.sizeof(status)
    if not kernel.GlobalMemoryStatusEx(ctypes.byref(status)):
        raise OSError("Windows memory measurement unavailable")
    return int(status.total_physical), int(status.available_physical)


def _nvidia_executable() -> Path | None:
    """Look only in Windows/vendor installation directories, never PATH or cwd."""
    if os.name != "nt":
        return None
    kernel = _kernel32()
    kernel.GetSystemDirectoryW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32]
    kernel.GetSystemDirectoryW.restype = ctypes.c_uint32
    system_buffer = ctypes.create_unicode_buffer(32768)
    size = kernel.GetSystemDirectoryW(system_buffer, len(system_buffer))
    candidates = []
    if 0 < size < len(system_buffer):
        candidates.append(Path(system_buffer.value) / "nvidia-smi.exe")
    shell = ctypes.WinDLL("shell32", use_last_error=True)
    shell.SHGetFolderPathW.argtypes = [
        ctypes.c_void_p,
        ctypes.c_int,
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_wchar_p,
    ]
    shell.SHGetFolderPathW.restype = ctypes.c_long
    program_buffer = ctypes.create_unicode_buffer(260)
    # CSIDL_PROGRAM_FILES: use the actual installed known folder, not an env override.
    if shell.SHGetFolderPathW(None, 0x0026, None, 0, program_buffer) == 0:
        candidates.append(
            Path(program_buffer.value) / "NVIDIA Corporation" / "NVSMI" / "nvidia-smi.exe"
        )
    for candidate in candidates:
        if candidate.is_absolute() and candidate.is_file() and not candidate.is_symlink():
            return candidate
    return None


def _bounded_gpu_output(executable: Path) -> str:
    """Query a fixed read-only NVIDIA command with both time and byte bounds."""
    command = [
        str(executable),
        "--query-gpu=name,utilization.gpu,memory.used,memory.total",
        "--format=csv,noheader,nounits",
    ]
    process = subprocess.Popen(
        command,
        shell=False,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    chunks: list[bytes] = []
    read_error: list[bool] = []

    def read_output() -> None:
        try:
            assert process.stdout is not None
            chunks.append(process.stdout.read(GPU_OUTPUT_LIMIT + 1))
        except OSError:
            read_error.append(True)

    reader = threading.Thread(target=read_output, name="jarvis-gpu-output", daemon=True)
    reader.start()
    try:
        process.wait(timeout=GPU_QUERY_TIMEOUT_SECONDS)
        reader.join(timeout=0.2)
        if reader.is_alive() or read_error:
            raise OSError("GPU output unavailable")
        output = chunks[0] if chunks else b""
        if process.returncode != 0:
            raise OSError("NVIDIA query failed")
        if len(output) > GPU_OUTPUT_LIMIT:
            raise OSError("GPU output exceeded its limit")
        return output.decode("utf-8", errors="strict")
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=1)
        reader.join(timeout=0.2)
        if process.stdout is not None and not reader.is_alive():
            process.stdout.close()


def _gpu_number(value: str, *, percentage: bool = False) -> float | None:
    if value.strip() in {"N/A", "[N/A]", "[Not Supported]"}:
        return None
    number = float(value)
    if not 0 <= number <= (100 if percentage else 2**32):
        raise ValueError("Invalid GPU measurement")
    return number


def _parse_gpu_output(output: str, sampled_at: str) -> tuple[GpuMetrics, ...]:
    rows = list(csv.reader(io.StringIO(output)))
    if not rows or len(rows) > 32:
        raise ValueError("NVIDIA query returned no valid measurements")
    measurements = []
    for row in rows:
        if len(row) != 4 or not row[0].strip() or len(row[0]) > 160:
            raise ValueError("Unexpected NVIDIA query response")
        used = _gpu_number(row[2])
        total = _gpu_number(row[3])
        if total is not None and (total <= 0 or (used is not None and used > total)):
            raise ValueError("Invalid GPU memory measurement")
        measurements.append(
            GpuMetrics(
                name=row[0].strip(),
                utilization_percent=_gpu_number(row[1], percentage=True),
                memory_used_bytes=int(used * 1024**2) if used is not None else None,
                memory_total_bytes=int(total * 1024**2) if total is not None else None,
                sampled_at=sampled_at,
            )
        )
    return tuple(measurements)


class SystemMetricsProvider:
    """Worker-side interval CPU/RAM measurements and cached read-only GPU query.

    CPU usage requires two samples; the first intentionally returns None. GPU
    results retain their own timestamp when cached. A nonblocking lock rejects
    overlapping collection instead of queuing repeated device queries.
    """

    def __init__(self):
        self._previous_cpu: tuple[int, int, int] | None = None
        self._gpu_last_query = float("-inf")
        self._gpus: tuple[GpuMetrics, ...] = ()
        self._gpu_reason: str | None = None
        self._lock = threading.Lock()

    def sample(self) -> SystemMetricsSnapshot:
        sampled_at = _timestamp()
        if os.name != "nt":
            return SystemMetricsSnapshot(
                sampled_at=sampled_at,
                unavailable_reason="System measurements are available on Windows only.",
            )
        if not self._lock.acquire(blocking=False):
            return SystemMetricsSnapshot(
                sampled_at=sampled_at, unavailable_reason="A measurement is already running."
            )
        try:
            cpu = None
            cpu_reason = "CPU measurement needs a second sample."
            try:
                current = _read_cpu_times()
                if self._previous_cpu is not None:
                    idle = current[0] - self._previous_cpu[0]
                    total = current[1] + current[2] - sum(self._previous_cpu[1:])
                    if total > 0 and 0 <= idle <= total:
                        cpu = round(100 * (total - idle) / total, 1)
                        cpu_reason = None
                    else:
                        cpu_reason = "No valid CPU sampling interval is available yet."
                self._previous_cpu = current
            except (OSError, AttributeError):
                self._previous_cpu = None
                cpu_reason = "Windows CPU measurement unavailable."
            memory_total = memory_used = memory_percent = None
            memory_reason = None
            try:
                memory_total, memory_available = _read_memory()
                if not 0 <= memory_available <= memory_total or memory_total <= 0:
                    raise OSError("Invalid memory measurement")
                memory_used = memory_total - memory_available
                memory_percent = round(100 * memory_used / memory_total, 1)
            except (OSError, AttributeError):
                memory_total = None
                memory_reason = "Windows memory measurement unavailable."
            now = time.monotonic()
            if now - self._gpu_last_query >= GPU_REFRESH_SECONDS:
                self._gpu_last_query = now
                try:
                    executable = _nvidia_executable()
                    if executable is None:
                        self._gpus = ()
                        self._gpu_reason = (
                            "NVIDIA metrics tool is not installed; GPU is unavailable."
                        )
                    else:
                        self._gpus = _parse_gpu_output(_bounded_gpu_output(executable), sampled_at)
                        self._gpu_reason = None
                except (OSError, ValueError, subprocess.SubprocessError, AttributeError):
                    self._gpus = ()
                    self._gpu_reason = "NVIDIA metrics query failed or timed out."
            return SystemMetricsSnapshot(
                sampled_at=sampled_at,
                cpu_percent=cpu,
                memory_used_bytes=memory_used,
                memory_total_bytes=memory_total,
                memory_percent=memory_percent,
                gpus=self._gpus,
                cpu_unavailable_reason=cpu_reason,
                memory_unavailable_reason=memory_reason,
                gpu_unavailable_reason=self._gpu_reason,
            )
        finally:
            self._lock.release()


def _foreground_context() -> tuple[str, str | None, int]:
    user = ctypes.WinDLL("user32", use_last_error=True)
    user.GetForegroundWindow.argtypes = []
    user.GetForegroundWindow.restype = ctypes.c_void_p
    user.GetWindowTextW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int]
    user.GetWindowTextW.restype = ctypes.c_int
    user.GetWindowThreadProcessId.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32)]
    user.GetWindowThreadProcessId.restype = ctypes.c_uint32
    window = user.GetForegroundWindow()
    if not window:
        raise OSError("No foreground window")
    title = ctypes.create_unicode_buffer(MAX_WINDOW_TITLE + 1)
    user.GetWindowTextW(window, title, len(title))
    pid = ctypes.c_uint32()
    if not user.GetWindowThreadProcessId(window, ctypes.byref(pid)) or not pid.value:
        raise OSError("No foreground process")
    kernel = _kernel32()
    kernel.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
    kernel.OpenProcess.restype = ctypes.c_void_p
    kernel.QueryFullProcessImageNameW.argtypes = [
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_wchar_p,
        ctypes.POINTER(ctypes.c_uint32),
    ]
    kernel.QueryFullProcessImageNameW.restype = ctypes.c_int
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel.CloseHandle.restype = ctypes.c_int
    handle = kernel.OpenProcess(0x1000, False, pid.value)  # PROCESS_QUERY_LIMITED_INFORMATION
    name = None
    if handle:
        try:
            image_path = ctypes.create_unicode_buffer(32768)
            image_size = ctypes.c_uint32(len(image_path))
            if kernel.QueryFullProcessImageNameW(handle, 0, image_path, ctypes.byref(image_size)):
                name = Path(image_path.value).name[:260]
        finally:
            kernel.CloseHandle(handle)
    return title.value, name, int(pid.value)


class DesktopContextProvider:
    """An ephemeral foreground window snapshot, captured only with explicit consent."""

    def capture(self, *, consent: bool = False) -> DesktopContextSnapshot:
        sampled_at = _timestamp()
        if consent is not True:
            return DesktopContextSnapshot(
                sampled_at=sampled_at,
                available=False,
                consent_granted=False,
                unavailable_reason="Desktop context is off. Enable foreground context to permit it.",
            )
        if os.name != "nt":
            return DesktopContextSnapshot(
                sampled_at=sampled_at,
                available=False,
                consent_granted=True,
                unavailable_reason="Foreground application context is available on Windows only.",
            )
        try:
            title, name, pid = _foreground_context()
            return DesktopContextSnapshot(
                sampled_at=sampled_at,
                available=True,
                consent_granted=True,
                window_title=title[:MAX_WINDOW_TITLE],
                process_name=name[:260] if name else None,
                pid=pid,
            )
        except (OSError, AttributeError):
            return DesktopContextSnapshot(
                sampled_at=sampled_at,
                available=False,
                consent_granted=True,
                unavailable_reason="Foreground application information is unavailable or restricted.",
            )


def collect_awareness(
    metrics: SystemMetricsProvider,
    context: DesktopContextProvider,
    *,
    consent: bool = False,
) -> AwarenessSnapshot:
    """Collect UI-friendly data on a worker; callers own scheduling and consent."""
    desktop = context.capture(consent=consent)
    return AwarenessSnapshot(system=metrics.sample(), desktop=desktop)

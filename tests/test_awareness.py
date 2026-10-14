"""Privacy gates, interval measurement, and bounded read-only device queries."""

import ctypes
import io
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from jarvis import awareness


@pytest.fixture
def measured_windows(monkeypatch):
    monkeypatch.setattr(awareness, "os", SimpleNamespace(name="nt"))
    clock = [10.0]
    monkeypatch.setattr(awareness.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(awareness, "_read_memory", lambda: (1000, 400))
    monkeypatch.setattr(awareness, "_read_disk", lambda: (2000, 500))
    monkeypatch.setattr(awareness, "_read_network_counters", lambda: {1: (100, 200)})
    monkeypatch.setattr(awareness, "_nvidia_executable", lambda: None)
    monkeypatch.setattr(awareness, "_read_cpu_times", lambda: (200, 400, 100))
    return clock


def test_cpu_requires_real_interval_and_memory_is_measured(measured_windows, monkeypatch):
    provider = awareness.SystemMetricsProvider()
    first = provider.sample()
    assert first.cpu_percent is None
    assert "second sample" in first.cpu_unavailable_reason
    assert first.memory_used_bytes == 600
    assert first.memory_total_bytes == 1000
    assert first.memory_percent == 60
    # Kernel time includes idle; delta idle=30, delta kernel+user=100 -> 70%.
    monkeypatch.setattr(awareness, "_read_cpu_times", lambda: (230, 470, 130))
    second = provider.sample()
    assert second.cpu_percent == 70
    assert second.cpu_unavailable_reason is None
    assert "not installed" in second.gpu_unavailable_reason
    assert second.as_dict()["memory_used_bytes"] == 600


def test_invalid_cpu_interval_is_unavailable_not_fake_zero(measured_windows):
    provider = awareness.SystemMetricsProvider()
    provider.sample()
    result = provider.sample()
    assert result.cpu_percent is None
    assert "interval" in result.cpu_unavailable_reason


def test_measurement_failures_do_not_fabricate_values(measured_windows, monkeypatch):
    def unavailable():
        raise OSError("fake native failure")

    monkeypatch.setattr(awareness, "_read_cpu_times", unavailable)
    monkeypatch.setattr(awareness, "_read_memory", unavailable)
    result = awareness.SystemMetricsProvider().sample()
    assert result.cpu_percent is None
    assert result.memory_percent is None
    assert result.memory_used_bytes is None
    assert result.memory_total_bytes is None
    assert "unavailable" in result.cpu_unavailable_reason
    assert "unavailable" in result.memory_unavailable_reason


def test_gpu_results_cache_with_actual_measurement_timestamp(measured_windows, monkeypatch):
    calls = []
    monkeypatch.setattr(awareness, "_nvidia_executable", lambda: Path("nvidia-smi.exe"))
    monkeypatch.setattr(
        awareness,
        "_bounded_gpu_output",
        lambda path: calls.append(path) or "NVIDIA RTX Test, 17, 2048, 12288\n",
    )
    provider = awareness.SystemMetricsProvider()
    first = provider.sample()
    measured_windows[0] += 4
    second = provider.sample()
    assert len(calls) == 1
    assert first.gpus == second.gpus
    assert second.gpus[0].utilization_percent == 17
    assert second.gpus[0].memory_used_bytes == 2048 * 1024**2
    assert second.gpus[0].memory_total_bytes == 12288 * 1024**2
    assert second.gpu_unavailable_reason is None
    measured_windows[0] += 1
    provider.sample()
    assert len(calls) == 2


@pytest.mark.parametrize(
    "output",
    ["", "GPU, 101, 1, 10", "GPU, -1, 1, 10", "GPU, 4, 11, 10", "GPU, 4, 0, 0", "wrong"],
)
def test_malformed_gpu_measurements_are_rejected(output):
    with pytest.raises(ValueError):
        awareness._parse_gpu_output(output, "timestamp")


def test_unsupported_gpu_fields_are_explicitly_unavailable():
    result = awareness._parse_gpu_output("GPU, [N/A], [N/A], 12000", "timestamp")[0]
    assert result.utilization_percent is None
    assert result.memory_used_bytes is None
    assert result.memory_total_bytes == 12000 * 1024**2


def test_gpu_timeout_is_reported_without_losing_ram(measured_windows, monkeypatch):
    monkeypatch.setattr(awareness, "_nvidia_executable", lambda: Path("nvidia-smi.exe"))

    def timeout(_path):
        raise subprocess.TimeoutExpired("fixed query", 2)

    monkeypatch.setattr(awareness, "_bounded_gpu_output", timeout)
    result = awareness.SystemMetricsProvider().sample()
    assert result.gpus == ()
    assert "timed out" in result.gpu_unavailable_reason
    assert result.memory_percent == 60


def test_overlapping_collection_is_rejected(measured_windows):
    provider = awareness.SystemMetricsProvider()
    provider._lock.acquire()
    try:
        result = provider.sample()
    finally:
        provider._lock.release()
    assert result.cpu_percent is None
    assert "already running" in result.unavailable_reason


@pytest.mark.parametrize("consent", [False, None, "yes", 1])
def test_no_foreground_api_is_called_without_boolean_consent(monkeypatch, consent):
    def forbidden():
        pytest.fail("Foreground API was accessed without permission")

    monkeypatch.setattr(awareness, "_foreground_context", forbidden)
    result = awareness.DesktopContextProvider().capture(consent=consent)
    assert result.consent_granted is False
    assert result.available is False
    assert result.window_title is None
    assert result.process_name is None
    assert result.pid is None


def test_foreground_consent_reads_only_bounded_title_basename_and_pid(
    measured_windows, monkeypatch
):
    monkeypatch.setattr(awareness, "_foreground_context", lambda: ("x" * 700, "y" * 400, 1234))
    result = awareness.DesktopContextProvider().capture(consent=True)
    assert result.available
    assert result.consent_granted
    assert len(result.window_title) == 512
    assert len(result.process_name) == 260
    assert result.pid == 1234
    assert "clipboard" not in result.as_dict()
    assert "screenshot" not in result.as_dict()


def test_foreground_access_failure_is_not_claimed_as_screen_awareness(
    measured_windows, monkeypatch
):
    def restricted():
        raise OSError("restricted process")

    monkeypatch.setattr(awareness, "_foreground_context", restricted)
    result = awareness.DesktopContextProvider().capture(consent=True)
    assert result.available is False
    assert result.window_title is None
    assert result.process_name is None
    assert "restricted" in result.unavailable_reason


def test_nonwindows_is_explicitly_unavailable(monkeypatch):
    monkeypatch.setattr(awareness, "os", SimpleNamespace(name="posix"))
    assert "Windows only" in awareness.SystemMetricsProvider().sample().unavailable_reason
    assert "Windows only" in (
        awareness.DesktopContextProvider().capture(consent=True).unavailable_reason
    )


class FakeQuery:
    def __init__(self, output=b"GPU, 2, 1, 10", *, timeout=False):
        self.stdout = io.BytesIO(output)
        self.returncode = None
        self.timeout = timeout
        self.killed = False
        self.wait_timeouts = []

    def wait(self, timeout):
        self.wait_timeouts.append(timeout)
        if self.timeout and not self.killed:
            raise subprocess.TimeoutExpired("fixed query", timeout)
        self.returncode = 0
        return 0

    def poll(self):
        return self.returncode

    def kill(self):
        self.killed = True


def test_gpu_query_uses_fixed_readonly_arguments_and_no_shell(monkeypatch):
    process = FakeQuery()
    calls = []

    def popen(command, **options):
        calls.append((command, options))
        return process

    monkeypatch.setattr(awareness.subprocess, "Popen", popen)
    result = awareness._bounded_gpu_output(Path("fixed-installed-nvidia-smi.exe"))
    assert result == "GPU, 2, 1, 10"
    command, options = calls[0]
    assert command == [
        "fixed-installed-nvidia-smi.exe",
        "--query-gpu=name,utilization.gpu,memory.used,memory.total",
        "--format=csv,noheader,nounits",
    ]
    assert options["shell"] is False
    assert options["stdin"] == subprocess.DEVNULL
    assert options["stderr"] == subprocess.DEVNULL
    assert process.wait_timeouts == [2.0]


def test_gpu_query_output_is_capped(monkeypatch):
    process = FakeQuery(b"x" * (awareness.GPU_OUTPUT_LIMIT + 10))
    monkeypatch.setattr(awareness.subprocess, "Popen", lambda *args, **kwargs: process)
    with pytest.raises(OSError, match="exceeded"):
        awareness._bounded_gpu_output(Path("fixed-nvidia-smi.exe"))


def test_gpu_query_timeout_stops_only_its_owned_query_process(monkeypatch):
    process = FakeQuery(timeout=True)
    monkeypatch.setattr(awareness.subprocess, "Popen", lambda *args, **kwargs: process)
    with pytest.raises(subprocess.TimeoutExpired):
        awareness._bounded_gpu_output(Path("fixed-nvidia-smi.exe"))
    assert process.killed
    assert process.wait_timeouts == [2.0, 1]


def test_collection_contract_keeps_desktop_consent_off_by_default(measured_windows):
    result = awareness.collect_awareness(
        awareness.SystemMetricsProvider(), awareness.DesktopContextProvider()
    )
    data = result.as_dict()
    assert data["system"]["memory_percent"] == 60
    assert data["desktop"]["consent_granted"] is False
    assert data["desktop"]["window_title"] is None


def test_disk_is_measured_and_temperature_is_explicitly_unavailable(measured_windows):
    result = awareness.SystemMetricsProvider().sample()
    assert result.disk_percent == 75
    assert result.disk_total_bytes == 2000
    assert result.disk_used_bytes == 1500
    assert result.disk_unavailable_reason is None
    assert result.cpu_temperature_celsius is None
    assert "no supported" in result.temperature_unavailable_reason


@pytest.mark.parametrize("measurement", [(0, 0), (100, 110), (100, -1)])
def test_disk_invalid_measurements_remain_unavailable(measured_windows, monkeypatch, measurement):
    monkeypatch.setattr(awareness, "_read_disk", lambda: measurement)
    result = awareness.SystemMetricsProvider().sample()
    assert result.disk_percent is None
    assert result.disk_used_bytes is None
    assert result.disk_total_bytes is None
    assert "unavailable" in result.disk_unavailable_reason


def test_network_is_a_real_two_sample_64bit_counter_interval(measured_windows, monkeypatch):
    monkeypatch.setattr(awareness, "_read_network_counters", lambda: {1: (2**40, 2**41)})
    provider = awareness.SystemMetricsProvider()
    first = provider.sample()
    assert first.network_bytes_per_second is None
    assert "second sample" in first.network_unavailable_reason
    measured_windows[0] += 5
    monkeypatch.setattr(
        awareness, "_read_network_counters", lambda: {1: (2**40 + 1000, 2**41 + 1500)}
    )
    second = provider.sample()
    assert second.network_bytes_per_second == 500
    assert second.network_unavailable_reason is None
    assert "interface" not in second.as_dict()
    assert "counters" not in second.as_dict()


@pytest.mark.parametrize(
    "counters,interval",
    [({1: (99, 200)}, 5), ({2: (100, 200)}, 5), ({1: (100, 200)}, 0), ({1: (100, 200)}, 61)],
)
def test_network_counter_resets_adapter_changes_and_bad_intervals_are_gaps(
    measured_windows, monkeypatch, counters, interval
):
    provider = awareness.SystemMetricsProvider()
    provider.sample()
    measured_windows[0] += interval
    monkeypatch.setattr(awareness, "_read_network_counters", lambda: counters)
    result = provider.sample()
    assert result.network_bytes_per_second is None
    assert "changed" in result.network_unavailable_reason


def test_new_metric_failures_preserve_other_measurements(measured_windows, monkeypatch):
    def unavailable():
        raise OSError("native failure")

    monkeypatch.setattr(awareness, "_read_disk", unavailable)
    monkeypatch.setattr(awareness, "_read_network_counters", unavailable)
    result = awareness.SystemMetricsProvider().sample()
    assert result.disk_percent is None
    assert result.network_bytes_per_second is None
    assert result.memory_percent == 60
    assert "unavailable" in result.network_unavailable_reason


def test_network_native_sdk_structure_layout_matches_64bit_windows():
    assert ctypes.sizeof(awareness._MibIfRow2) == 1352
    assert awareness._MibIfRow2.in_octets.offset == 1208
    assert awareness._MibIfRow2.out_octets.offset == 1280
    assert awareness._MibIfTable2.table.offset == 8


def test_native_network_query_reads_only_up_physical_counters_and_frees_table(monkeypatch):
    class Table(ctypes.Structure):
        _fields_ = [("num_entries", ctypes.c_uint32), ("table", awareness._MibIfRow2 * 4)]

    table = Table()
    table.num_entries = 4
    for index, row in enumerate(table.table):
        row.interface_luid = index + 1
        row.type = 6
        row.oper_status = 1
        row.flags = 1
        row.in_octets = 2**40 + index
        row.out_octets = 2**41 + index
    table.table[1].flags = 0  # virtual
    table.table[2].oper_status = 2  # disconnected
    table.table[3].type = 24  # loopback
    freed = []

    def get_table(pointer):
        out = ctypes.cast(pointer, ctypes.POINTER(ctypes.POINTER(awareness._MibIfTable2)))
        out[0] = ctypes.cast(ctypes.pointer(table), ctypes.POINTER(awareness._MibIfTable2))
        return 0

    def free_table(pointer):
        freed.append(pointer)

    monkeypatch.setattr(
        awareness,
        "_ip_helper",
        lambda: SimpleNamespace(GetIfTable2=get_table, FreeMibTable=free_table),
    )
    assert awareness._read_network_counters() == {1: (2**40, 2**41)}
    assert len(freed) == 1

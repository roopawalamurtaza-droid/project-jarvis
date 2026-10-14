"""Exact-process optional peak privacy, bounds and owning-thread lifecycle."""

import os
import threading

import pytest
from test_voice import qt_speech as speech_fixture

from jarvis import audio_meter, voice

qt_speech = speech_fixture


class Session:
    def __init__(self, pid=None, *, code=0, active=True, system=False, peak=0.3):
        self.pid = os.getpid() if pid is None else pid
        self.code = code
        self.running = active
        self.system = system
        self.value = peak
        self.peak_reads = 0
        self.closed = 0

    def process_id(self):
        return self.code, self.pid

    def active(self):
        return self.running

    def is_system(self):
        return self.system

    def peak(self):
        self.peak_reads += 1
        return self.value

    def close(self):
        self.closed += 1


class Backend:
    def __init__(self, sessions):
        self.records = sessions
        self.scans = 0
        self.closed = 0

    def sessions(self):
        self.scans += 1
        return list(self.records)

    def close(self):
        self.closed += 1


def test_other_process_shared_system_and_inactive_sessions_are_never_metered():
    own = Session(peak=0.42)
    blocked = [
        Session(os.getpid() + 1),
        Session(code=1),
        Session(system=True),
        Session(active=False),
    ]
    backend = Backend([own, *blocked])
    meter = audio_meter.ProcessAudioMeter(_backend=backend)
    try:
        assert meter.read() == pytest.approx(0.42)
        assert own.peak_reads == 1
        assert all(session.peak_reads == 0 and session.closed == 1 for session in blocked)
    finally:
        meter.close()
    assert own.closed == backend.closed == 1


def test_session_pid_and_active_state_are_rechecked_before_every_peak():
    own = Session()
    meter = audio_meter.ProcessAudioMeter(_backend=Backend([own]), _clock=lambda: 1)
    try:
        assert meter.read() == pytest.approx(0.3)
        own.pid = os.getpid() + 1
        assert meter.read() is None
        assert own.peak_reads == 1
        own.pid = os.getpid()
        own.code = 1  # A formerly private session may become multiprocess.
        assert meter.read() is None
        assert own.peak_reads == 1
        own.code = 0
        own.running = False
        assert meter.read() is None
        assert own.peak_reads == 1
    finally:
        meter.close()


def test_discovery_is_bounded_in_frequency_and_missing_is_not_zero():
    now = [1.0]
    backend = Backend([])
    meter = audio_meter.ProcessAudioMeter(_backend=backend, _clock=lambda: now[0])
    try:
        for _ in range(30):
            assert meter.read() is None
        assert backend.scans == 1
        now[0] += 1.01
        assert meter.read() is None
        assert backend.scans == 2
    finally:
        meter.close()


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -0.1, 1.1])
def test_invalid_peak_is_never_displayed(value):
    meter = audio_meter.ProcessAudioMeter(_backend=Backend([Session(peak=value)]))
    try:
        assert meter.read() is None
    finally:
        meter.close()


def test_multiple_own_sessions_return_actual_maximum_and_zero_remains_measured():
    sessions = [Session(peak=0.0), Session(peak=0.7)]
    meter = audio_meter.ProcessAudioMeter(_backend=Backend(sessions), _clock=lambda: 1)
    try:
        assert meter.read() == 0.7
        sessions[1].value = 0
        assert meter.read() == 0.0
        assert meter.error is None
    finally:
        meter.close()


def test_wrong_thread_never_reads_or_releases_com_references():
    backend = Backend([Session()])
    meter = audio_meter.ProcessAudioMeter(_backend=backend)
    results = []

    def other_thread():
        results.append(meter.read())
        try:
            meter.close()
        except RuntimeError as exc:
            results.append(str(exc))

    thread = threading.Thread(target=other_thread)
    thread.start()
    thread.join(timeout=2)
    assert results[0] is None and "owning desktop thread" in results[1]
    assert backend.scans == backend.closed == 0
    meter.close()
    meter.close()
    assert backend.closed == 1


def test_speech_meter_is_lazy_and_finished_on_original_speech_lifecycle(qt_speech, monkeypatch):
    records = []

    class Meter:
        def __init__(self):
            records.append("constructed")

        def read(self):
            records.append("read")
            return 0.6

        def close(self):
            records.append("closed")

    monkeypatch.setattr(audio_meter, "ProcessAudioMeter", Meter)
    speech = voice.SpeechOutput()
    assert speech.level is None and not records
    speech.speak("Measured speech.")
    assert not records
    assert speech.level == 0.6
    assert speech.level == 0.6
    speech.on_finished(lambda: records.append("finished"))
    speech.stop()
    assert records == ["constructed", "read", "read", "closed", "finished"]
    assert speech.level is None


def test_meter_failure_never_changes_playback_or_retries_at_every_frame(qt_speech, monkeypatch):
    attempted = []
    now = [10.0]

    def unavailable():
        attempted.append(True)
        raise OSError("No meter")

    monkeypatch.setattr(audio_meter, "ProcessAudioMeter", unavailable)
    monkeypatch.setattr(voice.time, "monotonic", lambda: now[0])
    speech = voice.SpeechOutput()
    speech.speak("Speech continues normally.")
    for _ in range(30):
        assert speech.level is None
    assert len(attempted) == 1
    assert speech.speaking and speech.error is None
    now[0] += 1.01
    assert speech.level is None and len(attempted) == 2
    speech.stop()
    assert not speech.speaking

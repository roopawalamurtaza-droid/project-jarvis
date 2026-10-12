"""Deterministic framing, lifecycle and stale-result checks for hands-free input."""

from __future__ import annotations

import threading
from types import SimpleNamespace

import numpy as np
import pytest

from jarvis.handsfree import (
    FRAME_SAMPLES,
    HandsFreeInput,
    SpeechSegmenter,
    is_stop_command,
    wake_command,
)
from jarvis.voice import VoiceError


def options(**changes):
    values = {
        "wake_enabled": True,
        "wake_phrase": "hey jarvis",
        "microphone_device": None,
        "input_sensitivity": 0.015,
        "vad_aggressiveness": 2,
        "speech_end_silence": 0.1,
        "maximum_utterance_seconds": 1.0,
    }
    return SimpleNamespace(**(values | changes))


class Vad:
    def __init__(self):
        self.frames = []

    def is_speech(self, pcm, rate):
        self.frames.append((pcm, rate))
        return bool(np.any(np.frombuffer(pcm, dtype="<i2")))


class Backend:
    class CallbackStop(Exception):
        pass

    def __init__(self, device_error=False):
        self.device_error = device_error
        self.streams = []

    def query_devices(self, device, kind):
        if self.device_error:
            raise RuntimeError("device disconnected")
        return {"max_input_channels": 1}

    def check_input_settings(self, **kwargs):
        self.checked = kwargs

    def InputStream(self, **kwargs):
        stream = SimpleNamespace(**kwargs, aborted=False, closed=False, started=False)

        def start():
            stream.started = True

        def abort(**kwargs):
            stream.aborted = True

        def close(**kwargs):
            stream.closed = True

        stream.start, stream.abort, stream.close = start, abort, close
        self.streams.append(stream)
        return stream


class Transcriber:
    def __init__(self, text="Hey Jarvis, open Chrome.", blocked=False):
        self.text = text
        self.prepared = False
        self.calls = []
        self.entered = threading.Event()
        self.release = threading.Event()
        if not blocked:
            self.release.set()

    def prepare(self):
        self.prepared = True

    def transcribe(self, audio):
        self.calls.append(audio)
        self.entered.set()
        assert self.release.wait(3)
        return self.text


def frame(value=0.2):
    return np.full(FRAME_SAMPLES, value, dtype=np.float32)


def feed(pipeline, backend, value, count):
    stream = backend.streams[-1]
    for _ in range(count):
        stream.callback(frame(value).reshape(-1, 1), FRAME_SAMPLES, None, None)


class Events:
    def __init__(self):
        self.items = []
        self.condition = threading.Condition()

    def __call__(self, item):
        with self.condition:
            self.items.append(item)
            self.condition.notify_all()

    def wait(self, name):
        with self.condition:
            assert self.condition.wait_for(
                lambda: any(item["event"] == name for item in self.items), timeout=3
            ), self.items
            return next(item for item in self.items if item["event"] == name)


@pytest.mark.parametrize(
    "text,command",
    [
        ("Hey Jarvis", ""),
        ("HEY, JARVIS! open Chrome.", "open Chrome."),
        (" hey jarvis what time is it?", "what time is it?"),
    ],
)
def test_exact_wake_prefix_preserves_same_utterance(text, command):
    assert wake_command(text) == command


@pytest.mark.parametrize(
    "text", ["Jarvis", "Hey Jarvison", "Please say hey Jarvis", '"hey Jarvis"', "Hello world"]
)
def test_unrelated_or_embedded_wake_is_rejected(text):
    assert wake_command(text) is None


def test_custom_phrase_and_stop_only_commands():
    assert wake_command("Hello, assistant: open VS Code", "hello assistant") == "open VS Code"
    assert is_stop_command("Jarvis, stop!")
    assert is_stop_command("Stop talking.")
    assert is_stop_command("Wait")
    assert not is_stop_command("Please explain why I should wait")
    assert not is_stop_command("Stop talking and open Chrome")


def test_vad_pcm_framing_threshold_and_endpoint():
    vad = Vad()
    segmenter = SpeechSegmenter(options(), vad)
    for index in range(50):
        assert segmenter.push(frame(0), index * 0.02) == (False, None)
    assert vad.frames == []  # RMS rejects silence without invoking native VAD.
    assert segmenter.push(frame(), 1.0) == (False, None)
    assert segmenter.push(frame(), 1.02) == (False, None)
    started, segment = segmenter.push(frame(), 1.04)
    assert started and segment is None
    for index in range(4):
        assert segmenter.push(frame(0), 1.06 + index * 0.02)[1] is None
    _, segment = segmenter.push(frame(0), 1.14)
    assert segment.reason == "silence"
    assert segment.audio.dtype == np.float32
    assert 0 < segment.audio.size <= 16000
    assert all(len(pcm) == FRAME_SAMPLES * 2 and rate == 16000 for pcm, rate in vad.frames)


def test_short_pauses_keep_a_single_utterance_and_long_speech_is_bounded():
    segmenter = SpeechSegmenter(options(maximum_utterance_seconds=0.3), Vad())
    segments = []
    for index in range(60):
        started, segment = segmenter.push(frame(), index * 0.02)
        if segment:
            segments.append(segment)
    assert len(segments) == 1
    assert segments[0].reason == "maximum_duration"
    assert segments[0].audio.size == 15 * FRAME_SAMPLES
    for index in range(5):
        segmenter.push(frame(0), 2 + index * 0.02)
    assert segmenter.push(frame(), 3)[0] is False
    segmenter.push(frame(), 3.02)
    assert segmenter.push(frame(), 3.04)[0] is True


def test_vad_rejects_malformed_nonfinite_and_out_of_range_frames():
    segmenter = SpeechSegmenter(options(), Vad())
    for bad in (np.zeros(10), np.zeros((FRAME_SAMPLES, 1)), frame(float("nan")), frame(2)):
        with pytest.raises(VoiceError):
            segmenter.push(bad)


def test_capture_primed_before_start_silence_never_transcribed_and_wake_emitted():
    backend, transcriber, events = Backend(), Transcriber(), Events()
    pipeline = HandsFreeInput(options(), transcriber, events, backend, Vad())
    assert not backend.streams and not transcriber.prepared
    try:
        pipeline.start()
        assert transcriber.prepared and pipeline.recording
        assert backend.checked["samplerate"] == 16000
        feed(pipeline, backend, 0, 20)
        feed(pipeline, backend, 0.2, 10)
        feed(pipeline, backend, 0, 6)
        wake = events.wait("wake")
        assert wake["command"] == "open Chrome."
        assert wake["timing"]["stt_seconds"] >= 0
        assert len(transcriber.calls) == 1
        assert pipeline.is_current(wake)
    finally:
        pipeline.close()
    assert backend.streams[-1].closed and backend.streams[-1].aborted


def test_generation_change_discards_inflight_transcription_and_playback_audio():
    backend, transcriber, events = Backend(), Transcriber(blocked=True), Events()
    pipeline = HandsFreeInput(options(), transcriber, events, backend, Vad())
    try:
        pipeline.start()
        feed(pipeline, backend, 0.2, 10)
        feed(pipeline, backend, 0, 6)
        assert transcriber.entered.wait(3)
        old = pipeline.generation
        pipeline.set_mode("gated")
        assert pipeline.generation > old and not pipeline.recording
        feed(pipeline, backend, 0.2, 20)
        assert pipeline._frames.empty()
        transcriber.release.set()
    finally:
        transcriber.release.set()
        pipeline.close()
    assert not any(event["event"] == "wake" for event in events.items)


def test_followup_and_restricted_headset_stop_mode():
    backend, transcriber, events = Backend(), Transcriber("What time is it?"), Events()
    pipeline = HandsFreeInput(options(), transcriber, events, backend, Vad())
    try:
        pipeline.set_mode("command")
        pipeline.start()
        feed(pipeline, backend, 0.2, 10)
        feed(pipeline, backend, 0, 6)
        assert events.wait("utterance")["text"] == "What time is it?"
        pipeline.set_mode("stop")
        transcriber.text = "Jarvis stop."
        feed(pipeline, backend, 0.2, 10)
        feed(pipeline, backend, 0, 6)
        assert events.wait("stop_command")["text"] == "Jarvis stop."
    finally:
        pipeline.close()


def test_optin_invalid_devices_and_disconnect_are_explicit_errors():
    backend, events = Backend(), Events()
    disabled = HandsFreeInput(options(wake_enabled=False), Transcriber(), events, backend, Vad())
    with pytest.raises(VoiceError, match="explicitly"):
        disabled.start()
    assert backend.streams == []
    invalid = HandsFreeInput(options(microphone_device=-1), Transcriber(), events, backend, Vad())
    with pytest.raises(VoiceError, match="valid microphone"):
        invalid.start()
    assert not invalid.running
    missing = HandsFreeInput(options(), Transcriber(), events, Backend(True), Vad())
    with pytest.raises(VoiceError, match="disconnected"):
        missing.start()
    assert not missing.running
    pipeline = HandsFreeInput(options(), Transcriber(), events, backend, Vad())
    try:
        pipeline.start()
        backend.streams[-1].finished_callback()
        assert not pipeline.running
        assert "disconnected" in pipeline.error
    finally:
        pipeline.close()


def test_muting_closes_capture_and_resume_uses_new_stream():
    backend, events = Backend(), Events()
    pipeline = HandsFreeInput(options(), Transcriber(), events, backend, Vad())
    try:
        pipeline.start()
        generation = pipeline.generation
        pipeline.stop()
        assert backend.streams[0].closed and not pipeline.recording
        assert pipeline.generation > generation
        pipeline.start()
        assert len(backend.streams) == 2 and pipeline.recording
    finally:
        pipeline.close()


def test_overflow_invalid_frame_and_status_never_transcribe_partial_audio():
    for kind in ("overflow", "shape", "status"):
        backend, transcriber, events = Backend(), Transcriber(), Events()
        pipeline = HandsFreeInput(options(), transcriber, events, backend, Vad())
        pipeline._ensure_workers = lambda: None
        pipeline.start()
        try:
            if kind == "overflow":
                for _ in range(pipeline._frames.maxsize):
                    pipeline._frames.put_nowait((pipeline.generation, "wake", frame(), 0))
                data, count, status = frame().reshape(-1, 1), FRAME_SAMPLES, None
            elif kind == "shape":
                data, count, status = np.zeros((10, 1)), 10, None
            else:
                data, count, status = frame().reshape(-1, 1), FRAME_SAMPLES, "input overflow"
            with pytest.raises(Backend.CallbackStop):
                backend.streams[-1].callback(data, count, None, status)
            assert not pipeline.running and pipeline.error
            assert pipeline._frames.empty()
            assert transcriber.calls == []
        finally:
            pipeline.close()


def test_mode_validation_and_event_consumer_exception_does_not_kill_workers():
    backend, transcriber = Backend(), Transcriber()
    pipeline = HandsFreeInput(
        options(), transcriber, lambda event: (_ for _ in ()).throw(ValueError()), backend, Vad()
    )
    try:
        with pytest.raises(VoiceError, match="mode"):
            pipeline.set_mode("invalid")
        pipeline.start()
        feed(pipeline, backend, 0.2, 10)
        feed(pipeline, backend, 0, 6)
        assert transcriber.entered.wait(3)
        assert all(worker.is_alive() for worker in pipeline._workers)
    finally:
        pipeline.close()


def test_stop_while_model_prepares_never_opens_microphone():
    backend, transcriber, events = Backend(), Transcriber(), Events()
    preparing, release = threading.Event(), threading.Event()

    def prepare():
        preparing.set()
        assert release.wait(3)

    transcriber.prepare = prepare
    pipeline = HandsFreeInput(options(), transcriber, events, backend, Vad())
    worker = threading.Thread(target=pipeline.start)
    try:
        worker.start()
        assert preparing.wait(3)
        pipeline.stop()
        release.set()
        worker.join(3)
        assert not worker.is_alive()
        assert not pipeline.running and not backend.streams
    finally:
        release.set()
        pipeline.close()


def test_mode_change_during_model_prepare_keeps_new_generation():
    backend, transcriber, events = Backend(), Transcriber(), Events()
    preparing, release = threading.Event(), threading.Event()

    def prepare():
        preparing.set()
        assert release.wait(3)

    transcriber.prepare = prepare
    pipeline = HandsFreeInput(options(), transcriber, events, backend, Vad())
    worker = threading.Thread(target=pipeline.start)
    try:
        worker.start()
        assert preparing.wait(3)
        pipeline.set_mode("gated")
        release.set()
        worker.join(3)
        ready = events.wait("ready")
        assert ready["mode"] == "gated" and pipeline.is_current(ready)
        assert pipeline.running and not pipeline.recording
    finally:
        release.set()
        pipeline.close()

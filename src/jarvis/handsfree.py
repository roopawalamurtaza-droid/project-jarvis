"""Opt-in local microphone segmentation and exact phrase wake detection.

No microphone opens at construction. PortAudio copies bounded frames; one worker
segments them and one worker performs offline transcription. The default wake
engine transcribes speech segments rather than continuously running Whisper on
silence. It trades wake latency and work on unrelated speech for a configurable
phrase without another downloaded model or an account key.
"""

from __future__ import annotations

import importlib
import math
import queue
import re
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Any, Callable

import numpy as np

from jarvis.voice import SAMPLE_RATE, VoiceError, VoiceInput

FRAME_MS = 20
FRAME_SAMPLES = SAMPLE_RATE * FRAME_MS // 1000
INPUT_QUEUE_FRAMES = 100
MODES = frozenset({"wake", "command", "gated", "stop"})
STOP_PHRASES = frozenset({"jarvis stop", "stop talking", "wait"})


def wake_command(text: str, phrase: str = "hey jarvis") -> str | None:
    """Return the command after an exact initial wake phrase, or None.

    Case and ordinary punctuation between words do not matter. A phrase inside
    another sentence, a partial word, or a quoted phrase does not activate.
    """
    words = re.findall(r"[^\W_]+", phrase.casefold())
    if not words or not isinstance(text, str):
        return None
    pattern = r"^\s*" + r"[\s,.:;!?\-]+".join(re.escape(word) for word in words)
    match = re.match(pattern + r"\b[\s,.:;!?\-]*", text, re.IGNORECASE)
    return text[match.end() :].strip() if match else None


def is_stop_command(text: str) -> bool:
    """Accept only the entire restricted interruption phrase."""
    return " ".join(re.findall(r"[^\W_]+", text.casefold())) in STOP_PHRASES


@dataclass(frozen=True)
class Segment:
    audio: np.ndarray
    reason: str
    started_at: float
    last_voice_at: float
    completed_at: float


class SpeechSegmenter:
    """Frame a stream into bounded utterances using WebRTC VAD and an RMS floor."""

    def __init__(self, settings: Any, vad: Any = None):
        self.threshold = float(settings.input_sensitivity)
        self.end_frames = max(1, math.ceil(float(settings.speech_end_silence) * 1000 / FRAME_MS))
        self.max_frames = min(
            30 * 1000 // FRAME_MS,
            max(10, int(float(settings.maximum_utterance_seconds) * 1000 / FRAME_MS)),
        )
        if vad is None:
            try:
                vad = importlib.import_module("webrtcvad").Vad(int(settings.vad_aggressiveness))
            except (ImportError, OSError) as exc:
                raise VoiceError(
                    "Hands-free speech detection is missing. Install the JARVIS voice extra."
                ) from exc
        self.vad = vad
        self.reset()

    def reset(self) -> None:
        self._pre_roll: deque[np.ndarray] = deque(maxlen=10)
        self._votes: deque[bool] = deque(maxlen=5)
        self._frames: list[np.ndarray] = []
        self._silence = 0
        self._started_at = 0.0
        self._last_voice_at = 0.0
        self._until_quiet = False

    @property
    def speaking(self) -> bool:
        return bool(self._frames)

    def push(self, frame: np.ndarray, now: float | None = None) -> tuple[bool, Segment | None]:
        """Accept exactly 20 ms mono normalized float audio; return start and end events."""
        if frame.ndim != 1 or frame.size != FRAME_SAMPLES or frame.dtype.kind != "f":
            raise VoiceError("Speech detection requires 20 ms mono floating-point frames.")
        if not np.isfinite(frame).all() or np.max(np.abs(frame)) > 1:
            raise VoiceError("The microphone returned invalid audio samples.")
        now = time.monotonic() if now is None else now
        frame = np.ascontiguousarray(frame, dtype=np.float32)
        rms = float(np.sqrt(np.mean(frame * frame)))
        pcm = (np.clip(frame, -1, 1) * 32767).astype("<i2").tobytes()
        voiced = rms >= self.threshold and self.vad.is_speech(pcm, SAMPLE_RATE)
        if self._until_quiet:
            self._silence = 0 if voiced else self._silence + 1
            if self._silence >= self.end_frames:
                self.reset()
            return False, None
        started = False
        if not self._frames:
            self._pre_roll.append(frame.copy())
            self._votes.append(bool(voiced))
            if sum(self._votes) < 3:
                return False, None
            self._frames = list(self._pre_roll)
            self._started_at = now - len(self._frames) * FRAME_MS / 1000
            self._last_voice_at = now
            self._silence = 0
            started = True
        else:
            self._frames.append(frame.copy())
        if voiced:
            self._last_voice_at = now
            self._silence = 0
        else:
            self._silence += 1
        reason = (
            "maximum_duration"
            if len(self._frames) >= self.max_frames
            else "silence"
            if self._silence >= self.end_frames
            else None
        )
        if reason is None:
            return started, None
        # Keep a short final pause for intelligibility; do not send the entire
        # configured end silence to STT. Pre-roll retains the beginning of words.
        trailing = max(0, self._silence - 10)
        kept = self._frames[: len(self._frames) - trailing] if trailing else self._frames
        segment = Segment(np.concatenate(kept), reason, self._started_at, self._last_voice_at, now)
        self.reset()
        self._until_quiet = reason == "maximum_duration"
        return started, segment


class HandsFreeInput:
    """A reversible, explicitly started hands-free pipeline without Qt objects.

    ``start`` prepares the offline model before opening the microphone and can
    take seconds; call it on a GUI worker. Event callbacks run on workers too.
    ``set_mode`` invalidates buffered audio and in-flight results. The UI must
    compare each queued event's generation with ``generation`` before using it.
    ``gated`` drops incoming samples during normal playback. ``stop`` is an
    optional headset mode that only emits exact stop phrases and has no acoustic
    echo cancellation; it must never be the default speaker playback mode.
    """

    def __init__(
        self,
        settings: Any,
        transcriber: Any = None,
        on_event: Callable[[dict], None] | None = None,
        audio_backend: Any = None,
        vad: Any = None,
    ):
        self.settings = settings
        self.transcriber = transcriber or VoiceInput(settings)
        self.on_event = on_event or (lambda event: None)
        self._backend = audio_backend
        self._vad = vad
        self._lock = threading.RLock()
        self._generation = 0
        self._start_serial = 0
        self._mode = "wake"
        self._running = False
        self._starting = False
        self._closed = False
        self._stream: Any = None
        self._error: str | None = None
        self._frames: queue.Queue = queue.Queue(maxsize=INPUT_QUEUE_FRAMES)
        self._utterances: queue.Queue = queue.Queue(maxsize=1)
        self._workers: list[threading.Thread] = []
        self.metrics = {"frames": 0, "segments": 0, "transcriptions": 0, "dropped_frames": 0}

    @property
    def generation(self) -> int:
        with self._lock:
            return self._generation

    @property
    def mode(self) -> str:
        with self._lock:
            return self._mode

    @property
    def running(self) -> bool:
        with self._lock:
            return self._running

    @property
    def recording(self) -> bool:
        with self._lock:
            return self._running and self._stream is not None and self._mode != "gated"

    @property
    def error(self) -> str | None:
        with self._lock:
            return self._error

    def is_current(self, event: dict) -> bool:
        return event.get("generation") == self.generation

    @staticmethod
    def _drain(items: queue.Queue) -> None:
        while True:
            try:
                items.get_nowait()
            except queue.Empty:
                return

    def _emit(self, name: str, generation: int, mode: str, **details: Any) -> None:
        with self._lock:
            if generation != self._generation or self._closed:
                return
        # Consumer exceptions must not strand the capture or inference worker.
        try:
            self.on_event({"event": name, "generation": generation, "mode": mode, **details})
        except Exception:
            pass

    def _ensure_workers(self) -> None:
        with self._lock:
            if self._workers:
                return
            for target, name in (
                (self._segment_loop, "JARVIS audio"),
                (self._infer_loop, "JARVIS STT"),
            ):
                worker = threading.Thread(target=target, name=name, daemon=True)
                self._workers.append(worker)
                worker.start()

    def start(self) -> None:
        """Prepare local recognition and start capture; never download a model."""
        with self._lock:
            if self._closed:
                raise VoiceError("This hands-free input has been closed.")
            if self._running or self._starting:
                raise VoiceError("Hands-free input is already running or starting.")
            if not self.settings.wake_enabled:
                raise VoiceError(
                    "Enable hands-free listening explicitly before opening the microphone."
                )
            self._starting = True
            self._running = True
            self._start_serial += 1
            start_serial = self._start_serial
            self._generation += 1
            generation, mode = self._generation, self._mode
            self._error = None
            previous_stream, self._stream = self._stream, None
        stream = None
        try:
            if previous_stream is not None:
                self._release(previous_stream)
            # Validate the VAD before opening the microphone as well.
            SpeechSegmenter(self.settings, self._vad)
            prepare = getattr(self.transcriber, "prepare", None)
            if prepare is not None:
                prepare()
            elif hasattr(self.transcriber, "_load_model"):
                self.transcriber._load_model()
            with self._lock:
                if not self._running or start_serial != self._start_serial or self._closed:
                    return
            sd = self._backend or VoiceInput._audio_backend()
            selected = self.settings.microphone_device
            if selected is not None and (
                isinstance(selected, bool) or not isinstance(selected, int) or selected < 0
            ):
                raise VoiceError("Select a valid microphone device.")
            info = sd.query_devices(selected, "input")
            if info.get("max_input_channels", 0) < 1:
                raise VoiceError("The selected device has no microphone input.")
            sd.check_input_settings(
                device=selected, channels=1, dtype="float32", samplerate=SAMPLE_RATE
            )
            stream = sd.InputStream(
                device=selected,
                samplerate=SAMPLE_RATE,
                blocksize=FRAME_SAMPLES,
                channels=1,
                dtype="float32",
                callback=lambda data, frames, timing, status: self._receive(
                    sd, data, frames, status
                ),
                finished_callback=self._stream_finished,
            )
            with self._lock:
                active = self._running and start_serial == self._start_serial and not self._closed
                if active:
                    self._stream = stream
            if not active:
                self._release(stream)
                return
            self._ensure_workers()
            stream.start()
            with self._lock:
                generation, mode = self._generation, self._mode
                active = self._running and start_serial == self._start_serial and not self._closed
            if not active:
                return
            self._emit("ready", generation, mode)
        except Exception as exc:
            if stream is not None:
                self._release(stream)
            message = (
                f"Could not start hands-free listening: {exc}. Check the selected microphone, "
                "Windows microphone permission, and local speech model setup."
            )
            with self._lock:
                if start_serial != self._start_serial:
                    return
                generation, mode = self._generation, self._mode
                self._running = False
                self._stream = None
                self._error = message
            self._emit("error", generation, mode, message=message)
            raise VoiceError(message) from exc
        finally:
            with self._lock:
                self._starting = False

    @staticmethod
    def _release(stream: Any) -> None:
        try:
            stream.abort(ignore_errors=True)
        finally:
            stream.close(ignore_errors=True)

    def set_mode(self, mode: str) -> int:
        """Drop buffered speech and invalidate inference; return the new generation."""
        if mode not in MODES:
            raise VoiceError("Unknown hands-free microphone mode.")
        with self._lock:
            if self._closed:
                return self._generation
            if mode == self._mode:
                return self._generation
            self._mode = mode
            self._generation += 1
            self._drain(self._frames)
            self._drain(self._utterances)
            return self._generation

    def stop(self) -> None:
        """Close the physical microphone and discard buffered or in-flight results."""
        with self._lock:
            self._running = False
            self._start_serial += 1
            self._generation += 1
            generation, mode = self._generation, self._mode
            stream, self._stream = self._stream, None
            self._drain(self._frames)
            self._drain(self._utterances)
        if stream is not None:
            try:
                self._release(stream)
            except Exception as exc:
                with self._lock:
                    self._error = f"Could not close the microphone: {exc}"
                self._emit("error", generation, mode, message=self._error)
        self._emit("stopped", generation, mode)

    pause = stop

    def close(self, timeout: float = 1.0) -> None:
        """Release capture and bound shutdown; native STT can finish only to be discarded."""
        self.stop()
        with self._lock:
            self._closed = True
        deadline = time.monotonic() + max(0.0, timeout)
        for worker in self._workers:
            if worker is not threading.current_thread():
                worker.join(max(0.0, deadline - time.monotonic()))

    def _fail_capture(self, message: str) -> None:
        with self._lock:
            self._running = False
            self._generation += 1
            generation, mode = self._generation, self._mode
            self._error = message
            self._drain(self._frames)
            self._drain(self._utterances)
        self._emit("error", generation, mode, message=message)

    def _stream_finished(self) -> None:
        with self._lock:
            unexpected = self._running and self._stream is not None
        if unexpected:
            self._fail_capture(
                "The microphone disconnected or stopped. Select a device and resume."
            )

    def _receive(self, sd: Any, data: Any, frames: int, status: Any) -> None:
        with self._lock:
            if not self._running:
                raise sd.CallbackStop
            generation, mode = self._generation, self._mode
        if status:
            self._fail_capture(
                f"Microphone audio was interrupted: {status}. Please resume listening."
            )
            raise sd.CallbackStop
        if mode == "gated":
            return
        if data.ndim != 2 or data.shape != (FRAME_SAMPLES, 1) or frames != FRAME_SAMPLES:
            self._fail_capture("The microphone returned an invalid frame. Please resume listening.")
            raise sd.CallbackStop
        try:
            self._frames.put_nowait((generation, mode, data[:, 0].copy(), time.monotonic()))
        except queue.Full:
            with self._lock:
                self.metrics["dropped_frames"] += 1
            # Never transcribe discontinuous speech as if it were complete.
            self._fail_capture(
                "The audio queue overflowed. Reduce system load and resume listening."
            )
            raise sd.CallbackStop

    def _segment_loop(self) -> None:
        segmenter = SpeechSegmenter(self.settings, self._vad)
        last_generation = -1
        while not self._closed:
            try:
                generation, mode, frame, captured_at = self._frames.get(timeout=0.1)
            except queue.Empty:
                continue
            with self._lock:
                if generation != self._generation or not self._running:
                    continue
                self.metrics["frames"] += 1
            if generation != last_generation:
                segmenter.reset()
                last_generation = generation
            try:
                started, segment = segmenter.push(frame, captured_at)
                if started:
                    self._emit("speech_started", generation, mode)
                if segment is not None:
                    self.metrics["segments"] += 1
                    try:
                        self._utterances.put_nowait((generation, mode, segment))
                    except queue.Full:
                        self._emit(
                            "busy",
                            generation,
                            mode,
                            message="Recognition is busy. Please wait and repeat the command.",
                        )
            except Exception as exc:
                self._fail_capture(str(exc))

    def _infer_loop(self) -> None:
        while not self._closed:
            try:
                generation, mode, segment = self._utterances.get(timeout=0.1)
            except queue.Empty:
                continue
            with self._lock:
                if generation != self._generation or not self._running:
                    continue
            self._emit("transcribing", generation, mode)
            started = time.monotonic()
            try:
                text = self.transcriber.transcribe(segment.audio).strip()
                self.metrics["transcriptions"] += 1
                completed = time.monotonic()
                if not text:
                    self._emit("empty", generation, mode)
                    continue
                timing = {
                    "audio_seconds": round(segment.audio.size / SAMPLE_RATE, 4),
                    "endpoint_seconds": round(segment.completed_at - segment.last_voice_at, 4),
                    "stt_seconds": round(completed - started, 4),
                    "voice_to_result_seconds": round(completed - segment.last_voice_at, 4),
                }
                details = {
                    "text": text,
                    "timing": timing,
                    "reason": segment.reason,
                    "last_voice_at": segment.last_voice_at,
                    "recognized_at": completed,
                }
                if mode == "wake":
                    command = wake_command(text, self.settings.wake_phrase)
                    if command is not None:
                        self._emit("wake", generation, mode, command=command, **details)
                    else:
                        self._emit("ignored", generation, mode, reason="wake_phrase_not_found")
                elif mode == "command":
                    self._emit("utterance", generation, mode, **details)
                elif mode == "stop" and is_stop_command(text):
                    self._emit("stop_command", generation, mode, **details)
            except Exception as exc:
                with self._lock:
                    if generation != self._generation:
                        continue
                    self._error = str(exc)
                self._emit("error", generation, mode, message=str(exc))

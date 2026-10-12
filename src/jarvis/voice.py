"""Explicit microphone capture, offline transcription, and Windows speech output.

Constructing these objects never records or speaks. Capture and transcription belong
on a worker thread; Qt speech output belongs on its owning GUI thread.
"""

from __future__ import annotations

import importlib
import sys
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import numpy as np

    from jarvis.config import Settings


SAMPLE_RATE = 16_000
MAX_RECORD_SECONDS = 30
MAX_AUDIO_SAMPLES = SAMPLE_RATE * MAX_RECORD_SECONDS


class VoiceError(RuntimeError):
    """A voice failure that is safe to display to the user."""


def download_speech_model(settings: Settings) -> Path:
    """Download a speech model only when invoked by explicit user setup.

    Normal recording and transcription never call this helper.
    """
    try:
        whisper = importlib.import_module("faster_whisper")
    except (ImportError, OSError) as exc:
        raise VoiceError(
            "Offline transcription support is missing. Install JARVIS with the voice extra."
        ) from exc
    try:
        model_path = Path(str(settings.speech_model))
        if not model_path.is_dir():
            cache = Path(settings.data_dir) / "speech-models"
            cache.mkdir(parents=True, exist_ok=True)
            model_path = Path(
                whisper.download_model(
                    str(settings.speech_model), local_files_only=False, cache_dir=str(cache)
                )
            )
        _check_model_files(model_path)
        return model_path
    except Exception as exc:
        raise VoiceError(f"Speech model setup failed: {exc}") from exc


def _check_model_files(model_path: Path) -> None:
    missing = [
        name
        for name in ("model.bin", "config.json", "tokenizer.json")
        if not (model_path / name).is_file()
    ]
    if missing:
        raise VoiceError(f"Incomplete local speech model (missing {', '.join(missing)}).")


@dataclass
class _Capture:
    buffer: Any
    samples: int = 0
    accepting: bool = True
    limit_reached: bool = False
    error: str | None = None
    stream: Any = None
    timer: Any = None
    lock: Any = field(default_factory=threading.Lock)


class VoiceInput:
    """Record only between explicit start and stop calls, for at most 30 seconds."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self._capture: _Capture | None = None
        self._lifecycle = threading.RLock()
        self._transcribe_lock = threading.Lock()
        self._error: str | None = None
        self._last_limit = False
        self._model: Any = None
        self._model_key: tuple[str, str, str, str] | None = None

    @property
    def error(self) -> str | None:
        with self._lifecycle:
            if self._capture is not None:
                with self._capture.lock:
                    return self._capture.error or self._error
            return self._error

    @property
    def recording(self) -> bool:
        with self._lifecycle:
            if self._capture is None:
                return False
            with self._capture.lock:
                return self._capture.accepting

    @property
    def limit_reached(self) -> bool:
        with self._lifecycle:
            if self._capture is None:
                return self._last_limit
            with self._capture.lock:
                return self._capture.limit_reached

    @staticmethod
    def _numpy() -> Any:
        try:
            return importlib.import_module("numpy")
        except ImportError as exc:
            raise VoiceError("Audio support is missing. Install the JARVIS dependencies.") from exc

    @staticmethod
    def _audio_backend() -> Any:
        try:
            return importlib.import_module("sounddevice")
        except (ImportError, OSError) as exc:
            raise VoiceError(
                "Microphone support is unavailable. Install the audio dependencies."
            ) from exc

    def devices(self) -> list[dict]:
        """List input devices without opening or recording from them."""
        try:
            devices = self._audio_backend().query_devices()
            return [
                {"id": int(device.get("index", index)), "name": str(device["name"])}
                for index, device in enumerate(devices)
                if device.get("max_input_channels", 0) > 0
            ]
        except Exception as exc:
            self._error = f"Could not list microphones: {exc}"
            raise VoiceError(self._error) from exc

    def start(self, device: int | None = None) -> None:
        """Start one user-requested mono float32 recording at 16 kHz."""
        with self._lifecycle:
            if self._capture is not None:
                raise VoiceError("A recording is already open. Stop or cancel it first.")
            selected = self.settings.microphone_device if device is None else device
            if selected is not None and (
                isinstance(selected, bool) or not isinstance(selected, int) or selected < 0
            ):
                raise VoiceError("Select a valid microphone device.")
            self._error = None
            self._last_limit = False
            capture = None
            try:
                np = self._numpy()
                sd = self._audio_backend()
                info = sd.query_devices(selected, "input")
                if info.get("max_input_channels", 0) < 1:
                    raise VoiceError("The selected device has no microphone input.")
                sd.check_input_settings(
                    device=selected, channels=1, dtype="float32", samplerate=SAMPLE_RATE
                )
                capture = _Capture(np.empty(MAX_AUDIO_SAMPLES, dtype=np.float32))
                capture.stream = sd.InputStream(
                    device=selected,
                    samplerate=SAMPLE_RATE,
                    channels=1,
                    dtype="float32",
                    callback=lambda data, frames, timing, status: self._receive(
                        capture, sd, data, frames, status
                    ),
                )
                self._capture = capture
                capture.stream.start()
                capture.timer = threading.Timer(MAX_RECORD_SECONDS, self._timeout, args=(capture,))
                capture.timer.daemon = True
                capture.timer.start()
            except Exception as exc:
                if capture is not None:
                    if capture.timer is not None:
                        capture.timer.cancel()
                    with capture.lock:
                        capture.accepting = False
                    self._close_stream(capture)
                self._capture = None
                self._error = (
                    f"Could not start the microphone: {exc}. Check Windows microphone permission "
                    "and select an input device that supports 16 kHz mono audio."
                )
                raise VoiceError(self._error) from exc

    def _receive(self, capture: _Capture, sd: Any, data: Any, frames: int, status: Any):
        """PortAudio callback: copy into fixed storage and stop at the boundary."""
        should_stop = False
        with capture.lock:
            if not capture.accepting:
                should_stop = True
            elif status:
                capture.error = f"Microphone audio was interrupted: {status}. Please try again."
                capture.accepting = False
                should_stop = True
            else:
                try:
                    if data.ndim != 2 or data.shape[1] != 1 or data.shape[0] != frames:
                        raise ValueError("expected mono audio")
                    count = min(frames, MAX_AUDIO_SAMPLES - capture.samples)
                    end = capture.samples + count
                    capture.buffer[capture.samples : end] = data[:count, 0]
                    capture.samples = end
                    if end >= MAX_AUDIO_SAMPLES:
                        capture.limit_reached = True
                        capture.accepting = False
                        should_stop = True
                except Exception:
                    capture.error = "The microphone returned invalid audio. Please try again."
                    capture.accepting = False
                    should_stop = True
        if should_stop:
            raise sd.CallbackStop

    @staticmethod
    def _close_stream(capture: _Capture) -> str | None:
        stream, capture.stream = capture.stream, None
        if stream is None:
            return None
        error = None
        try:
            stream.abort(ignore_errors=False)
        except Exception as exc:
            error = f"Could not stop microphone capture: {exc}"
        try:
            stream.close(ignore_errors=False)
        except Exception as exc:
            error = error or f"Could not close the microphone: {exc}"
        return error

    def _timeout(self, capture: _Capture) -> None:
        with self._lifecycle:
            if self._capture is not capture:
                return
            with capture.lock:
                capture.accepting = False
                capture.limit_reached = True
            error = self._close_stream(capture)
            if error:
                with capture.lock:
                    capture.error = capture.error or error
                self._error = error

    def stop(self) -> np.ndarray:
        """Release the microphone and return captured audio; never save it to disk."""
        with self._lifecycle:
            np = self._numpy()
            capture, self._capture = self._capture, None
            if capture is None:
                return np.empty(0, dtype=np.float32)
            if capture.timer is not None:
                capture.timer.cancel()
            with capture.lock:
                capture.accepting = False
                self._last_limit = capture.limit_reached
            error = self._close_stream(capture)
            with capture.lock:
                error = capture.error or error
                audio = capture.buffer[: capture.samples].copy()
                capture.buffer.fill(0)
            if error:
                self._error = error
                raise VoiceError(error)
            return audio

    def cancel(self) -> None:
        """Stop capture and discard its contents, without invoking transcription."""
        with self._lifecycle:
            capture, self._capture = self._capture, None
            if capture is None:
                return
            if capture.timer is not None:
                capture.timer.cancel()
            with capture.lock:
                capture.accepting = False
                capture.buffer.fill(0)
                capture.samples = 0
            error = self._close_stream(capture)
            if error:
                self._error = error
                raise VoiceError(error)

    def _load_model(self) -> Any:
        model_name = str(self.settings.speech_model)
        cache = str(Path(self.settings.data_dir) / "speech-models")
        key = (model_name, cache, self.settings.speech_device, self.settings.speech_compute_type)
        if self._model is not None and self._model_key == key:
            return self._model
        try:
            whisper = importlib.import_module("faster_whisper")
        except (ImportError, OSError) as exc:
            raise VoiceError(
                "Offline transcription support is missing. Install JARVIS with the voice extra."
            ) from exc
        try:
            model_path = Path(model_name)
            if not model_path.is_dir():
                model_path = Path(
                    whisper.download_model(model_name, local_files_only=True, cache_dir=cache)
                )
            # WhisperModel's tokenizer fallback can otherwise download even when
            # local_files_only=True. Require it before entering that constructor.
            _check_model_files(model_path)
            model = whisper.WhisperModel(
                str(model_path),
                device=self.settings.speech_device,
                compute_type=self.settings.speech_compute_type,
                download_root=cache,
                local_files_only=True,
            )
        except Exception as exc:
            raise VoiceError(
                f"Could not load the local speech model: {exc}. "
                "Run JARVIS setup with --download-speech-model explicitly, or choose a complete "
                "local model directory. CPU with int8 is the supported default."
            ) from exc
        self._model, self._model_key = model, key
        return model

    def transcribe(self, audio: np.ndarray) -> str:
        """Transcribe a bounded normalized mono float array using only local files."""
        np = self._numpy()
        if not isinstance(audio, np.ndarray) or audio.ndim != 1 or audio.dtype.kind != "f":
            raise VoiceError("Transcription requires a mono floating-point audio array at 16 kHz.")
        if not 0 < audio.size <= MAX_AUDIO_SAMPLES:
            raise VoiceError("Audio must contain between 1 sample and 30 seconds at 16 kHz.")
        if not np.isfinite(audio).all() or np.any(np.abs(audio) > 1):
            raise VoiceError("Audio samples must be finite and normalized between -1 and 1.")
        samples = np.ascontiguousarray(audio, dtype=np.float32)
        if np.max(np.abs(samples)) < 0.0001:
            return ""
        try:
            with self._transcribe_lock:
                model = self._load_model()
                segments, _ = model.transcribe(
                    samples,
                    beam_size=1,
                    best_of=1,
                    temperature=0,
                    condition_on_previous_text=False,
                    vad_filter=True,
                )
                text = " ".join(segment.text.strip() for segment in segments).strip()
            self._error = None
            return text
        except VoiceError as exc:
            self._error = str(exc)
            raise
        except Exception as exc:
            self._error = f"Local transcription failed: {exc}. Please try again."
            raise VoiceError(self._error) from exc


class SpeechOutput:
    """Speak through an installed Windows Qt engine, only after an explicit call."""

    def __init__(self, parent: Any = None):
        self._tts: Any = None
        self._qt: Any = None
        self._core: Any = None
        self._error: str | None = None
        self.engine = ""
        try:
            self._core = importlib.import_module("PySide6.QtCore")
            self._qt = importlib.import_module("PySide6.QtTextToSpeech")
            if self._core.QCoreApplication.instance() is None:
                raise VoiceError("Speech output requires a running desktop application.")
            if sys.platform != "win32":
                raise VoiceError("The MVP speech output supports installed Windows voices.")
            engines = self._qt.QTextToSpeech.availableEngines()
            for name in ("winrt", "sapi"):
                if name not in engines:
                    continue
                candidate = self._qt.QTextToSpeech(name, parent)
                if candidate.state() == self._qt.QTextToSpeech.State.Error:
                    self._error = candidate.errorString() or "Windows speech initialization failed."
                    candidate.deleteLater()
                    continue
                self._tts = candidate
                self.engine = name
                self._error = None
                candidate.errorOccurred.connect(self._on_error)
                break
            if self._tts is None:
                raise VoiceError(self._error or "No supported Windows speech engine is installed.")
        except Exception as exc:
            self._error = f"Speech output is unavailable: {exc}"

    def _on_error(self, reason: Any, message: str) -> None:
        self._error = message or "Windows speech output failed."

    @property
    def error(self) -> str | None:
        if self._tts is None:
            return self._error
        if self._tts.state() == self._qt.QTextToSpeech.State.Error:
            return self._tts.errorString() or self._error or "Windows speech output failed."
        if not self._tts.availableVoices():
            return "No Windows voices are available for the current system language."
        return self._error

    @property
    def available(self) -> bool:
        return self._tts is not None and self.error is None

    def _require_engine(self) -> None:
        if not self.available:
            raise VoiceError(self.error or "Speech output is unavailable.")
        if self._core.QThread.currentThread() != self._tts.thread():
            raise VoiceError("Speech output must be called from its desktop thread.")

    def voices(self) -> list[str]:
        if self._tts is None:
            return []
        return list(dict.fromkeys(voice.name() for voice in self._tts.availableVoices()))

    def set_voice(self, name: str) -> None:
        self._require_engine()
        for voice in self._tts.availableVoices():
            if voice.name() == name:
                self._tts.setVoice(voice)
                return
        raise VoiceError("That Windows voice is unavailable. Select an installed voice.")

    def speak(self, text: str) -> None:
        self._require_engine()
        if not isinstance(text, str):
            raise VoiceError("Speech output requires text.")
        if not text.strip():
            return
        if len(text) > 12_000:
            raise VoiceError("The response is too long to speak. Read it in the chat instead.")
        self._tts.say(text)
        if self._tts.state() == self._qt.QTextToSpeech.State.Error:
            raise VoiceError(self.error or "Windows speech output failed.")

    def stop(self) -> None:
        if self._tts is None:
            return
        if self._core.QThread.currentThread() != self._tts.thread():
            raise VoiceError("Speech output must be stopped from its desktop thread.")
        self._tts.stop(self._qt.QTextToSpeech.BoundaryHint.Immediate)

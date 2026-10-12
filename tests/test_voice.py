"""Voice checks use synthetic audio; they never open a microphone or speak."""

from types import SimpleNamespace

import numpy as np
import pytest

from jarvis import voice


@pytest.fixture
def settings(tmp_path):
    return SimpleNamespace(
        data_dir=tmp_path,
        microphone_device=None,
        speech_model="base.en",
        speech_device="cpu",
        speech_compute_type="int8",
    )


class FakeTimer:
    def __init__(self, seconds, target, args=()):
        self.seconds = seconds
        self.target = target
        self.args = args
        self.daemon = False
        self.started = False
        self.cancelled = False

    def start(self):
        self.started = True

    def cancel(self):
        self.cancelled = True

    def fire(self):
        self.target(*self.args)


class FakeStream:
    def __init__(self, owner, **kwargs):
        self.owner = owner
        self.kwargs = kwargs
        self.started = False
        self.aborted = False
        self.closed = False

    def start(self):
        if self.owner.start_error:
            raise RuntimeError("device is busy")
        self.started = True

    def abort(self, ignore_errors=False):
        self.aborted = True
        if self.owner.abort_error:
            raise RuntimeError("abort failed")

    def close(self, ignore_errors=False):
        self.closed = True

    def feed(self, data, status=None):
        self.kwargs["callback"](data, len(data), None, status)


class FakeAudio:
    class CallbackStop(Exception):
        pass

    def __init__(self):
        self.streams = []
        self.start_error = False
        self.abort_error = False
        self.supported = True
        self.input_channels = 1
        self.checked = None

    def query_devices(self, device=None, kind=None):
        if kind == "input":
            return {"name": "Test mic", "max_input_channels": self.input_channels}
        return [
            {"name": "Speaker", "max_input_channels": 0},
            {"name": "Test mic", "max_input_channels": 1, "index": 8},
        ]

    def check_input_settings(self, **kwargs):
        self.checked = kwargs
        if not self.supported:
            raise RuntimeError("unsupported sample rate")

    def InputStream(self, **kwargs):
        stream = FakeStream(self, **kwargs)
        self.streams.append(stream)
        return stream


@pytest.fixture
def audio_backend(monkeypatch):
    audio = FakeAudio()
    monkeypatch.setattr(voice.VoiceInput, "_audio_backend", staticmethod(lambda: audio))
    monkeypatch.setattr(voice.threading, "Timer", FakeTimer)
    return audio


def test_constructor_does_not_import_audio_or_whisper(settings, monkeypatch):
    def unexpected_import(name):
        pytest.fail(f"Voice construction imported {name}")

    monkeypatch.setattr(voice.importlib, "import_module", unexpected_import)
    source = voice.VoiceInput(settings)
    assert source.recording is False
    assert source.error is None


def test_device_list_does_not_open_microphone(settings, audio_backend):
    source = voice.VoiceInput(settings)
    assert source.devices() == [{"id": 8, "name": "Test mic"}]
    assert audio_backend.streams == []


def test_recording_returns_mono_float32_and_releases_device(settings, audio_backend):
    settings.microphone_device = 8
    source = voice.VoiceInput(settings)
    source.start()
    stream = audio_backend.streams[-1]
    assert source.recording is True
    assert stream.kwargs["device"] == 8
    assert stream.kwargs["samplerate"] == 16_000
    assert stream.kwargs["channels"] == 1
    assert stream.kwargs["dtype"] == "float32"
    stream.feed(np.array([[0.25], [-0.5]], dtype=np.float32))
    captured = source.stop()
    np.testing.assert_array_equal(captured, np.array([0.25, -0.5], dtype=np.float32))
    assert captured.dtype == np.float32
    assert source.recording is False
    assert stream.aborted and stream.closed
    assert source.stop().size == 0


def test_recording_never_exceeds_thirty_seconds(settings, audio_backend):
    source = voice.VoiceInput(settings)
    source.start(device=8)
    stream = audio_backend.streams[-1]
    data = np.full((voice.MAX_AUDIO_SAMPLES + 20, 1), 0.25, dtype=np.float32)
    with pytest.raises(audio_backend.CallbackStop):
        stream.feed(data)
    assert source.recording is False
    assert source.limit_reached is True
    audio = source.stop()
    assert audio.size == 30 * 16_000
    assert source.limit_reached is True
    assert stream.closed


def test_wall_timeout_closes_device_even_without_new_audio(settings, audio_backend):
    source = voice.VoiceInput(settings)
    source.start()
    stream = audio_backend.streams[-1]
    stream.feed(np.full((3, 1), 0.2, dtype=np.float32))
    timer = source._capture.timer
    assert timer.seconds == 30 and timer.started and timer.daemon
    timer.fire()
    assert not source.recording and source.limit_reached
    assert stream.closed and stream.aborted
    assert source.stop().size == 3


def test_cancel_discards_audio_and_stale_callback(settings, audio_backend):
    source = voice.VoiceInput(settings)
    source.start()
    old_stream = audio_backend.streams[-1]
    old_stream.feed(np.full((4, 1), 0.2, dtype=np.float32))
    old_capture = source._capture
    source.cancel()
    assert source.stop().size == 0
    assert old_stream.closed and old_capture.timer.cancelled
    assert not old_capture.buffer.any()
    source.start()
    with pytest.raises(audio_backend.CallbackStop):
        old_stream.feed(np.full((4, 1), 0.5, dtype=np.float32))
    assert source.stop().size == 0


def test_second_recording_is_rejected(settings, audio_backend):
    source = voice.VoiceInput(settings)
    source.start()
    with pytest.raises(voice.VoiceError, match="already open"):
        source.start()
    source.cancel()


@pytest.mark.parametrize("device", [-1, True, "Microphone"])
def test_invalid_device_cannot_start(settings, audio_backend, device):
    with pytest.raises(voice.VoiceError, match="valid microphone"):
        voice.VoiceInput(settings).start(device)
    assert audio_backend.streams == []


def test_unsupported_input_reports_error_before_opening(settings, audio_backend):
    audio_backend.supported = False
    source = voice.VoiceInput(settings)
    with pytest.raises(voice.VoiceError, match="16 kHz"):
        source.start()
    assert not source.recording
    assert "unsupported sample rate" in source.error
    assert audio_backend.streams == []


def test_failed_start_still_closes_microphone(settings, audio_backend):
    audio_backend.start_error = True
    source = voice.VoiceInput(settings)
    with pytest.raises(voice.VoiceError, match="device is busy"):
        source.start()
    assert not source.recording
    assert audio_backend.streams[-1].closed


def test_audio_overflow_is_visible_and_prevents_partial_transcription(settings, audio_backend):
    source = voice.VoiceInput(settings)
    source.start()
    stream = audio_backend.streams[-1]
    with pytest.raises(audio_backend.CallbackStop):
        stream.feed(np.full((4, 1), 0.2, dtype=np.float32), status="input overflow")
    assert "input overflow" in source.error
    with pytest.raises(voice.VoiceError, match="interrupted"):
        source.stop()
    assert stream.closed


def test_stop_error_still_attempts_close(settings, audio_backend):
    audio_backend.abort_error = True
    source = voice.VoiceInput(settings)
    source.start()
    with pytest.raises(voice.VoiceError, match="abort failed"):
        source.stop()
    assert audio_backend.streams[-1].closed
    assert not source.recording


@pytest.mark.parametrize(
    "audio",
    [
        "audio.wav",
        [0.1],
        np.empty(0, dtype=np.float32),
        np.ones((2, 1), dtype=np.float32),
        np.ones(4, dtype=np.int16),
        np.array([float("nan")], dtype=np.float32),
        np.array([float("inf")], dtype=np.float32),
        np.array([1.1], dtype=np.float32),
        np.ones(voice.MAX_AUDIO_SAMPLES + 1, dtype=np.float32),
    ],
)
def test_invalid_audio_is_rejected_before_model_load(settings, monkeypatch, audio):
    source = voice.VoiceInput(settings)
    monkeypatch.setattr(
        source, "_load_model", lambda: pytest.fail("Loaded model for invalid audio")
    )
    with pytest.raises(voice.VoiceError):
        source.transcribe(audio)


def test_silence_does_not_load_model_or_hallucinate(settings, monkeypatch):
    source = voice.VoiceInput(settings)
    monkeypatch.setattr(source, "_load_model", lambda: pytest.fail("Loaded model for silence"))
    assert source.transcribe(np.zeros(160, dtype=np.float32)) == ""


@pytest.fixture
def whisper_backend(tmp_path, monkeypatch):
    model_path = tmp_path / "cached-model"
    model_path.mkdir()
    for name in ("model.bin", "config.json", "tokenizer.json"):
        (model_path / name).write_text("test fixture", encoding="utf-8")
    calls = {"downloads": [], "models": [], "transcriptions": []}

    class Model:
        def __init__(self, path, **kwargs):
            calls["models"].append((path, kwargs))

        def transcribe(self, audio, **kwargs):
            calls["transcriptions"].append((audio, kwargs))
            return iter([SimpleNamespace(text=" Hello "), SimpleNamespace(text=" world ")]), None

    def download_model(name, **kwargs):
        calls["downloads"].append((name, kwargs))
        return str(model_path)

    backend = SimpleNamespace(WhisperModel=Model, download_model=download_model)
    real_import = voice.importlib.import_module
    monkeypatch.setattr(
        voice.importlib,
        "import_module",
        lambda name: backend if name == "faster_whisper" else real_import(name),
    )
    return model_path, backend, calls


def test_transcription_loads_only_local_files_and_reuses_model(settings, whisper_backend):
    model_path, _, calls = whisper_backend
    source = voice.VoiceInput(settings)
    audio = np.full(160, 0.1, dtype=np.float64)[::2]
    assert source.transcribe(audio) == "Hello world"
    assert source.transcribe(audio) == "Hello world"
    assert len(calls["models"]) == 1
    assert calls["downloads"][0][1]["local_files_only"] is True
    path, model_options = calls["models"][0]
    assert path == str(model_path)
    assert model_options["local_files_only"] is True
    assert model_options["device"] == "cpu"
    assert model_options["compute_type"] == "int8"
    samples, options = calls["transcriptions"][0]
    assert samples.dtype == np.float32 and samples.flags.c_contiguous
    assert options["vad_filter"] is True


def test_explicit_prepare_primes_only_local_model_without_capture(settings, whisper_backend):
    _, _, calls = whisper_backend
    source = voice.VoiceInput(settings)
    source.prepare()
    source.prepare()
    assert len(calls["models"]) == 1
    assert calls["downloads"][0][1]["local_files_only"] is True
    assert not calls["transcriptions"] and not source.recording


def test_missing_tokenizer_prevents_whisper_network_fallback(settings, whisper_backend):
    model_path, _, calls = whisper_backend
    (model_path / "tokenizer.json").unlink()
    source = voice.VoiceInput(settings)
    with pytest.raises(voice.VoiceError, match="missing tokenizer.json"):
        source.transcribe(np.full(160, 0.1, dtype=np.float32))
    assert calls["models"] == []
    assert calls["downloads"][0][1]["local_files_only"] is True


def test_uncached_model_has_clear_setup_message(settings, whisper_backend):
    _, backend, _ = whisper_backend

    def missing(*args, **kwargs):
        raise FileNotFoundError("not in local cache")

    backend.download_model = missing
    source = voice.VoiceInput(settings)
    with pytest.raises(voice.VoiceError, match="--download-speech-model"):
        source.transcribe(np.full(160, 0.1, dtype=np.float32))
    assert "not in local cache" in source.error


def test_transcription_generator_failure_is_reported(settings, whisper_backend):
    _, backend, _ = whisper_backend

    class BrokenModel:
        def __init__(self, *args, **kwargs):
            pass

        def transcribe(self, *args, **kwargs):
            def broken_segments():
                raise RuntimeError("decoder failed")
                yield  # noqa: B018

            return broken_segments(), None

    backend.WhisperModel = BrokenModel
    source = voice.VoiceInput(settings)
    with pytest.raises(voice.VoiceError, match="decoder failed"):
        source.transcribe(np.full(160, 0.1, dtype=np.float32))


def test_download_is_only_in_explicit_setup_helper(settings, whisper_backend):
    model_path, _, calls = whisper_backend
    assert voice.download_speech_model(settings) == model_path
    assert calls["downloads"][0][1]["local_files_only"] is False
    assert calls["downloads"][0][1]["cache_dir"] == str(settings.data_dir / "speech-models")
    assert calls["models"] == []


class FakeSignal:
    def connect(self, callback):
        self.callback = callback

    def emit(self, *args):
        self.callback(*args)


@pytest.fixture
def qt_speech(monkeypatch):
    engine_states = SimpleNamespace(Ready=0, Speaking=1, Error=2)
    engine_thread = object()
    current_thread = [engine_thread]
    engines = ["winrt", "sapi"]
    failed_engines = set()
    created = []

    class TextToSpeech:
        State = engine_states
        BoundaryHint = SimpleNamespace(Immediate="immediate")

        @staticmethod
        def availableEngines():
            return engines

        def __init__(self, name, params=None, parent=None):
            self.name = name
            self.params = params
            self._state = engine_states.Error if name in failed_engines else engine_states.Ready
            self.errorOccurred = FakeSignal()
            self.stateChanged = FakeSignal()
            self.spoken = []
            self.stopped = []
            self.selected = None
            self.voice_objects = [SimpleNamespace(name=lambda: "Windows Voice")]
            created.append(self)

        def state(self):
            return self._state

        def errorString(self):
            return "speech engine failed"

        def availableVoices(self):
            return self.voice_objects

        def thread(self):
            return engine_thread

        def setVoice(self, selected):
            self.selected = selected

        def say(self, text):
            self.spoken.append(text)
            self._state = engine_states.Speaking
            self.stateChanged.emit(self._state)

        def stop(self, boundary):
            self.stopped.append(boundary)
            self._state = engine_states.Ready
            self.stateChanged.emit(self._state)

        def setRate(self, rate):
            self.rate = rate

        def deleteLater(self):
            pass

    modules = {
        "PySide6.QtCore": SimpleNamespace(
            QCoreApplication=SimpleNamespace(instance=lambda: object()),
            QThread=SimpleNamespace(currentThread=lambda: current_thread[0]),
        ),
        "PySide6.QtTextToSpeech": SimpleNamespace(QTextToSpeech=TextToSpeech),
        "PySide6.QtMultimedia": SimpleNamespace(
            QMediaDevices=SimpleNamespace(
                audioOutputs=lambda: [
                    SimpleNamespace(id=lambda: b"headphones", description=lambda: "Test headphones")
                ]
            )
        ),
    }
    real_import = voice.importlib.import_module
    monkeypatch.setattr(
        voice.importlib,
        "import_module",
        lambda name: modules[name] if name in modules else real_import(name),
    )
    monkeypatch.setattr(voice.sys, "platform", "win32")
    return created, engines, failed_engines, current_thread, engine_states


def test_windows_speech_is_available_but_silent_on_construction(qt_speech):
    created, *_ = qt_speech
    speech = voice.SpeechOutput()
    assert speech.available and speech.error is None and speech.engine == "winrt"
    assert speech.voices() == ["Windows Voice"]
    assert created[0].spoken == []
    speech.set_voice("Windows Voice")
    assert created[0].selected is created[0].voice_objects[0]
    speech.speak("Hello")
    speech.stop()
    assert created[0].spoken == ["Hello."]
    assert created[0].stopped == ["immediate"]


def test_windows_speech_falls_back_to_installed_sapi(qt_speech):
    created, _, failed_engines, *_ = qt_speech
    failed_engines.add("winrt")
    speech = voice.SpeechOutput()
    assert speech.available and speech.engine == "sapi"
    assert all(engine.spoken == [] for engine in created)


def test_unavailable_speech_is_visible(qt_speech):
    _, engines, *_ = qt_speech
    engines.clear()
    speech = voice.SpeechOutput()
    assert not speech.available and "No supported" in speech.error
    assert speech.voices() == []
    with pytest.raises(voice.VoiceError, match="unavailable"):
        speech.speak("Hello")
    speech.stop()


def test_speech_runtime_error_is_visible(qt_speech):
    created, _, _, _, state = qt_speech
    speech = voice.SpeechOutput()
    created[0]._state = state.Error
    created[0].errorOccurred.callback(None, "audio output failed")
    assert not speech.available and speech.error == "speech engine failed"


def test_speech_rejects_wrong_thread_or_missing_voice(qt_speech):
    _, _, _, current_thread, _ = qt_speech
    speech = voice.SpeechOutput()
    with pytest.raises(voice.VoiceError, match="unavailable"):
        speech.set_voice("Unknown")
    current_thread[0] = object()
    with pytest.raises(voice.VoiceError, match="desktop thread"):
        speech.speak("Hello")
    with pytest.raises(voice.VoiceError, match="desktop thread"):
        speech.stop()


def test_speech_completion_stop_and_error_are_exactly_once(qt_speech):
    created, _, _, _, state = qt_speech
    speech = voice.SpeechOutput()
    completed = []
    unsubscribe = speech.on_finished(lambda: completed.append("finished"))
    assert speech.speak("Ready.") is True and speech.speaking
    created[0]._state = state.Ready
    created[0].stateChanged.emit(state.Ready)
    created[0].stateChanged.emit(state.Ready)
    assert completed == ["finished"] and not speech.speaking
    speech.speak("Ready.")
    speech.stop()
    speech.stop()
    assert completed == ["finished", "finished"] and not speech.speaking
    speech.speak("Ready.")
    created[0].errorOccurred.emit(None, "playback error")
    created[0].stateChanged.emit(state.Error)
    assert completed == ["finished"] * 3
    unsubscribe()
    created[0]._state = state.Ready
    speech._error = None
    speech.speak("Ready.")
    speech.stop()
    assert completed == ["finished"] * 3


def test_speech_replaces_active_utterance_and_normalizes_only_speech(qt_speech):
    created, *_ = qt_speech
    speech = voice.SpeechOutput()
    finished = []
    speech.on_finished(lambda: finished.append(True))
    speech.speak("First reply.")
    written = "**JARVIS ready.**\n- Ask for help!"
    speech.speak(written, replacements={"JARVIS": "Jarvis"})
    assert written == "**JARVIS ready.**\n- Ask for help!"
    assert created[0].spoken == ["First reply.", "Jarvis ready. Ask for help!"]
    assert created[0].stopped == ["immediate"]
    assert finished == [True] and speech.speaking


def test_speech_suppresses_machine_output_without_playback(qt_speech):
    created, *_ = qt_speech
    speech = voice.SpeechOutput()
    finished = []
    speech.on_finished(lambda: finished.append(True))
    assert speech.speak('{"task": "completed"}') is False
    assert speech.speak("```python\nprint('Hello')\n```") is False
    assert not speech.speaking and not created[0].spoken and not finished


@pytest.mark.parametrize("rate", [-1.1, 1.1, True, float("nan"), float("inf"), "fast"])
def test_speech_rejects_invalid_rate(qt_speech, rate):
    with pytest.raises(voice.VoiceError, match="rate"):
        voice.SpeechOutput().set_rate(rate)


def test_speech_rate_is_applied(qt_speech):
    created, *_ = qt_speech
    speech = voice.SpeechOutput()
    speech.set_rate(0.2)
    assert created[0].rate == 0.2


def test_speaker_enumeration_and_winrt_constructor_device_selection(qt_speech):
    created, *_ = qt_speech
    speakers = voice.SpeechOutput.output_devices()
    assert speakers == [{"id": b"headphones".hex(), "name": "Test headphones"}]
    assert not created
    speech = voice.SpeechOutput(output_device=speakers[0]["id"])
    assert speech.available and speech.engine == "winrt"
    assert bytes(created[0].params["audioDevice"].id()) == b"headphones"
    assert not created[0].spoken


def test_disconnected_speaker_is_visible_and_never_falls_back(qt_speech):
    created, *_ = qt_speech
    speech = voice.SpeechOutput(output_device=b"disconnected".hex())
    assert not speech.available and "disconnected" in speech.error
    assert not created


def test_sapi_fallback_cannot_silently_ignore_requested_speaker(qt_speech):
    created, _, failed_engines, *_ = qt_speech
    failed_engines.add("winrt")
    speech = voice.SpeechOutput(output_device=b"headphones".hex())
    assert not speech.available
    assert [engine.name for engine in created] == ["winrt"]

"""Review desktop speech integration using completion callbacks like native Qt.

No microphone or speaker is opened. The adapter fake exercises synchronous stop
callbacks, speech preparation, and device reconstruction through the real UI.
"""

import sys
import threading
from types import SimpleNamespace

import pytest
from test_desktop import app as app
from test_desktop import wait_until
from test_desktop import window as window

from jarvis import desktop
from jarvis.conversation import VoiceState
from jarvis.speech_text import normalize_speech


class ReviewSignal:
    def __init__(self):
        self.callbacks = []

    def connect(self, callback):
        self.callbacks.append(callback)

    def emit(self, state):
        for callback in tuple(self.callbacks):
            callback(SimpleNamespace(name=state))


class CompletionSpeech:
    instances = []

    def __init__(self, parent=None, output_device=None):
        self.device = output_device
        self.available = output_device in {None, "speaker-one"}
        self.error = None if self.available else "The selected speaker is disconnected."
        self.speaking = False
        self.written = []
        self.spoken = []
        self.callbacks = []
        self.stops = 0
        self.deleted = False
        self.rate = None
        self._tts = SimpleNamespace(deleteLater=self._delete, stateChanged=ReviewSignal())
        self.instances.append(self)

    def _delete(self):
        self.deleted = True

    @staticmethod
    def output_devices():
        return [{"id": "speaker-one", "name": "Test headphones"}]

    def on_finished(self, callback):
        self.callbacks.append(callback)

    def voices(self):
        return ["Test voice"]

    def set_voice(self, name):
        self.selected_voice = name

    def set_rate(self, rate):
        self.rate = rate

    def speak(self, text, *, replacements=None):
        self.written.append(text)
        spoken = normalize_speech(text, replacements)
        if not spoken:
            return False
        if self.speaking:
            self.stop()
        self.speaking = True
        self.spoken.append(spoken)
        self._tts.stateChanged.emit("Speaking")
        return True

    def stop(self):
        self.stops += 1
        if self.speaking:
            self.speaking = False
            self._tts.stateChanged.emit("Ready")
            for callback in tuple(self.callbacks):
                callback()


class ReviewCapture:
    def __init__(self):
        self.running = True
        self.mode = "wake"
        self.generation = 1
        self.closed = False

    def set_mode(self, mode):
        if mode != self.mode:
            self.generation += 1
        self.mode = mode
        return self.generation

    def close(self):
        self.running = False
        self.closed = True


@pytest.fixture
def speech_adapter(window, monkeypatch):
    CompletionSpeech.instances.clear()
    monkeypatch.setitem(
        sys.modules,
        "jarvis.voice",
        SimpleNamespace(
            SpeechOutput=CompletionSpeech,
            VoiceInput=lambda settings: SimpleNamespace(devices=lambda: []),
        ),
    )
    window.speak_check.setChecked(True)
    return window._speech


@pytest.fixture
def speaking_session(app, window, speech_adapter):
    controller = window.voice_controller
    controller.timer.stop()
    window.settings.wake_enabled = True
    window.wake_check.setChecked(True)
    controller.input = ReviewCapture()
    controller.session.enable()
    controller.session.wake("Hello")
    controller.session.processing()
    yield controller
    controller.stop("disable")
    wait_until(app, lambda: not window._jobs)


def test_replacing_utterance_keeps_microphone_gated_until_new_completion(
    app, window, speech_adapter, speaking_session
):
    controller = speaking_session
    controller.speak("First reply.")
    assert controller.session.state == VoiceState.ASSISTANT_SPEAKING
    controller.speak("Second reply.")
    assert speech_adapter.spoken == ["First reply.", "Second reply."]
    assert speech_adapter.speaking
    assert controller.session.state == VoiceState.ASSISTANT_SPEAKING
    assert controller.input.mode == "gated"
    assert not controller._resume_after
    speech_adapter.stop()
    assert controller.session.state == VoiceState.FOLLOW_UP_LISTENING
    assert controller._resume_after


def test_ui_uses_speech_only_normalization_dictionary_and_rate(
    app, window, speech_adapter, speaking_session
):
    window.settings.pronunciation_replacements = {"API": "A P I"}
    window.settings.speech_rate = 0.15
    written = "**API ready.**\n- Ask me for help?"
    window._append_message("JARVIS", written)
    speaking_session.speak(written)
    assert written in window.conversation.toPlainText()
    assert speech_adapter.spoken == ["A P I ready. Ask me for help?"]
    assert speech_adapter.rate == 0.15
    assert speaking_session.session.state == VoiceState.ASSISTANT_SPEAKING


def test_machine_only_reply_returns_to_listening_without_waiting_for_tts(
    app, window, speech_adapter, speaking_session
):
    speaking_session.speak('{"id": "task-1", "state": "completed"}')
    assert not speech_adapter.speaking and not speech_adapter.spoken
    assert speaking_session.session.state == VoiceState.FOLLOW_UP_LISTENING
    assert speaking_session.input.mode == "gated"
    assert speaking_session._resume_after


def test_disabling_speech_replies_stops_playback_and_preserves_followup(
    app, window, speech_adapter, speaking_session
):
    speaking_session.speak("A spoken reply.")
    window.speak_check.setChecked(False)
    assert not speech_adapter.speaking
    assert speaking_session.session.state == VoiceState.FOLLOW_UP_LISTENING
    assert speaking_session._resume_after


def test_muting_stops_playback_closes_capture_and_late_completion_stays_muted(
    app, window, speech_adapter, speaking_session
):
    capture = speaking_session.input
    speaking_session.speak("A spoken reply.")
    speaking_session.mute()
    wait_until(app, lambda: not window._jobs)
    for callback in speech_adapter.callbacks:
        callback()
    assert not speech_adapter.speaking
    assert speaking_session.session.state == VoiceState.MUTED
    assert speaking_session.input is None and capture.closed
    assert not speaking_session._resume_after


def test_speaker_change_save_recreates_engine_and_honors_selected_device(
    app, window, speech_adapter
):
    window.speaker_choice.addItem("Test headphones", "speaker-one")
    window.speaker_choice.setCurrentIndex(1)
    window.save_configuration()
    wait_until(app, lambda: not window._jobs)
    assert window.settings.speaker_device == "speaker-one"
    assert speech_adapter.deleted and window._speech is None
    window._speak("Ready.")
    assert window._speech is not speech_adapter
    assert window._speech.device == "speaker-one"
    assert window._speech.spoken == ["Ready."]


def test_invalid_speaker_choice_errors_then_default_save_recovers(app, window, speech_adapter):
    window.speaker_choice.addItem("Disconnected headphones", "missing-speaker")
    window.speaker_choice.setCurrentIndex(1)
    window.save_configuration()
    wait_until(app, lambda: not window._jobs)
    window._speak("Ready.")
    assert "disconnected" in window.status_label.text()
    assert not window._speech.available and not window._speech.spoken
    window.speaker_choice.setCurrentIndex(0)
    window.save_configuration()
    wait_until(app, lambda: not window._jobs)
    window._speak("Ready.")
    assert window._speech.available and window._speech.device is None
    assert window._speech.spoken == ["Ready."]


def test_mute_during_pending_settings_save_remains_authoritative(
    app, window, speech_adapter, speaking_session, monkeypatch
):
    entered, release = threading.Event(), threading.Event()
    original_save = desktop.save_settings

    def slow_save(settings):
        entered.set()
        release.wait(3)
        original_save(settings)

    monkeypatch.setattr(desktop, "save_settings", slow_save)
    window.save_configuration()
    wait_until(app, entered.is_set)
    speaking_session.mute()
    assert speaking_session.session.state == VoiceState.MUTED
    try:
        release.set()
        wait_until(app, lambda: not window._jobs)
        assert speaking_session.session.state == VoiceState.MUTED
        assert speaking_session.input is None
    finally:
        release.set()


def test_saving_unrelated_settings_does_not_unmute_an_existing_session(
    app, window, speech_adapter, speaking_session
):
    speaking_session.mute()
    wait_until(app, lambda: not window._jobs)
    window.rate_spin.setValue(0.1)
    window.save_configuration()
    wait_until(app, lambda: not window._jobs)
    assert window.settings.speech_rate == 0.1
    assert speaking_session.session.state == VoiceState.MUTED
    assert speaking_session.input is None

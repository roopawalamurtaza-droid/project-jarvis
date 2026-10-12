"""Execute desktop voice integration with fake capture, STT, and playback events.

These prove state and cancellation behavior; they do not measure microphone
accuracy, loudspeaker echo, or human-audible interruption latency.
"""

import sys
import threading
import time
from types import SimpleNamespace

import pytest
from test_desktop import app as desktop_app
from test_desktop import wait_until
from test_desktop import window as desktop_window

from jarvis.conversation import VoiceState
from jarvis.service import JarvisService
from jarvis.tasks import TaskEngine

app = desktop_app
window = desktop_window


class FakeCapture:
    instances = []

    def __init__(self, settings, on_event):
        self.settings = settings
        self.on_event = on_event
        self.running = False
        self.mode = "wake"
        self.generation = 0
        self.modes = []
        self.closed = False
        self.error = None
        self.instances.append(self)

    def start(self):
        self.running = True
        self.generation += 1
        self.emit("ready")

    def set_mode(self, mode):
        self.modes.append(mode)
        if mode != self.mode:
            self.mode = mode
            self.generation += 1
        return self.generation

    def close(self):
        self.running = False
        self.closed = True
        self.generation += 1

    def emit(self, event, **details):
        self.on_event({"event": event, "generation": self.generation, "mode": self.mode, **details})


class FakeSpeech:
    available = True

    def __init__(self):
        self.spoken = []
        self.speaking = False
        self.stops = 0

    def speak(self, text, **kwargs):
        self.spoken.append(text)
        self.speaking = True

    def stop(self):
        self.stops += 1
        self.speaking = False


@pytest.fixture
def handsfree(app, window, monkeypatch):
    monkeypatch.setitem(
        sys.modules, "jarvis.handsfree", SimpleNamespace(HandsFreeInput=FakeCapture)
    )
    window.settings.wake_enabled = True
    controller = window.voice_controller
    controller.timer.stop()
    controller.start()
    wait_until(app, lambda: not window._jobs)
    controller.poll()
    assert controller.session.state == VoiceState.WAKE_WORD_LISTENING
    yield controller
    controller.stop("disable")
    wait_until(app, lambda: not window._jobs)


def spoken_replies(window):
    speech = FakeSpeech()
    window._speech = speech
    window.speak_check.setChecked(True)
    return speech


def test_hands_free_same_utterance_calls_service_without_send_button(app, window, handsfree):
    capture = handsfree.input
    capture.emit("wake", command="What time is it?", text="Hey Jarvis, what time is it?")
    handsfree.poll()
    wait_until(app, lambda: not window._jobs)
    assert window.service.calls == [("What time is it?", None)]
    assert handsfree.session.state == VoiceState.FOLLOW_UP_LISTENING
    assert capture.mode == "command"
    assert "Reply: What time is it?" in window.conversation.toPlainText()


def test_wake_followup_and_timeout_require_no_button(app, window, handsfree):
    capture = handsfree.input
    capture.emit("wake", command="", text="Hey Jarvis")
    handsfree.poll()
    assert handsfree.session.state == VoiceState.ACTIVATED
    assert capture.mode == "command"
    capture.emit("speech_started")
    capture.emit("transcribing")
    capture.emit("utterance", text="Open Chrome")
    handsfree.poll()
    wait_until(app, lambda: not window._jobs)
    assert handsfree.session.state == VoiceState.FOLLOW_UP_LISTENING
    capture.emit("speech_started")
    capture.emit("utterance", text="And what time is it?")
    handsfree.poll()
    wait_until(app, lambda: not window._jobs)
    assert [call[0] for call in window.service.calls] == ["Open Chrome", "And what time is it?"]
    assert handsfree.session.state == VoiceState.FOLLOW_UP_LISTENING
    handsfree.session.clock = lambda: handsfree.session.deadline + 1
    handsfree.poll()
    assert handsfree.session.state == VoiceState.WAKE_WORD_LISTENING
    assert capture.mode == "wake"


def test_followup_speech_and_stt_do_not_expire_as_idle(app, window, handsfree):
    capture = handsfree.input
    capture.emit("wake", command="Hello")
    handsfree.poll()
    wait_until(app, lambda: not window._jobs)
    expiration = handsfree.session.deadline
    capture.emit("speech_started")
    capture.emit("transcribing")
    handsfree.poll()
    handsfree.session.clock = lambda: expiration + 60
    handsfree.poll()
    assert handsfree.session.state == VoiceState.USER_SPEAKING
    assert capture.mode == "command"
    capture.emit("utterance", text="This took longer to recognize")
    handsfree.poll()
    wait_until(app, lambda: not window._jobs)
    assert window.service.calls[-1][0] == "This took longer to recognize"
    assert handsfree.session.state == VoiceState.FOLLOW_UP_LISTENING


def test_contextual_thanks_continue_but_exact_thanks_ends(app, window, handsfree):
    capture = handsfree.input
    capture.emit("wake", command="Hello")
    handsfree.poll()
    wait_until(app, lambda: not window._jobs)
    capture.emit("utterance", text="Thanks Jarvis, can you explain this?")
    handsfree.poll()
    wait_until(app, lambda: not window._jobs)
    assert window.service.calls[-1][0] == "Thanks Jarvis, can you explain this?"
    capture.emit("utterance", text="Thanks Jarvis")
    handsfree.poll()
    assert handsfree.session.state == VoiceState.WAKE_WORD_LISTENING
    assert capture.mode == "wake"
    assert len(window.service.calls) == 2


def test_empty_transcription_restores_bounded_followup(app, window, handsfree):
    capture = handsfree.input
    capture.emit("wake", command="")
    handsfree.poll()
    capture.emit("speech_started")
    capture.emit("empty")
    handsfree.poll()
    assert handsfree.session.state == VoiceState.FOLLOW_UP_LISTENING
    assert handsfree.session.deadline is not None
    assert window.service.calls == []


def test_mute_closes_capture_and_discards_queued_wake(app, window, handsfree):
    capture = handsfree.input
    capture.emit("wake", command="This must not be sent")
    handsfree.mute()
    wait_until(app, lambda: not window._jobs)
    handsfree.poll()
    assert handsfree.session.state == VoiceState.MUTED
    assert handsfree.input is None
    assert capture.closed and not capture.running
    assert window.service.calls == []


def test_muted_voice_never_speaks_a_typed_reply(app, window, handsfree):
    speech = spoken_replies(window)
    handsfree.mute()
    wait_until(app, lambda: not window._jobs)
    window.composer.setPlainText("Typed request while muted")
    window.send_message()
    wait_until(app, lambda: not window._jobs)
    assert window.service.calls[-1][0] == "Typed request while muted"
    assert speech.spoken == []
    assert handsfree.session.state == VoiceState.MUTED


def test_interrupt_processing_turn_recovers_followup(app, window, handsfree):
    window.service.release.clear()
    capture = handsfree.input
    capture.emit("wake", command="Slow request")
    handsfree.poll()
    wait_until(app, window.service.started.is_set)
    assert handsfree.session.state == VoiceState.PROCESSING
    window.interrupt()
    wait_until(app, lambda: not window._jobs)
    assert handsfree.session.state == VoiceState.FOLLOW_UP_LISTENING
    assert handsfree.session.deadline is not None
    assert "Request cancelled" in window.conversation.toPlainText()


def test_default_playback_gates_microphone_and_discards_prior_generation(app, window, handsfree):
    speech = spoken_replies(window)
    capture = handsfree.input
    capture.emit("wake", command="Hello")
    handsfree.poll()
    wait_until(app, lambda: not window._jobs)
    assert speech.spoken == ["Reply: Hello"]
    assert handsfree.session.state == VoiceState.ASSISTANT_SPEAKING
    assert capture.mode == "gated"
    stale = {"event": "utterance", "generation": capture.generation - 1, "text": "Own echo"}
    handsfree.events.put_nowait((handsfree.epoch, stale))
    handsfree.poll()
    assert len(window.service.calls) == 1
    assert handsfree.session.state == VoiceState.ASSISTANT_SPEAKING


def test_opt_in_stop_only_capture_interrupts_playback(app, window, handsfree):
    speech = spoken_replies(window)
    window.settings.voice_interruption = True
    capture = handsfree.input
    capture.emit("wake", command="Hello")
    handsfree.poll()
    wait_until(app, lambda: not window._jobs)
    assert capture.mode == "stop"
    capture.emit("stop_command", text="Jarvis stop")
    handsfree.poll()
    assert speech.stops >= 1 and not speech.speaking
    assert handsfree.session.state == VoiceState.FOLLOW_UP_LISTENING
    assert len(window.service.calls) == 1


def test_stale_playback_tail_cannot_reopen_microphone_during_new_reply(app, window, handsfree):
    spoken_replies(window)
    capture = handsfree.input
    capture.emit("wake", command="Hello")
    handsfree.poll()
    wait_until(app, lambda: not window._jobs)
    handsfree.speech_finished()
    handsfree._resume_after = time.monotonic() - 1
    # A second response starts before the previous speaker-tail delay expires.
    handsfree.session.processing()
    handsfree.speak("Another answer")
    handsfree.poll()
    assert handsfree.session.state == VoiceState.ASSISTANT_SPEAKING
    assert capture.mode == "gated"


def test_typed_send_interrupts_current_playback_before_processing(app, window, handsfree):
    speech = spoken_replies(window)
    handsfree.input.emit("wake", command="Hello")
    handsfree.poll()
    wait_until(app, lambda: not window._jobs)
    assert handsfree.session.state == VoiceState.ASSISTANT_SPEAKING
    window.composer.setPlainText("Typed follow-up")
    window.send_message()
    wait_until(app, lambda: not window._jobs)
    assert [call[0] for call in window.service.calls] == ["Hello", "Typed follow-up"]
    assert speech.stops >= 1


def test_rejected_voice_command_during_history_transition_does_not_strand_session(
    app, window, handsfree
):
    entered, release = threading.Event(), threading.Event()

    def history_transition():
        entered.set()
        release.wait(3)

    window._run("history", history_transition)
    wait_until(app, entered.is_set)
    handsfree.input.emit("wake", command="Request while loading history")
    handsfree.poll()
    try:
        assert window.service.calls == []
        assert handsfree.session.state in {VoiceState.ACTIVATED, VoiceState.FOLLOW_UP_LISTENING}
        assert handsfree.session.deadline is not None
    finally:
        release.set()
        wait_until(app, lambda: not window._jobs)


def test_muted_output_can_resume_without_granting_hands_free_permission(app, window, handsfree):
    handsfree.stop("disable")
    wait_until(app, lambda: not window._jobs)
    window.settings.wake_enabled = False
    speech = spoken_replies(window)
    handsfree.mute()
    handsfree.toggle()
    assert handsfree.session.state == VoiceState.IDLE
    assert handsfree.input is None
    window.composer.setPlainText("Typed request after unmuting")
    window.send_message()
    wait_until(app, lambda: not window._jobs)
    assert speech.spoken == ["Reply: Typed request after unmuting"]


def test_capture_error_recovers_even_if_controller_event_queue_was_full(app, window, handsfree):
    capture = handsfree.input
    for _ in range(handsfree.events.maxsize):
        capture.emit("ready")
    capture.generation += 1
    capture.running = False
    capture.error = "Microphone disconnected during queue backlog"
    capture.emit("error", message=capture.error)
    handsfree.poll()
    wait_until(app, lambda: not window._jobs)
    assert handsfree.session.state == VoiceState.ERROR
    assert handsfree.input is None
    assert capture.closed
    assert "Microphone disconnected" in window.status_label.text()


def test_stale_start_failure_cannot_unmute_or_override_new_epoch(
    app, window, handsfree, monkeypatch
):
    handsfree.stop("disable")
    wait_until(app, lambda: not window._jobs)
    entered, release = threading.Event(), threading.Event()

    class SlowStart(FakeCapture):
        def start(self):
            entered.set()
            release.wait(3)
            raise RuntimeError("Old device failed to prepare")

    monkeypatch.setitem(sys.modules, "jarvis.handsfree", SimpleNamespace(HandsFreeInput=SlowStart))
    handsfree.start()
    wait_until(app, entered.is_set)
    handsfree.mute()
    release.set()
    wait_until(app, lambda: not window._jobs)
    assert handsfree.session.state == VoiceState.MUTED
    assert handsfree.input is None
    assert "Old device failed" not in window.status_label.text()


def real_permission_engine(window):
    class ForbiddenProvider:
        name = "ollama"

        def generate(self, *args, **kwargs):
            raise AssertionError("An exact local voice command must not ask a model to execute it")

    window.settings.mode = "manual"
    engine = TaskEngine(window.settings, window.store)
    executed = []

    def unexpected_execution(tool, arguments):
        executed.append((tool, arguments))
        raise AssertionError("Approval is required before execution")

    engine.registry.execute = unexpected_execution
    window.engine = engine
    window.service = JarvisService(
        window.settings, window.store, engine, provider=ForbiddenProvider()
    )
    return executed


def test_hands_free_natural_open_app_keeps_real_manual_approval(app, window, handsfree):
    executed = real_permission_engine(window)
    handsfree.input.emit("wake", command="Open Chrome", text="Hey Jarvis, open Chrome")
    handsfree.poll()
    wait_until(app, lambda: not window._jobs)
    tasks = window.store.tasks()
    assert len(tasks) == 1
    assert tasks[0]["tool"] == "open_app"
    assert tasks[0]["arguments"] == {"app": "chrome"}
    assert tasks[0]["state"] == "awaiting_approval"
    assert executed == []
    assert "This action needs your approval" in window.conversation.toPlainText()
    assert handsfree.session.state == VoiceState.FOLLOW_UP_LISTENING


def test_hands_free_downloads_command_cannot_bypass_allowed_roots(app, window, handsfree):
    executed = real_permission_engine(window)
    handsfree.input.emit("wake", command="Open downloads")
    handsfree.poll()
    wait_until(app, lambda: not window._jobs)
    assert window.store.tasks() == []
    assert executed == []
    assert "outside the configured allowed folders" in window.conversation.toPlainText()
    assert any(item["event"] == "tool_denied" for item in window.store.audits())
    assert handsfree.session.state == VoiceState.FOLLOW_UP_LISTENING

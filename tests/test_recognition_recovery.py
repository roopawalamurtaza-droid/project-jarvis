"""Regression checks for completed local recognition and listening recovery.

Capture and transcription are fake. These exercise real desktop event handling
without opening a microphone or making an AI provider request.
"""

import time

import pytest
from test_desktop import wait_until
from test_handsfree import Backend, Events, Transcriber, Vad, feed, options
from test_voice_controller_review import app as controller_app
from test_voice_controller_review import handsfree as controller_handsfree
from test_voice_controller_review import spoken_replies
from test_voice_controller_review import window as controller_window

from jarvis.conversation import VoiceState
from jarvis.handsfree import HandsFreeInput

app = controller_app
handsfree = controller_handsfree
window = controller_window


@pytest.mark.parametrize("completion", ["ignored", "empty"])
def test_rejected_wake_recognition_recovers_and_accepts_next_command(
    app, window, handsfree, completion
):
    capture = handsfree.input
    capture.emit("transcribing")
    handsfree.poll()
    assert "Recognizing speech" in window.status_label.text()

    capture.emit(completion, reason="wake_phrase_not_found")
    handsfree.poll()
    assert "Recognizing speech" not in window.status_label.text()
    assert handsfree.session.state == VoiceState.WAKE_WORD_LISTENING
    assert capture.running and capture.mode == "wake"
    assert window.service.calls == []

    capture.emit("wake", command="What time is it?", text="Hey Jarvis, what time is it?")
    handsfree.poll()
    wait_until(app, lambda: not window._jobs)
    assert window.service.calls == [("What time is it?", None)]
    assert "Reply: What time is it?" in window.conversation.toPlainText()
    assert handsfree.session.state == VoiceState.FOLLOW_UP_LISTENING
    assert capture.running and capture.mode == "command"


def test_empty_followup_clears_recognition_and_restores_bounded_listening(app, window, handsfree):
    capture = handsfree.input
    capture.emit("wake", command="Hello")
    handsfree.poll()
    wait_until(app, lambda: not window._jobs)
    assert handsfree.session.state == VoiceState.FOLLOW_UP_LISTENING

    capture.emit("speech_started")
    capture.emit("transcribing")
    handsfree.poll()
    assert handsfree.session.state == VoiceState.USER_SPEAKING
    assert "Recognizing speech" in window.status_label.text()

    capture.emit("empty")
    handsfree.poll()
    assert "Recognizing speech" not in window.status_label.text()
    assert handsfree.session.state == VoiceState.FOLLOW_UP_LISTENING
    assert handsfree.session.deadline is not None
    assert "Follow Up Listening" in window.voice_status.text()
    assert capture.running and capture.mode == "command"
    assert window.service.calls == [("Hello", None)]


def test_pending_recognition_remains_visible_until_real_completion(app, window, handsfree):
    capture = handsfree.input
    capture.emit("transcribing")
    handsfree.poll()
    for _ in range(3):
        handsfree.poll()
        assert "recognizing speech" in window.voice_status.text()
        assert "Recognizing speech" in window.status_label.text()
        assert capture.running and capture.mode == "wake"
    capture.emit("ignored", reason="wake_phrase_not_found")
    handsfree.poll()
    assert "recognizing speech" not in window.voice_status.text()
    assert "Recognizing speech" not in window.status_label.text()
    assert window.service.calls == []


@pytest.mark.parametrize("mode,state", [("pause", VoiceState.SLEEPING), ("mute", VoiceState.MUTED)])
@pytest.mark.parametrize("completion", ["ignored", "empty", "wake"])
def test_cancelled_completion_cannot_override_pause_or_mute(
    app, window, handsfree, mode, state, completion
):
    capture = handsfree.input
    capture.emit("transcribing")
    handsfree.poll()
    old_epoch, old_generation = handsfree.epoch, capture.generation
    assert "recognizing speech" in window.voice_status.text()

    handsfree.stop(mode)
    wait_until(app, lambda: not window._jobs)
    status_after_stop = window.status_label.text()
    assert "Recognizing speech" not in status_after_stop
    handsfree.events.put_nowait(
        (
            old_epoch,
            {
                "event": completion,
                "generation": old_generation,
                "mode": "wake",
                "command": "This cancelled request must not run",
            },
        )
    )
    handsfree.poll()
    assert handsfree.session.state == state
    assert handsfree.input is None
    assert capture.closed and not capture.running
    assert "microphone off" in window.voice_status.text()
    assert "recognizing speech" not in window.voice_status.text()
    assert window.status_label.text() == status_after_stop
    assert window.service.calls == []


def test_spoken_wake_acknowledgment_finishes_recognition_before_playback(app, window, handsfree):
    speech = spoken_replies(window)
    capture = handsfree.input
    capture.emit("transcribing")
    handsfree.poll()
    assert "recognizing speech" in window.voice_status.text()
    capture.emit("wake", command="", text="Hey Jarvis")
    handsfree.poll()
    assert len(speech.spoken) == 1
    assert handsfree.session.state == VoiceState.ASSISTANT_SPEAKING
    assert capture.mode == "gated"
    assert "Recognizing speech" not in window.status_label.text()
    assert "recognizing speech" not in window.voice_status.text()
    assert "Speaking reply" in window.status_label.text()

    speech.speaking = False
    handsfree.speech_finished()
    assert capture.mode == "gated"
    handsfree._resume_after = time.monotonic() - 1
    handsfree.poll()
    assert handsfree.session.state == VoiceState.ACTIVATED
    assert handsfree.session.deadline is not None
    assert capture.running and capture.mode == "command"
    assert "Listening for your next command" in window.status_label.text()
    assert window.service.calls == []


def test_stop_mode_unrelated_transcription_emits_completion_without_a_command():
    backend, transcriber, events = Backend(), Transcriber("What time is it?"), Events()
    pipeline = HandsFreeInput(options(), transcriber, events, backend, Vad())
    try:
        pipeline.set_mode("stop")
        pipeline.start()
        feed(pipeline, backend, 0.2, 10)
        feed(pipeline, backend, 0, 6)
        completion = events.wait("ignored")
        assert completion["mode"] == "stop"
        assert pipeline.is_current(completion)
        assert pipeline.running and pipeline.mode == "stop"
        assert len(transcriber.calls) == 1
        assert any(event["event"] == "transcribing" for event in events.items)
        assert not any(
            event["event"] in {"wake", "utterance", "stop_command"} for event in events.items
        )
    finally:
        pipeline.close()

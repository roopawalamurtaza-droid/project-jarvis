"""Conversation checks never access audio devices or wall-clock timers."""

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from jarvis.conversation import (
    ProactivePolicy,
    VoiceSession,
    VoiceState,
    VoiceTransitionError,
    current_datetime,
    greeting,
    normalize_utterance,
    route_voice_command,
    strip_wake_prefix,
)


class Clock:
    def __init__(self):
        self.value = 100.0

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += seconds


@pytest.fixture
def settings():
    return SimpleNamespace(
        wake_enabled=False,
        wake_phrase="hey jarvis",
        conversation_timeout=20,
        speech_start_timeout=8,
        greeting_style="brief",
        timezone="UTC",
        proactive_enabled=False,
        quiet_start=22,
        quiet_end=8,
        proactive_interval_seconds=300,
    )


def test_complete_hands_free_conversation_has_explicit_states(settings):
    clock = Clock()
    session = VoiceSession(settings, clock)
    assert session.state == VoiceState.IDLE
    assert session.enable() == VoiceState.WAKE_WORD_LISTENING
    assert session.wake() == "Yes, sir?"
    assert session.state == VoiceState.ACTIVATED
    assert session.assistant_speaking() == VoiceState.ASSISTANT_SPEAKING
    assert session.speech_finished() == VoiceState.ACTIVATED
    assert session.speech_started() == VoiceState.USER_SPEAKING
    assert session.processing() == VoiceState.PROCESSING
    assert session.assistant_speaking() == VoiceState.ASSISTANT_SPEAKING
    assert session.speech_finished() == VoiceState.FOLLOW_UP_LISTENING
    assert session.speech_started() == VoiceState.USER_SPEAKING
    assert session.processing() == VoiceState.PROCESSING
    assert session.assistant_speaking() == VoiceState.ASSISTANT_SPEAKING
    assert session.speech_finished() == VoiceState.FOLLOW_UP_LISTENING
    clock.advance(20)
    assert session.tick() == VoiceState.WAKE_WORD_LISTENING


def test_same_utterance_command_does_not_delay_for_acknowledgment(settings):
    session = VoiceSession(settings)
    session.enable()
    assert session.wake("What time is it?") is None
    assert session.processing() == VoiceState.PROCESSING


def test_acknowledgment_playback_does_not_use_up_start_timeout(settings):
    clock = Clock()
    session = VoiceSession(settings, clock)
    session.enable()
    session.wake()
    session.assistant_speaking()
    clock.advance(100)
    assert session.tick() == VoiceState.ASSISTANT_SPEAKING
    session.speech_finished()
    clock.advance(7.99)
    assert session.tick() == VoiceState.ACTIVATED
    clock.advance(0.01)
    assert session.tick() == VoiceState.WAKE_WORD_LISTENING


def test_follow_up_timeout_is_configurable_and_paused_during_user_speech(settings):
    settings.conversation_timeout = 3
    clock = Clock()
    session = VoiceSession(settings, clock)
    session.enable()
    session.wake("Hello")
    session.processing()
    session.assistant_speaking()
    session.speech_finished()
    clock.advance(2.9)
    assert session.tick() == VoiceState.FOLLOW_UP_LISTENING
    session.speech_started()
    clock.advance(60)
    assert session.tick() == VoiceState.USER_SPEAKING
    assert session.deadline is None


@pytest.mark.parametrize("command", ["Thanks, Jarvis.", "That's all!", "Go to sleep."])
def test_exact_end_commands(command):
    assert route_voice_command(command) == "end"


@pytest.mark.parametrize(
    "command",
    [
        "Thanks Jarvis, can you open Chrome?",
        "That's all I know about the task.",
        "Please explain why you can stop listening.",
        "I said wait until noon.",
    ],
)
def test_contextual_words_do_not_end_or_interrupt(command):
    assert route_voice_command(command) is None


@pytest.mark.parametrize("command", ["Jarvis stop", "Stop talking.", "WAIT!"])
def test_stop_commands(command):
    assert route_voice_command(command) == "stop"


def test_command_normalization_keeps_contractions_and_word_boundaries():
    assert normalize_utterance("THAT’S\n ALL!") == "that's all"
    assert route_voice_command("that’s all") == "end"
    assert route_voice_command("mute microphone") == "mute"


def test_optional_jarvis_address_preserves_exact_command_matching():
    assert route_voice_command("Jarvis, go to sleep.") == "end"
    assert route_voice_command("Jarvis, mute microphone.") == "mute"
    assert route_voice_command("Jarvis, stop talking.") == "stop"
    assert route_voice_command("Jarvis, thanks, can you open Chrome?") is None


@pytest.mark.parametrize(
    ("text", "result"),
    [
        ("Hey Jarvis", ""),
        ("Hey, Jarvis! Open Chrome.", "Open Chrome."),
        ("  HEY JARVIS, what time is it?  ", "what time is it?"),
        ("they Jarvis open Chrome", None),
        ("Hey Jarvisian", None),
        ("HeyJarvis", None),
        ("Please say Hey Jarvis", None),
    ],
)
def test_exact_wake_prefix_preserves_same_utterance_command(text, result):
    assert strip_wake_prefix(text) == result


def test_custom_wake_phrase_and_empty_phrase():
    assert strip_wake_prefix("Hello assistant. Open my project.", "hello assistant") == (
        "Open my project."
    )
    with pytest.raises(ValueError):
        strip_wake_prefix("Hey Jarvis", " ... ")


def test_mute_disable_and_late_playback_callback_cannot_reopen_listening(settings):
    session = VoiceSession(settings)
    session.enable()
    session.wake()
    session.assistant_speaking()
    assert session.mute() == VoiceState.MUTED
    assert session.speech_finished() == VoiceState.MUTED
    assert session.end() == VoiceState.MUTED
    assert session.resume() == VoiceState.WAKE_WORD_LISTENING
    session.wake()
    session.assistant_speaking()
    assert session.disable() == VoiceState.IDLE
    assert session.speech_finished() == VoiceState.IDLE


def test_muting_an_idle_session_does_not_enable_microphone(settings):
    session = VoiceSession(settings)
    session.mute()
    assert session.resume() == VoiceState.IDLE


def test_pause_and_error_resume_to_passive_listening_without_active_context(settings):
    session = VoiceSession(settings)
    session.enable()
    session.wake("Hello")
    session.processing()
    assert session.pause() == VoiceState.SLEEPING
    assert session.end() == VoiceState.SLEEPING
    assert session.resume() == VoiceState.WAKE_WORD_LISTENING
    assert session.fail("The input device disconnected.") == VoiceState.ERROR
    assert session.error == "The input device disconnected."
    assert session.speech_finished() == VoiceState.ERROR
    assert session.resume() == VoiceState.WAKE_WORD_LISTENING
    assert session.error is None


def test_barge_in_user_state_survives_late_playback_completion(settings):
    session = VoiceSession(settings)
    session.enable()
    session.wake("Tell me something")
    session.processing()
    session.assistant_speaking()
    assert session.speech_started() == VoiceState.USER_SPEAKING
    assert session.speech_finished() == VoiceState.USER_SPEAKING


@pytest.mark.parametrize("source", ["processing", "empty_transcription", "activated"])
def test_turn_without_playback_returns_to_follow_up(settings, source):
    session = VoiceSession(settings)
    session.enable()
    session.wake("What time is it?")
    if source == "processing":
        session.processing()
    elif source == "empty_transcription":
        session.speech_started()
    assert session.response_finished() == VoiceState.FOLLOW_UP_LISTENING
    assert session.deadline is not None


@pytest.mark.parametrize("control", ["mute", "disable", "pause", "fail"])
def test_late_turn_finish_cannot_override_capture_controls(settings, control):
    session = VoiceSession(settings)
    session.enable()
    session.wake("What time is it?")
    session.processing()
    expected = (
        getattr(session, control)("Disconnected")
        if control == "fail"
        else (getattr(session, control)())
    )
    assert session.response_finished() == expected
    assert session.deadline is None


def test_response_finished_retains_acknowledgment_continuation(settings):
    session = VoiceSession(settings)
    session.enable()
    session.wake()
    session.assistant_speaking()
    assert session.response_finished() == VoiceState.ACTIVATED


def test_invalid_events_are_rejected_and_valid_repeat_events_are_idempotent(settings):
    session = VoiceSession(settings)
    with pytest.raises(VoiceTransitionError):
        session.wake()
    with pytest.raises(VoiceTransitionError):
        session.processing()
    session.enable()
    with pytest.raises(VoiceTransitionError):
        session.assistant_speaking()
    session.wake("hello")
    session.processing()
    assert session.processing() == VoiceState.PROCESSING
    session.assistant_speaking()
    assert session.assistant_speaking() == VoiceState.ASSISTANT_SPEAKING
    session.speech_finished()
    assert session.speech_finished() == VoiceState.FOLLOW_UP_LISTENING


def test_greetings_rotate_and_sir_is_sparingly_used(settings):
    session = VoiceSession(settings)
    session.enable()
    assert [session.wake() for _ in range(3)] == [
        "Yes, sir?",
        "I'm listening.",
        "How can I help?",
    ]


@pytest.mark.parametrize(
    ("hour", "period"), [(4, "evening"), (8, "morning"), (14, "afternoon"), (23, "evening")]
)
def test_greetings_use_actual_time_without_invented_user_activity(settings, hour, period):
    settings.greeting_style = "professional"
    now = datetime(2026, 10, 13, hour, tzinfo=timezone.utc)
    assert greeting(settings, now=now) == f"Good {period}. How can I assist?"


def test_configured_timezone_changes_time_context(settings):
    settings.timezone = "Asia/Calcutta"
    now = datetime(2026, 10, 13, 4, tzinfo=timezone.utc)
    local = current_datetime(settings, now)
    assert (local.hour, local.minute) == (9, 30)
    settings.greeting_style = "friendly"
    assert greeting(settings, now=now) == "Good morning. How can I help?"


def test_unavailable_timezone_falls_back_to_actual_local_zone(settings):
    settings.timezone = "Unavailable/Zone"
    now = datetime(2026, 10, 13, 4, tzinfo=timezone.utc)
    assert current_datetime(settings, now) == now.astimezone()


def test_silent_style_produces_no_acknowledgment_or_proactive_speech(settings):
    settings.greeting_style = "silent"
    settings.proactive_enabled = True
    session = VoiceSession(settings)
    session.enable()
    assert session.wake() is None
    policy = ProactivePolicy(settings)
    assert policy.event("task_completed", "Saved report") is None


def test_proactive_requires_opt_in_a_real_event_and_non_quiet_hours(settings):
    clock = Clock()
    policy = ProactivePolicy(settings, clock)
    day = datetime(2026, 10, 13, 12, tzinfo=timezone.utc)
    assert policy.event("task_completed", "Created folder", now=day) is None
    settings.proactive_enabled = True
    assert policy.event("idle", now=day) is None
    assert policy.event("task_completed", "Created folder", now=day) == (
        "Task completed: Created folder."
    )
    clock.advance(299)
    assert policy.event("error", "Device disconnected", now=day) is None
    clock.advance(1)
    assert policy.event("error", "Device disconnected", now=day) == (
        "An error occurred: Device disconnected."
    )
    night = datetime(2026, 10, 13, 22, tzinfo=timezone.utc)
    clock.advance(300)
    assert policy.event("task_completed", "Created folder", now=night) is None


def test_activation_notice_occurs_at_most_once_per_day(settings):
    settings.proactive_enabled = True
    settings.greeting_style = "friendly"
    clock = Clock()
    policy = ProactivePolicy(settings, clock)
    morning = datetime(2026, 10, 13, 8, tzinfo=timezone.utc)
    assert policy.event("activation", now=morning) == "Good morning. How can I help?"
    clock.advance(600)
    assert policy.event("activation", now=morning) is None
    assert policy.event("activation", now=morning.replace(day=14)) is not None


def test_quiet_first_activation_does_not_emit_a_later_daily_greeting(settings):
    settings.proactive_enabled = True
    clock = Clock()
    policy = ProactivePolicy(settings, clock)
    night = datetime(2026, 10, 13, 1, tzinfo=timezone.utc)
    assert policy.event("activation", now=night) is None
    clock.advance(600)
    assert policy.event("activation", now=night.replace(hour=12)) is None
    assert policy.event("activation", now=night.replace(day=14, hour=12)) is not None


def test_quiet_hours_support_daytime_and_midnight_windows(settings):
    policy = ProactivePolicy(settings)
    day = datetime(2026, 10, 13, 12, tzinfo=timezone.utc)
    assert policy.quiet(day) is False
    assert policy.quiet(day.replace(hour=1)) is True
    settings.quiet_start, settings.quiet_end = 11, 14
    assert policy.quiet(day) is True
    assert policy.quiet(day.replace(hour=15)) is False
    settings.quiet_start = settings.quiet_end
    assert policy.quiet(day) is False

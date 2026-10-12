"""Deterministic conversation states and local, event-grounded voice wording.

This module never opens a microphone, starts a timer, or speaks. The desktop
drives it from capture, transcription, and playback events on its UI thread.
"""

from __future__ import annotations

import re
import time
import unicodedata
from datetime import datetime
from enum import Enum
from typing import Callable, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class VoiceState(str, Enum):
    IDLE = "IDLE"
    WAKE_WORD_LISTENING = "WAKE_WORD_LISTENING"
    ACTIVATED = "ACTIVATED"
    USER_SPEAKING = "USER_SPEAKING"
    PROCESSING = "PROCESSING"
    ASSISTANT_SPEAKING = "ASSISTANT_SPEAKING"
    FOLLOW_UP_LISTENING = "FOLLOW_UP_LISTENING"
    SLEEPING = "SLEEPING"
    MUTED = "MUTED"
    ERROR = "ERROR"


class VoiceTransitionError(RuntimeError):
    """An event arrived in a state that cannot accept it."""


def normalize_utterance(text: str) -> str:
    """Normalize only for exact command matching, preserving word boundaries."""
    text = unicodedata.normalize("NFKC", text).casefold().replace("’", "'")
    return " ".join(re.sub(r"[^\w']+", " ", text).split())


def strip_wake_prefix(text: str, phrase: str = "hey jarvis") -> str | None:
    """Return the trailing command after an exact leading wake phrase.

    An empty string means the wake phrase alone. ``None`` means no match.
    Substrings such as "they Jarvis" or "Hey Jarvisian" never activate voice.
    """
    words = normalize_utterance(phrase).split()
    if not words:
        raise ValueError("The wake phrase must contain at least one word.")
    separator = r"[^\w']+"
    pattern = r"^\s*" + separator.join(re.escape(word) for word in words)
    pattern += r"(?=$|[^\w'])"
    source = unicodedata.normalize("NFKC", text).replace("’", "'")
    match = re.match(pattern, source, flags=re.IGNORECASE)
    if match is None:
        return None
    return re.sub(r"^[^\w']+", "", source[match.end() :]).strip()


VoiceCommand = Literal["end", "mute", "stop"]

_END_COMMANDS = {
    "thanks jarvis",
    "thank you jarvis",
    "that's all",
    "that's all jarvis",
    "that is all",
    "go to sleep",
    "you can stop listening",
    "stop listening",
    "thanks jarvis go to sleep",
    "thank you jarvis go to sleep",
}
_MUTE_COMMANDS = {"mute", "mute microphone", "jarvis mute", "mute jarvis", "mute yourself"}
_STOP_COMMANDS = {
    "stop",
    "jarvis stop",
    "stop talking",
    "stop speaking",
    "wait",
    "jarvis wait",
    "jarvis stop talking",
}


def route_voice_command(text: str) -> VoiceCommand | None:
    """Route full utterances only; polite words inside a request are ordinary text."""
    normalized = normalize_utterance(text)
    normalized = normalized.removeprefix("jarvis ")
    if normalized in _END_COMMANDS:
        return "end"
    if normalized in _MUTE_COMMANDS:
        return "mute"
    if normalized in _STOP_COMMANDS:
        return "stop"
    return None


def current_datetime(settings, now: datetime | None = None) -> datetime:
    """Use the configured zone, or the actual system zone when unavailable."""
    timezone_name = getattr(settings, "timezone", "")
    zone = None
    if timezone_name:
        try:
            zone = ZoneInfo(timezone_name)
        except (ZoneInfoNotFoundError, ValueError):
            # A missing timezone database must never invent a location or hour.
            pass
    if now is None:
        return datetime.now(zone).astimezone() if zone is None else datetime.now(zone)
    if now.tzinfo is None and zone is not None:
        return now.replace(tzinfo=zone)
    return now.astimezone(zone)


def greeting(settings, *, now: datetime | None = None, variation: int = 0) -> str | None:
    """A varied greeting grounded only in the current local time and chosen style."""
    style = getattr(settings, "greeting_style", "brief")
    if style == "silent":
        return None
    hour = current_datetime(settings, now).hour
    period = "morning" if 5 <= hour < 12 else "afternoon" if 12 <= hour < 18 else "evening"
    forms = {
        "brief": (
            "Yes, sir?",
            "I'm listening.",
            "How can I help?",
        ),
        "friendly": (
            f"Good {period}. How can I help?",
            "Hello. What would you like to do?",
            "I'm here. What can I help with?",
        ),
        "professional": (
            f"Good {period}. How can I assist?",
            "I'm listening. How can I assist?",
            "Ready. What would you like me to do?",
        ),
    }
    choices = forms.get(style, forms["brief"])
    return choices[variation % len(choices)]


class VoiceSession:
    """Authoritative state machine for one hands-free conversation.

    ``wake`` produces optional wording and enters ACTIVATED. Playback of that
    acknowledgment returns to ACTIVATED; playback following PROCESSING returns
    to FOLLOW_UP_LISTENING. Only those two listening states expire. UI/device
    ownership, capture cancellation, and stale worker results remain the
    caller's responsibility.
    """

    def __init__(self, settings, clock: Callable[[], float] = time.monotonic):
        self.settings = settings
        self.clock = clock
        self.state = VoiceState.IDLE
        self.error: str | None = None
        self.deadline: float | None = None
        self._resume_state = VoiceState.IDLE
        self._after_speech = VoiceState.FOLLOW_UP_LISTENING
        self._greeting_count = 0

    def _enter(self, state: VoiceState) -> VoiceState:
        self.state = state
        self.deadline = None
        if state == VoiceState.ACTIVATED:
            self.deadline = self.clock() + float(self.settings.speech_start_timeout)
        elif state == VoiceState.FOLLOW_UP_LISTENING:
            self.deadline = self.clock() + float(self.settings.conversation_timeout)
        return state

    def _require(self, event: str, allowed: set[VoiceState]) -> None:
        if self.state not in allowed:
            raise VoiceTransitionError(f"{event} cannot run while voice is {self.state.value}.")

    def enable(self) -> VoiceState:
        self.error = None
        self._resume_state = VoiceState.WAKE_WORD_LISTENING
        return self._enter(VoiceState.WAKE_WORD_LISTENING)

    def disable(self) -> VoiceState:
        self.error = None
        self._resume_state = VoiceState.IDLE
        return self._enter(VoiceState.IDLE)

    def mute(self) -> VoiceState:
        if self.state == VoiceState.MUTED:
            return self.state
        self._resume_state = (
            VoiceState.IDLE if self.state == VoiceState.IDLE else VoiceState.WAKE_WORD_LISTENING
        )
        return self._enter(VoiceState.MUTED)

    def pause(self) -> VoiceState:
        if self.state in {VoiceState.IDLE, VoiceState.MUTED, VoiceState.SLEEPING}:
            return self.state
        self._resume_state = VoiceState.WAKE_WORD_LISTENING
        return self._enter(VoiceState.SLEEPING)

    def resume(self) -> VoiceState:
        if self.state not in {VoiceState.MUTED, VoiceState.SLEEPING, VoiceState.ERROR}:
            return self.state
        self.error = None
        return self._enter(self._resume_state)

    def wake(self, command: str = "") -> str | None:
        self._require(
            "Wake",
            {VoiceState.WAKE_WORD_LISTENING, VoiceState.ACTIVATED, VoiceState.FOLLOW_UP_LISTENING},
        )
        self._enter(VoiceState.ACTIVATED)
        if command.strip():
            return None
        text = greeting(self.settings, variation=self._greeting_count)
        self._greeting_count += 1
        return text

    def speech_started(self) -> VoiceState:
        self._require(
            "Speech start",
            {
                VoiceState.ACTIVATED,
                VoiceState.FOLLOW_UP_LISTENING,
                VoiceState.ASSISTANT_SPEAKING,
                VoiceState.USER_SPEAKING,
            },
        )
        return self._enter(VoiceState.USER_SPEAKING)

    def processing(self) -> VoiceState:
        self._require(
            "Processing",
            {
                VoiceState.ACTIVATED,
                VoiceState.USER_SPEAKING,
                VoiceState.FOLLOW_UP_LISTENING,
                VoiceState.PROCESSING,
            },
        )
        return self._enter(VoiceState.PROCESSING)

    def assistant_speaking(self) -> VoiceState:
        self._require(
            "Playback start",
            {
                VoiceState.ACTIVATED,
                VoiceState.PROCESSING,
                VoiceState.FOLLOW_UP_LISTENING,
                VoiceState.ASSISTANT_SPEAKING,
            },
        )
        if self.state == VoiceState.ASSISTANT_SPEAKING:
            return self.state
        self._after_speech = (
            VoiceState.ACTIVATED
            if self.state == VoiceState.ACTIVATED
            else VoiceState.FOLLOW_UP_LISTENING
        )
        return self._enter(VoiceState.ASSISTANT_SPEAKING)

    def speech_finished(self) -> VoiceState:
        # A late playback callback after mute, interruption, or disable must
        # never reopen a microphone or override a newer user-speech event.
        if self.state != VoiceState.ASSISTANT_SPEAKING:
            return self.state
        return self._enter(self._after_speech)

    def response_finished(self) -> VoiceState:
        """Finish a turn even when playback is disabled or transcription is empty.

        Acknowledgment playback retains its normal ACTIVATED continuation.
        Late worker callbacks cannot resume capture after mute, pause, disable,
        or a device failure.
        """
        if self.state == VoiceState.ASSISTANT_SPEAKING:
            return self.speech_finished()
        if self.state in {
            VoiceState.PROCESSING,
            VoiceState.USER_SPEAKING,
            VoiceState.ACTIVATED,
            VoiceState.FOLLOW_UP_LISTENING,
        }:
            return self._enter(VoiceState.FOLLOW_UP_LISTENING)
        return self.state

    def tick(self) -> VoiceState:
        if self.deadline is not None and self.clock() >= self.deadline:
            return self._enter(VoiceState.WAKE_WORD_LISTENING)
        return self.state

    def end(self) -> VoiceState:
        if self.state in {
            VoiceState.IDLE,
            VoiceState.MUTED,
            VoiceState.SLEEPING,
            VoiceState.ERROR,
        }:
            return self.state
        return self._enter(VoiceState.WAKE_WORD_LISTENING)

    def fail(self, message: str) -> VoiceState:
        if self.state not in {VoiceState.MUTED, VoiceState.SLEEPING, VoiceState.ERROR}:
            self._resume_state = (
                VoiceState.IDLE if self.state == VoiceState.IDLE else VoiceState.WAKE_WORD_LISTENING
            )
        self.error = str(message)[:500] or "The voice system encountered an error."
        return self._enter(VoiceState.ERROR)


class ProactivePolicy:
    """Allow optional speech only for a supplied real event, respecting quiet hours."""

    def __init__(self, settings, clock: Callable[[], float] = time.monotonic):
        self.settings = settings
        self.clock = clock
        self._last_spoken: float | None = None
        self._last_activation_date = None

    def quiet(self, now: datetime | None = None) -> bool:
        hour = current_datetime(self.settings, now).hour
        start = int(self.settings.quiet_start)
        end = int(self.settings.quiet_end)
        if start == end:
            return False
        return start <= hour < end if start < end else hour >= start or hour < end

    def event(
        self,
        kind: Literal["task_completed", "error", "activation"],
        detail: str = "",
        *,
        now: datetime | None = None,
    ) -> str | None:
        if not self.settings.proactive_enabled or self.settings.greeting_style == "silent":
            return None
        if kind not in {"task_completed", "error", "activation"}:
            return None
        local = current_datetime(self.settings, now)
        if kind == "activation":
            if self._last_activation_date == local.date():
                return None
            # Record the first real activation even when quiet hours or the
            # speech cooldown suppress its greeting. A later wake is not the
            # first activation of that day.
            self._last_activation_date = local.date()
        if self.quiet(local):
            return None
        clock_now = self.clock()
        if self._last_spoken is not None and clock_now - self._last_spoken < float(
            self.settings.proactive_interval_seconds
        ):
            return None
        # Details are provided by the real task/device event, never inferred
        # from idle time, transcript guesses, or a model's action claims.
        detail = " ".join(str(detail).split())[:240].rstrip(".!?")
        if kind == "activation":
            text = greeting(self.settings, now=local)
            if text is None:
                return None
        elif kind == "task_completed":
            text = f"Task completed: {detail}." if detail else "The task completed."
        else:
            text = f"An error occurred: {detail}." if detail else "An error needs your attention."
        self._last_spoken = clock_now
        return text

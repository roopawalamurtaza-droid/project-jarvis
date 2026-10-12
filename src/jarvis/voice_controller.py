"""Desktop integration for the deterministic hands-free conversation session."""

from __future__ import annotations

import logging
import queue
import time

from PySide6.QtCore import QObject, QTimer

from .conversation import ProactivePolicy, VoiceSession, VoiceState, route_voice_command


class VoiceController(QObject):
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.session = VoiceSession(window.settings)
        self.proactive = ProactivePolicy(window.settings)
        self.input = None
        self.epoch = 0
        self.events = queue.Queue(maxsize=32)
        self.metrics: dict[str, float] = {}
        self._reply_start = 0.0
        self._speech_requested_at = 0.0
        self._last_voice_at = 0.0
        self._resume_after = 0.0
        self._recognition_started_at = None
        self.timer = QTimer(self)
        self.timer.setInterval(80)
        self.timer.timeout.connect(self.poll)
        self.timer.start()
        if window.settings.wake_enabled:
            QTimer.singleShot(0, self.start)

    @property
    def active(self):
        return self.session.state not in {
            VoiceState.IDLE,
            VoiceState.SLEEPING,
            VoiceState.MUTED,
            VoiceState.ERROR,
        }

    def _display(self):
        capture = bool(self.input and self.input.running)
        gated = capture and self.input.mode == "gated"
        state = self.session.state.value.replace("_", " ").title()
        microphone = "gated (stream open)" if gated else "active" if capture else "off"
        text = f"Voice: {state} · microphone {microphone}"
        if self._recognition_started_at is not None:
            text += " · recognizing speech"
        self.window.voice_status.setText(text)
        self.window.listen_button.setText("Pause listening" if self.active else "Resume listening")
        if self.window.tray:
            self.window.tray.setToolTip(f"JARVIS · {text}")
        if hasattr(self.window, "build_health_label"):
            self.window._update_build_health()

    def start(self):
        window = self.window
        if not window.settings.wake_enabled:
            if self.session.state == VoiceState.MUTED:
                self.session.disable()
                self._display()
                window._status("Voice unmuted · microphone remains off.")
                return
            window._status("Enable hands-free microphone permission in Settings first.")
            return
        if window._closing or window._stopped:
            return
        if any(
            name in window._jobs
            for name in ("record", "chat", "settings", "handsfree-start", "handsfree-close")
        ):
            window._status("Finish active work before resuming hands-free listening.")
            return
        if self.input and self.input.running:
            return
        from .handsfree import HandsFreeInput

        self.epoch += 1
        epoch = self.epoch

        def event(item):
            try:
                self.events.put_nowait((epoch, item))
            except queue.Full:
                # Keep the latest completion/error ahead of obsolete status events.
                try:
                    self.events.get_nowait()
                    self.events.put_nowait((epoch, item))
                except (queue.Empty, queue.Full):
                    pass

        capture = HandsFreeInput(window.settings.model_copy(deep=True), on_event=event)
        self.input = capture
        self.session.enable()
        window._status("Preparing offline hands-free recognition…")
        self._display()

        def start_capture():
            capture.start()
            if epoch != self.epoch:
                capture.close()

        window._run(
            "handsfree-start",
            start_capture,
            failure=lambda error: self.failed(error) if epoch == self.epoch else None,
        )

    def stop(self, mode="pause"):
        self.epoch += 1
        self._resume_after = 0
        self._finish_recognition("cancelled")
        if mode == "mute":
            self.session.mute()
        elif mode == "disable":
            self.session.disable()
        else:
            self.session.pause()
        capture, self.input = self.input, None
        if capture:
            capture.set_mode("gated")
            self.window._run("handsfree-close", capture.close)
        if self.window._speech:
            self.window._speech.stop()
        status = {
            "mute": "Voice muted · microphone off.",
            "disable": "Hands-free disabled · microphone off.",
        }.get(mode, "Listening paused · microphone off.")
        self.window._status(status)
        self._display()

    def toggle(self):
        self.stop() if self.active else self.start()

    def schedule_restart(self):
        epoch = self.epoch

        def ready():
            if epoch != self.epoch or self.window._closing or not self.window.settings.wake_enabled:
                return
            if any(
                name in self.window._jobs
                for name in ("settings", "handsfree-close", "handsfree-start")
            ):
                QTimer.singleShot(100, ready)
            else:
                self.start()

        QTimer.singleShot(100, ready)

    def mute(self):
        self.window.interrupt()
        self.stop("mute")

    def gate(self):
        self._resume_after = 0
        self._finish_recognition("cancelled")
        if self.input:
            self.input.set_mode("gated")

    def _listen_for_state(self):
        if not self.input or not self.active:
            return
        if self.session.state not in {
            VoiceState.WAKE_WORD_LISTENING,
            VoiceState.ACTIVATED,
            VoiceState.FOLLOW_UP_LISTENING,
        }:
            return
        mode = "wake" if self.session.state == VoiceState.WAKE_WORD_LISTENING else "command"
        self.input.set_mode(mode)
        self._listening_status()
        self._display()

    def poll(self):
        if self.window._closing:
            return
        if self.input and getattr(self.input, "error", None):
            self.failed(self.input.error)
            return
        for _ in range(32):
            try:
                epoch, item = self.events.get_nowait()
            except queue.Empty:
                break
            if epoch != self.epoch or self.input is None:
                continue
            if item.get("generation") != self.input.generation:
                continue
            self.handle(item)
        previous = self.session.state
        self.session.tick()
        if self._resume_after and time.monotonic() >= self._resume_after:
            self._resume_after = 0
            self._listen_for_state()
        if previous != self.session.state:
            self._listen_for_state()
            self._display()

    def _finish_recognition(self, outcome):
        if self._recognition_started_at is not None:
            elapsed = time.monotonic() - self._recognition_started_at
            self.metrics["last_recognition_seconds"] = round(elapsed, 3)
            # No recognized text or audio is retained in logs.
            logging.getLogger("jarvis").info(
                "Voice recognition finished (%s, %.3fs)", outcome, elapsed
            )
        self._recognition_started_at = None

    def _listening_status(self, prefix=""):
        if self.session.state == VoiceState.WAKE_WORD_LISTENING:
            self.window._status(f'{prefix}Listening for "{self.window.settings.wake_phrase}".')
        elif self.session.state in {VoiceState.ACTIVATED, VoiceState.FOLLOW_UP_LISTENING}:
            self.window._status(f"{prefix}Listening for your next command.")
        elif self.session.state == VoiceState.ASSISTANT_SPEAKING:
            self.window._status("Speaking reply…")

    def handle(self, item):
        event = item["event"]
        if event in {"wake", "utterance", "stop_command", "empty", "ignored", "error"}:
            self._finish_recognition(event)
        if event == "error":
            self.failed(item.get("error") or item.get("message") or "Microphone disconnected.")
            return
        if event == "ready":
            self._listening_status()
            self._display()
        elif event == "speech_started":
            if self.session.state in {VoiceState.ACTIVATED, VoiceState.FOLLOW_UP_LISTENING}:
                self.session.speech_started()
            self._display()
        elif event == "transcribing":
            self._recognition_started_at = time.monotonic()
            logging.getLogger("jarvis").info("Voice recognition started (%s)", item.get("mode"))
            self.window._status("Recognizing speech locally…")
            self._display()
        elif event == "wake":
            self._last_voice_at = item.get("last_voice_at", 0.0)
            command = item.get("command", "").strip()
            self.gate()
            acknowledgment = self.session.wake(command)
            self.metrics.update(item.get("timing", {}))
            proactive = self.proactive.event("activation")
            if not command and proactive:
                acknowledgment = proactive
            if command:
                self.command(command)
            elif acknowledgment and self.window.speak_check.isChecked():
                self.window._append_message("JARVIS", acknowledgment)
                self.speak(acknowledgment)
            else:
                self._listen_for_state()
                self._listening_status()
            self._display()
        elif event == "utterance":
            self._last_voice_at = item.get("last_voice_at", 0.0)
            self.metrics.update(item.get("timing", {}))
            self.command(item.get("text", ""))
        elif event == "stop_command":
            self.window.interrupt()
        elif event == "empty":
            if self.session.state == VoiceState.USER_SPEAKING:
                self.session.response_finished()
                self._listen_for_state()
            self._listening_status("No clear speech recognized. ")
            self._display()
        elif event == "ignored":
            self.metrics["recognition_rejections"] = (
                self.metrics.get("recognition_rejections", 0) + 1
            )
            self._listening_status()
            self._display()
        elif event == "busy":
            self.window._status(item.get("message", "Recognition is busy. Please repeat."))

    def command(self, text):
        if not text.strip() or not self.active:
            return
        local = route_voice_command(text)
        if local == "mute":
            self.window._append_message("YOU", text)
            self.mute()
            return
        if local == "end":
            self.window._append_message("YOU", text)
            self.session.end()
            self._listen_for_state()
            self._display()
            return
        if local == "stop":
            self.window.interrupt()
            self.session.response_finished()
            self._listen_for_state()
            return
        self.gate()
        self.session.processing()
        self._reply_start = time.monotonic()
        self.window.composer.setPlainText(text)
        if not self.window.send_message():
            if "chat" not in self.window._jobs:
                self.session.response_finished()
                self._listen_for_state()
            self.window._status(
                "Voice request deferred. Finish active work and repeat your command."
            )
        self._display()

    def speak(self, text):
        speech = self.window._speech
        if speech and getattr(speech, "speaking", False):
            speech.stop()
        self.gate()
        self.session.assistant_speaking()
        self.window._status("Speaking reply…")
        self._display()
        if self.input and self.window.settings.voice_interruption:
            # Explicit headset-only opt-in; default acoustic protection is half duplex.
            self.input.set_mode("stop")
        self.window._speak(text)

    def reply(self, text):
        if not self.active:
            if self.session.state == VoiceState.MUTED:
                return
            if self.window.speak_check.isChecked():
                self.window._speak(text)
            return
        if self._reply_start:
            self.metrics["response_seconds"] = round(time.monotonic() - self._reply_start, 3)
        if self.window.speak_check.isChecked() and text:
            self.speak(text)
        else:
            self.session.response_finished()
            self._listen_for_state()

    def speech_finished(self):
        if self.session.state == VoiceState.ASSISTANT_SPEAKING:
            self.session.response_finished()
            self.gate()
            # Flush speaker tail before accepting speech; pending results are invalidated.
            self._resume_after = time.monotonic() + 0.35
            self.window._status("Finishing playback before listening…")
            self._display()

    def playback_started(self):
        now = time.monotonic()
        if self._speech_requested_at:
            self.metrics["tts_backend_startup_seconds"] = round(now - self._speech_requested_at, 3)
        if self._last_voice_at:
            self.metrics["speech_end_to_playback_backend_seconds"] = round(
                now - self._last_voice_at, 3
            )

    def interrupted(self):
        if self.active:
            self.gate()
            self.session.response_finished()
            self._resume_after = time.monotonic() + 0.35
            self._display()

    def failed(self, error):
        self.stop("disable")
        self.session.fail(error)
        self.window._status(f"Hands-free unavailable: {error}")
        self._display()

    def task_event(self, task):
        kind = {"completed": "task_completed", "failed": "error"}.get(task.get("state"))
        if not kind or self.session.state not in {VoiceState.IDLE, VoiceState.WAKE_WORD_LISTENING}:
            return
        message = self.proactive.event(kind)
        if message and self.window.speak_check.isChecked():
            if self.active:
                self.session.wake("event")
                self.session.processing()
                self.speak(message)
            else:
                self.window._speak(message)

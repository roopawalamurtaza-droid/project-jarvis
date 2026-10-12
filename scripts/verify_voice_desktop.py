"""Actual Qt + VAD + offline STT + local provider integration on synthetic PCM.

This does not open a microphone. It injects labeled synthetic audio through the
actual capture callback, sends hands-free commands, plays through Windows TTS,
and saves a real window capture and timings. Run with a running local Ollama.
"""

from __future__ import annotations

import argparse
import json
import os
import threading
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from verify_handsfree import PlaybackBackend, generate_fixture

from jarvis import handsfree
from jarvis.__main__ import build_service
from jarvis.config import load_settings
from jarvis.conversation import VoiceState
from jarvis.desktop import MainWindow
from jarvis.health import build_identity


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, default=Path(".local"))
    parser.add_argument(
        "--actions",
        action="store_true",
        help="Explicitly launch Chrome and VS Code through the existing permissions",
    )
    args = parser.parse_args()
    settings = load_settings(args.data_dir).model_copy(deep=True)
    settings.wake_enabled = True
    settings.speech_enabled = True
    settings.voice_interruption = False
    settings.conversation_timeout = 20
    settings.save_history = False
    settings.greeting_style = "friendly"
    if settings.provider != "ollama":
        raise RuntimeError("This diagnostic uses only the local provider.")
    fixtures = settings.data_dir / "handsfree-fixtures"
    fixtures.mkdir(parents=True, exist_ok=True)
    wake = generate_fixture(fixtures / "desktop-wake.wav", "Hey Jarvis, what time is it?")
    follow = generate_fixture(fixtures / "desktop-followup.wav", "Reply with just the word ready.")
    end = generate_fixture(fixtures / "desktop-end.wav", "Thanks Jarvis. Go to sleep.")
    wake_only = generate_fixture(fixtures / "desktop-wake-only.wav", "Hey Jarvis.")
    unmatched = generate_fixture(
        fixtures / "desktop-unmatched.wav", "Please open the weather forecast."
    )
    backend = PlaybackBackend()
    original = handsfree.HandsFreeInput
    handsfree.HandsFreeInput = lambda settings, **kwargs: original(
        settings, audio_backend=backend, **kwargs
    )
    application = QApplication.instance() or QApplication([])
    application.setQuitOnLastWindowClosed(False)
    service = build_service(settings)
    window = MainWindow(service, settings, service.store, service.engine)
    window.show()
    ticks = []
    timer = QTimer()
    timer.setInterval(20)
    timer.timeout.connect(lambda: ticks.append(time.monotonic()))
    timer.start()

    def wait(condition, timeout=90):
        deadline = time.monotonic() + timeout
        while not condition():
            application.processEvents()
            if time.monotonic() >= deadline:
                raise RuntimeError(
                    f"Desktop integration timed out: {window.voice_status.text()} / {window.status_label.text()}"
                )
            time.sleep(0.005)
        application.processEvents()

    def play(audio):
        worker = threading.Thread(target=backend.play, args=(audio,), daemon=True)
        worker.start()
        wait(lambda: not worker.is_alive(), timeout=40)

    report = {
        "evidence": "synthetic PCM, actual Qt/VAD/offline STT/local provider/Windows playback; no microphone",
        "model": settings.model,
        "build": build_identity(),
    }
    try:
        wait(
            lambda: (
                window.voice_controller.input is not None
                and window.voice_controller.input.recording
                and "handsfree-start" not in window._jobs
            )
        )
        play(unmatched)
        wait(lambda: window.voice_controller.metrics.get("recognition_rejections", 0) >= 1)
        if (
            window.voice_controller.session.state != VoiceState.WAKE_WORD_LISTENING
            or "Recognizing" in window.status_label.text()
            or "YOU\n" in window.conversation.toPlainText()
        ):
            raise RuntimeError("Unmatched speech did not finish safely in wake listening")
        report["unmatched_speech_returns_to_wake"] = True
        report["status_after_unmatched_speech"] = window.status_label.text()
        started = time.monotonic()
        play(wake)
        wait(lambda: "YOU\nwhat time is it?".lower() in window.conversation.toPlainText().lower())
        wait(
            lambda: (
                window.voice_controller.session.state == VoiceState.FOLLOW_UP_LISTENING
                and window.voice_controller.input.mode == "command"
            )
        )
        report["wake_turn_metrics"] = dict(window.voice_controller.metrics)
        report["wake_turn_including_playback_seconds"] = round(time.monotonic() - started, 3)
        first_session = window.session_id
        started = time.monotonic()
        play(follow)
        wait(
            lambda: (
                "Reply with just the word ready.".lower()
                in window.conversation.toPlainText().lower()
            )
        )
        wait(
            lambda: (
                "chat" not in window._jobs
                and window.voice_controller.session.state == VoiceState.FOLLOW_UP_LISTENING
                and window.voice_controller.input.mode == "command"
            )
        )
        report["follow_up_metrics"] = dict(window.voice_controller.metrics)
        report["follow_up_including_playback_seconds"] = round(time.monotonic() - started, 3)
        report["same_session"] = window.session_id == first_session
        if args.actions:
            report["desktop_actions"] = []
            for name, phrase in (("chrome", "Open Chrome."), ("vscode", "And open VS Code.")):
                sample = generate_fixture(fixtures / f"desktop-{name}.wav", phrase)
                play(sample)
                wait(
                    lambda: (
                        "chat" not in window._jobs
                        and window.voice_controller.session.state == VoiceState.FOLLOW_UP_LISTENING
                        and window.voice_controller.input.mode == "command"
                    )
                )
                tasks = service.store.tasks()
                task = next(
                    (item for item in tasks if item.get("arguments", {}).get("app") == name), None
                )
                if task is None or task["state"] not in {"completed", "awaiting_approval"}:
                    raise RuntimeError(f"{name} voice action failed: {task}")
                report["desktop_actions"].append(
                    {
                        "app": name,
                        "state": task["state"],
                        "result": task["result"],
                        "note": "Process/launcher evidence; application window visibility not asserted",
                    }
                )
        report["ui_ticks"] = len(ticks)
        report["maximum_ui_timer_gap_seconds"] = round(
            max((b - a for a, b in zip(ticks, ticks[1:])), default=0), 3
        )
        screenshot = Path("artifacts/JARVIS-handsfree.png").resolve()
        screenshot.parent.mkdir(exist_ok=True)
        if not window.grab().save(str(screenshot)):
            raise RuntimeError("Could not save real Qt capture")
        play(end)
        wait(lambda: window.voice_controller.session.state == VoiceState.WAKE_WORD_LISTENING)
        report["end_command_returns_to_wake"] = True
        play(wake_only)
        wait(
            lambda: (
                window.voice_controller.session.state == VoiceState.ACTIVATED
                and window.voice_controller.input.mode == "command"
            )
        )
        report["standalone_wake_acknowledged"] = True
        play(end)
        wait(lambda: window.voice_controller.session.state == VoiceState.WAKE_WORD_LISTENING)
        window.voice_controller.mute()
        wait(lambda: "handsfree-close" not in window._jobs)
        report["mute_closes_microphone"] = (
            window.voice_controller.input is None
            and window.voice_controller.session.state == VoiceState.MUTED
        )
        report["text"] = window.conversation.toPlainText()
    finally:
        timer.stop()
        window.close()
        wait(lambda: not window._jobs and not window.isVisible())
        service.store.close()
        handsfree.HandsFreeInput = original
    target = settings.data_dir / "voice-desktop-report.json"
    target.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()

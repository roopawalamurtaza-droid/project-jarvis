"""Explicit desktop/package verification; no model calls or microphone capture."""

from __future__ import annotations

import json
import sys
import time

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from jarvis.desktop import MainWindow
from jarvis.voice import SpeechOutput, VoiceInput


def smoke_test(service, settings):
    app = QApplication.instance() or QApplication([])
    window = MainWindow(service, settings, service.store, service.engine)
    window.show()
    started = time.perf_counter()
    result = {"frozen": bool(getattr(sys, "frozen", False)), "desktop": "launched"}
    try:
        result["microphones"] = VoiceInput(settings).devices()
    except Exception as exc:
        result["microphone_error"] = str(exc)
    speech = SpeechOutput(window)
    result["speech"] = {
        "available": speech.available,
        "engine": speech.engine,
        "voices": speech.voices(),
        "error": speech.error,
    }
    timer = QTimer()

    def finish():
        if window._jobs:
            return
        result["elapsed_seconds"] = round(time.perf_counter() - started, 3)
        result["screenshot"] = str(settings.data_dir / "package-desktop.png")
        result["screenshot_saved"] = window.grab().save(result["screenshot"])
        (settings.data_dir / "package-verification.json").write_text(
            json.dumps(result, indent=2), encoding="utf-8"
        )
        timer.stop()
        window.close()

    timer.timeout.connect(finish)
    timer.start(200)
    return app.exec()

"""Render the real app and optionally exercise its live model worker. Never records audio."""

import argparse
import json
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from jarvis.__main__ import build_service
from jarvis.config import load_settings
from jarvis.desktop import MainWindow

parser = argparse.ArgumentParser()
parser.add_argument("--data-dir", type=Path, required=True)
parser.add_argument("--live", action="store_true")
args = parser.parse_args()
settings = load_settings(args.data_dir)
settings.speech_enabled = False
service = build_service(settings)
app = QApplication([])
window = MainWindow(service, settings, service.store, service.engine)
window.show()
root = Path(__file__).resolve().parents[1]
(root / "artifacts").mkdir(exist_ok=True)
started = time.perf_counter()
ticks = 0
report = {"live": args.live, "screenshot": str(root / "artifacts" / "JARVIS-desktop.png")}
timer = QTimer()


def check():
    global ticks
    ticks += 1
    if args.live and "chat" in window._jobs:
        if time.perf_counter() - started > settings.request_timeout + 10:
            report["error"] = "Desktop request failed to finish within its deadline"
            window.interrupt()
        else:
            return
    if window._jobs:
        return
    transcript = window.conversation.toPlainText()
    report["elapsed_seconds"] = round(time.perf_counter() - started, 3)
    report["ui_timer_ticks"] = ticks
    report["conversation"] = transcript
    report["model_response_visible"] = "I am JARVIS" in transcript or "I am Jarvis" in transcript
    window.grab().save(report["screenshot"])
    (root / ".local" / "desktop-verification.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )
    timer.stop()
    window.close()


timer.timeout.connect(check)
timer.start(100)
if args.live:
    window.composer.setPlainText("Reply with only: I am JARVIS. /no_think")
    QTimer.singleShot(100, window.send_message)
else:
    window._status("Desktop launch verification · microphone off")
code = app.exec()
service.emergency_stop()
service.store.close()
print(json.dumps(report, indent=2))
sys.exit(code if not args.live or report.get("model_response_visible") else 1)

"""Capture the actual Qt interface with isolated data and measured telemetry.

Offscreen captures are labelled as renders. --native uses the Windows graphical
platform. No microphone, cloud call or application launch is performed.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--native", action="store_true")
parser.add_argument("--output", type=Path, required=True)
parser.add_argument("--data-dir", type=Path, required=True)
parser.add_argument("--settings-from", type=Path)
parser.add_argument("--live", action="store_true")
parser.add_argument("--width", type=int, default=1440)
parser.add_argument("--height", type=int, default=840)
args = parser.parse_args()
if not args.native:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from jarvis.__main__ import build_service  # noqa: E402
from jarvis.config import Settings, load_settings  # noqa: E402
from jarvis.desktop import MainWindow  # noqa: E402

settings = load_settings(args.settings_from) if args.settings_from else Settings()
settings = settings.model_copy(
    deep=True,
    update={
        "data_dir": args.data_dir.resolve(),
        "allowed_roots": [(args.data_dir / "workspace").resolve()],
        "wake_enabled": False,
        "speech_enabled": False,
        "save_history": False,
        "desktop_context_enabled": False,
        "minimize_to_tray": False,
        "reduce_motion": True,
    },
)
app = QApplication([])
service = build_service(settings)
window = MainWindow(service, settings, service.store, service.engine)
window.resize(args.width, args.height)
window.show()
args.output.parent.mkdir(parents=True, exist_ok=True)
started = previous_tick = time.monotonic()
ticks = 0
max_gap = 0.0
sent = False
report = {
    "platform": app.platformName(),
    "offscreen": not args.native,
    "data_isolated": True,
    "microphone_requested": False,
    "cloud_requested": False,
    "live_requested": args.live,
    "source_identity": window.build_info,
    "screenshots": [],
}


def finish():
    window.grab().save(str(args.output))
    report["screenshots"].append(str(args.output))
    # This is a second real widget capture, never pasted into the main screenshot.
    window.toggle_mini()
    app.processEvents()
    mini_path = args.output.with_name(args.output.stem + "-mini.png")
    window.ambient_overlay.grab().save(str(mini_path))
    report["screenshots"].append(str(mini_path))
    navigation = []
    for index in range(len(window.page_titles)):
        window._navigate(index)
        app.processEvents()
        navigation.append(
            {"page": window.page_titles[index], "selected": window.pages.currentIndex() == index}
        )
    report["navigation"] = navigation
    window._navigate(0)
    report["all_navigation_selected"] = all(row["selected"] for row in navigation)
    report["system"] = window._awareness_data.get("system", {})
    report["live_reply_received"] = bool(window._last_reply) if args.live else None
    report["ui_ticks"] = ticks
    report["maximum_timer_gap_seconds"] = round(max_gap, 4)
    report["elapsed_seconds"] = round(time.monotonic() - started, 3)
    report["main_size"] = [window.width(), window.height()]
    report["dashboard_visible"] = window.dashboard.isVisible()
    args.output.with_suffix(".json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    timer.stop()
    window.close()


def poll():
    global ticks, previous_tick, max_gap, sent
    now = time.monotonic()
    max_gap = max(max_gap, now - previous_tick)
    previous_tick = now
    ticks += 1
    if args.live and not sent and not window._jobs:
        if settings.provider != "ollama":
            raise RuntimeError("Live UI verification permits only the configured local provider.")
        sent = True
        window.composer.setPlainText("Give three brief ways to organize a study session. /no_think")
        window.send_message()
    if now - started > settings.request_timeout + 15:
        report["error"] = "UI verification did not finish within its deadline."
        window.interrupt()
        finish()
    elif now - started >= 4 and not window._jobs:
        if not args.live or sent and window._last_reply:
            finish()


QTimer.singleShot(400, lambda: window.refresh_system(force=True))
QTimer.singleShot(1600, lambda: window.refresh_system(force=True))
timer = QTimer()
timer.setInterval(20)
timer.timeout.connect(poll)
timer.start()
code = app.exec()
service.emergency_stop()
service.store.close()
print(
    json.dumps(
        {
            "platform": report["platform"],
            "screenshots": report["screenshots"],
            "navigation": report.get("all_navigation_selected"),
            "live_reply": report.get("live_reply_received"),
            "max_gap": report.get("maximum_timer_gap_seconds"),
            "error": report.get("error"),
        },
        indent=2,
    )
)
sys.exit(code if not report.get("error") else 1)

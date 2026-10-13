"""Actual native action check, isolated receipts; no microphone or cloud requests.

--actions explicitly opens applications and public browser destinations under
the existing permission scope. Page loading is not inferred from launch results.
"""

from __future__ import annotations

import argparse
import json
import os
import time
import uuid
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from jarvis.config import load_settings
from jarvis.desktop import MainWindow
from jarvis.health import build_identity
from jarvis.service import JarvisService
from jarvis.storage import Store
from jarvis.tasks import TaskEngine


class ForbiddenProvider:
    name = "ollama"

    def generate(self, *args, **kwargs):
        raise AssertionError("Deterministic action requests must not use a language model")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--actions", action="store_true")
    args = parser.parse_args()
    original = load_settings(args.data_dir)
    root = original.data_dir / ("phase4-check-" + uuid.uuid4().hex[:8])
    settings = original.model_copy(deep=True)
    settings.data_dir = root
    settings.wake_enabled = settings.speech_enabled = settings.save_history = False
    settings.provider = "ollama"
    settings.model_action_planning = False
    store = Store(root)
    engine = TaskEngine(settings, store)
    service = JarvisService(settings, store, engine, provider=ForbiddenProvider())
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    window = MainWindow(service, settings, store, engine)
    window.show()
    report = {
        "build": build_identity(),
        "evidence": "Actual local Windows executor and native Qt; no microphone or cloud; generated isolated task data",
        "actions_authorized": args.actions,
        "output_dir": str(root),
        "commands": [],
    }
    ticks = []

    def wait(condition, timeout=35):
        deadline = time.monotonic() + timeout
        while not condition():
            app.processEvents()
            ticks.append(time.monotonic())
            if time.monotonic() > deadline:
                raise TimeoutError("Action diagnostic exceeded its worker deadline")
            time.sleep(0.01)
        app.processEvents()

    def request(message):
        window.composer.setPlainText(message)
        if not window.send_message():
            raise AssertionError("The native input rejected a verification request")
        wait(lambda: not window._jobs)
        reply = window._last_reply
        run = reply.get("action_run")
        if not run and "task" not in reply:
            raise AssertionError("Request did not enter the local action engine")
        report["commands"].append(
            {
                "request": message,
                "text": reply["text"],
                "state": run["state"] if run else reply["task"]["state"],
                "steps": run["steps"] if run else [reply["task"]],
            }
        )
        return reply

    try:
        wait(lambda: not window._jobs)
        records = engine.registry.applications.refresh()
        report["catalog_count"] = len(records)
        report["known_app_availability"] = {
            name: next(
                (
                    {"installed": True, "enabled": row["enabled"], "kind": row["kind"]}
                    for row in records
                    if row["id"] == name
                ),
                {"installed": False},
            )
            for name in (
                "notepad",
                "calculator",
                "chrome",
                "vscode",
                "spotify",
                "discord",
                "android_studio",
                "telegram",
            )
        }
        window._navigate(9)
        window.refresh_applications()
        wait(lambda: not window._jobs)
        screenshots = []
        library = root / "application-library.png"
        assert window.grab().save(str(library))
        screenshots.append(str(library))
        if args.actions:
            if settings.mode == "manual":
                raise PermissionError(
                    "This automated diagnostic cannot approve manual-mode actions; use the visible application for approval"
                )
            for command in (
                "Jarvis, open Notepad.",
                "Open Calculator.",
                "Open Chrome.",
                "Open VS Code too.",
                "Open File Explorer.",
                "Now open Chrome and search for Python tutorials.",
                "Search YouTube for Flutter tutorials.",
                "Open the official Python website.",
                "Open GitHub.",
                "Open another tab and search for Windows automation.",
                "Open Chrome and VS Code.",
            ):
                reply = request(command)
                if reply.get("action_run", {}).get("state") != "completed":
                    raise AssertionError("Expected supported action did not complete: " + command)
            request("Switch to Chrome.")  # foreground refusal is an honest bounded result
            if report["known_app_availability"]["spotify"].get("installed"):
                request("Open Spotify.")
            missing = request("Open JARVIS deliberately missing verification app.")
            assert missing["task"]["outcome"] == "application_not_found"
            partial = request(
                "Open Chrome, JARVIS deliberately missing verification app, and VS Code."
            )
            assert partial["action_run"]["state"] == "partial"
            try:
                service.chat("Open Downloads.")
            except Exception as exc:
                report["downloads"] = {
                    "state": "denied",
                    "error": type(exc).__name__,
                    "note": "Current configured roots were preserved",
                }
            else:
                report["downloads"] = {
                    "state": "requested",
                    "note": "Uses the existing configured path permissions",
                }
            report["core_actions_passed"] = True
        else:
            report["core_actions_passed"] = False
            report["note"] = (
                "Discovery/UI only. Rerun explicitly with --actions for actual launches."
            )
        window._navigate(1)
        window.refresh()
        wait(lambda: not window._jobs)
        action_panel = root / "action-receipts.png"
        assert window.grab().save(str(action_panel))
        screenshots.append(str(action_panel))
        report["screenshots"] = screenshots
        report["windows"] = engine.registry.windows.health()
        report["browser"] = engine.registry.browser.health()
        report["registry"] = engine.registry.applications.health()
        report["passed"] = True
    except Exception as exc:
        report.update(passed=False, error=f"{type(exc).__name__}: {exc}")
    finally:
        window.close()
        wait(lambda: not window._jobs and not window.isVisible())
        service.emergency_stop()
        store.close()
        report["ui_ticks"] = len(ticks)
        report["maximum_ui_gap_seconds"] = round(
            max((b - a for a, b in zip(ticks, ticks[1:])), default=0), 3
        )
        (original.data_dir / "phase4-verification.json").write_text(
            json.dumps(report, indent=2), encoding="utf-8"
        )
    print(json.dumps(report, indent=2))
    return 0 if report.get("passed") else 1


if __name__ == "__main__":
    raise SystemExit(main())

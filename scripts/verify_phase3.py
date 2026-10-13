"""Exercise the actual native command center with isolated generated test data.

No microphone, private memory, ledger import, OS application launch or messaging.
Optional --live requests only the configured local Ollama model.
"""

from __future__ import annotations

import argparse
import json
import os
import time
import uuid
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from jarvis.config import Settings, load_settings
from jarvis.desktop import MainWindow
from jarvis.health import build_identity
from jarvis.providers import ProviderReply
from jarvis.service import JarvisService
from jarvis.storage import Store
from jarvis.tasks import TaskEngine


class VerificationProvider:
    name = "ollama"

    def generate(self, messages, **kwargs):
        # Keeps the interface working while a controlled background request runs.
        time.sleep(0.4)
        return ProviderReply("The verification request completed.", {})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    original = load_settings(args.data_dir)
    root = original.data_dir / ("phase3-check-" + uuid.uuid4().hex[:8])
    workspace = root / "workspace"
    workspace.mkdir(parents=True)
    settings = Settings(
        data_dir=root,
        allowed_roots=[workspace],
        model=original.model,
        ollama_url=original.ollama_url,
        wake_enabled=False,
        speech_enabled=False,
    )
    if args.live and original.provider != "ollama":
        raise RuntimeError("Live Phase 3 verification is local Ollama only")
    store = Store(root)
    engine = TaskEngine(settings, store)
    service = JarvisService(
        settings, store, engine, provider=None if args.live else VerificationProvider()
    )
    app = QApplication.instance() or QApplication([])
    window = MainWindow(service, settings, store, engine)
    window.show()
    report = {
        "build": build_identity(),
        "live_local_ai": args.live,
        "scale_factor": os.environ.get("QT_SCALE_FACTOR", "1"),
        "output_dir": str(root),
    }
    gaps = []
    last_tick = time.monotonic()
    phase = 0
    deadline = time.monotonic() + 150
    run_id = None
    screenshots = []

    def screenshot(name):
        path = root / (name + ".png")
        if not window.grab().save(str(path)):
            raise AssertionError("Native screenshot could not be saved")
        screenshots.append(str(path))

    timer = QTimer()

    def fail(error):
        report["error"] = str(error)
        finish()

    def finish():
        timer.stop()
        report["screenshots"] = screenshots
        report["ui_timer_ticks"] = len(gaps)
        report["maximum_timer_gap_seconds"] = round(max(gaps, default=0), 3)
        (args.data_dir / "phase3-verification.json").write_text(
            json.dumps(report, indent=2), encoding="utf-8"
        )
        window.close()

    def check():
        nonlocal phase, last_tick, run_id
        current = time.monotonic()
        gaps.append(current - last_tick)
        last_tick = current
        try:
            if current > deadline:
                raise TimeoutError("Phase 3 verification exceeded its deadline")
            if window._jobs:
                return
            if phase == 0:
                window._update_presence()
                assert window.core.state == "idle"
                assert not (root / "business.sqlite3").exists()
                report["honest_mic_off_core"] = True
                report["sample_business_does_not_create_ledger"] = True
                screenshot("command-center")
                window.toggle_compact()
                phase = 1
            elif phase == 1:
                assert window._compact and not window.sidebar.isVisible()
                screenshot("compact")
                window.toggle_compact()
                project = service.workflows.register_project("Verification project", str(workspace))
                service.workflows.select_project(project["id"], "verification")
                window.session_id = "verification"
                memory = store.save_memory(
                    "project", "Verification project", "Generated diagnostic reference only"
                )
                assert Store(root).memories()[0]["id"] == memory["id"]
                report["memory_restart_persistence"] = True
                routine = service.workflows.create_routine(
                    "Verified two-step routine",
                    [
                        {
                            "tool": "create_directory",
                            "arguments": {"path": str(workspace / "created")},
                        },
                        {
                            "tool": "list_directory",
                            "arguments": {"path": str(workspace / "created")},
                        },
                    ],
                )
                service.workflows.set_enabled(routine["id"], True)
                run = service.workflows.start(routine["id"], session_id="verification")
                assert run["state"] == "awaiting_approval" and not (workspace / "created").exists()
                run_id = run["id"]
                window.refresh()
                window._navigate(1)
                phase = 2
            elif phase == 2:
                screenshot("approval-center")
                run = service.workflows.get_run(run_id)
                assert any(
                    task["id"] == run["task_id"] and task["state"] == "awaiting_approval"
                    for task in window._tasks
                )
                engine.approve(run["task_id"])
                run = service.workflows.resume(run_id)
                assert run["state"] == "completed" and len(run["results"]) == 2
                assert all(item["verified"] for item in run["results"])
                assert (workspace / "created").is_dir()
                report["approval_safeguard"] = True
                report["multi_step_workflow_verified"] = True
                window.refresh()
                window._navigate(5)
                phase = 3
            elif phase == 3:
                window.workflow_table.selectRow(0)
                screenshot("workflow-replay")
                window.core.set_reduce_motion(True)
                assert not window.core.timer.isActive()
                window.core.set_reduce_motion(False)
                report["reduced_motion"] = True
                window._navigate(0)
                window.composer.setPlainText(
                    "Reply with one short sentence identifying yourself as JARVIS. /no_think"
                )
                assert window.send_message()
                phase = 4
            elif phase == 4:
                assert window._last_reply.get("text")
                report["text_response"] = True
                report["last_reply_latency_seconds"] = window._last_latency
                window._navigate(6)
                window.refresh_system(force=True)
                phase = 5
            elif phase == 5:
                assert window._awareness_data.get("system")
                window.refresh_system(force=True)
                phase = 6
            elif phase == 6:
                report["system_measurements"] = window._awareness_data["system"]
                assert not window._awareness_data["desktop"]["consent_granted"]
                screenshot("system-health")
                report["passed"] = True
                finish()
                phase = 7
        except Exception as exc:
            fail(exc)
            phase = 7

    timer.timeout.connect(check)
    timer.start(40)
    app.exec()
    service.emergency_stop()
    print(json.dumps(report, indent=2))
    return 0 if report.get("passed") else 1


if __name__ == "__main__":
    raise SystemExit(main())

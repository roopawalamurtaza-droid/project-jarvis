"""Explicit actual local executors, isolated generic data; no microphone/cloud.

--actions authorizes creating the generic diagnostic note through native Notepad.
--browser additionally opens an isolated visible browser, public sites and a
Google search. CAPTCHA is a blocked gate, not a test pass.
"""

from __future__ import annotations

import argparse
import json
import uuid
from pathlib import Path

from jarvis.config import load_settings
from jarvis.health import build_identity
from jarvis.service import JarvisService
from jarvis.storage import Store
from jarvis.tasks import TaskEngine


class NoProvider:
    name = "ollama"

    def generate(self, *args, **kwargs):
        raise AssertionError("Explicit diagnostic commands must use the local executor")


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--actions", action="store_true")
    parser.add_argument("--browser", action="store_true")
    args = parser.parse_args(argv)
    original = load_settings(args.data_dir)
    root = original.data_dir / ("phase5-check-" + uuid.uuid4().hex[:8])
    workspace = root / "workspace"
    workspace.mkdir(parents=True)
    settings = original.model_copy(deep=True)
    settings.data_dir = root
    settings.allowed_roots = [workspace]
    settings.wake_enabled = settings.speech_enabled = settings.save_history = False
    settings.computer_use_enabled = settings.browser_automation_enabled = True
    settings.desktop_actions_enabled = settings.browser_enabled = True
    settings.default_browser = "chrome"
    settings.provider = "ollama"
    settings.model_action_planning = False
    store = Store(root)
    engine = TaskEngine(settings, store)
    service = JarvisService(settings, store, engine, provider=NoProvider())
    report = {
        "build": build_identity(),
        "evidence": "Actual local executor; generic diagnostic data; no microphone/cloud",
        "actions_authorized": args.actions,
        "browser_authorized": args.browser,
        "commands": [],
        "gates": {"notepad": "not_tested", "search_open": "not_tested"},
    }

    def request(message, *, approve_note=False):
        reply = service.chat(message, "phase5-diagnostic")
        task = reply.get("task")
        if approve_note and task and task["state"] == "awaiting_approval":
            preview = service.approval_preview(task["id"])
            assert preview["arguments"]["path"] == str(workspace / "jarvis-test.txt")
            assert preview["arguments"]["text"] == "Testing JARVIS automation"
            task = engine.approve(task["id"])
            service.actions.resume_for_task(task["id"])
        report["commands"].append({"request": message, "task": task, "text": reply.get("text")})
        return task

    code = 0
    try:
        if args.actions:
            note = request(
                f"Open Notepad, write a short note saying 'Testing JARVIS automation', and save it to '{workspace / 'jarvis-test.txt'}'.",
                approve_note=True,
            )
            assert note and note["state"] == "completed", "Actual Notepad note was not verified"
            assert (workspace / "jarvis-test.txt").read_text(
                encoding="utf-8-sig"
            ) == "Testing JARVIS automation"
            report["gates"]["notepad"] = "passed_actual_ui_and_file_bytes"
        if args.browser:
            for tool, arguments in (
                ("browser_navigate", {"url": "https://www.python.org/", "browser": "chrome"}),
                ("browser_scroll", {"direction": "down"}),
                ("browser_new_tab", {"url": "https://github.com/", "browser": "chrome"}),
                ("browser_tabs", {}),
            ):
                task = engine.submit(tool, arguments)
                if task["state"] == "awaiting_approval":
                    task = engine.approve(task["id"])
                report["commands"].append({"tool": tool, "task": task})
                assert task["state"] == "completed", "Actual browser control was not verified"
            task = request(
                "Open Chrome, search for the official Python website and open the result."
            )
            if task and task["state"] == "completed":
                report["gates"]["search_open"] = "passed_actual_search_and_page"
            elif task and (task.get("result") or {}).get("user_interaction_required"):
                report["gates"]["search_open"] = "blocked_by_website_human_challenge"
                code = 2
            else:
                report["gates"]["search_open"] = "failed"
                code = 1
    except Exception as exc:
        report["error"] = str(exc)[:300]
        code = 1
    finally:
        report["computer_status"] = service.computer_status()
        service.emergency_stop()
        browser = engine.registry._computer_browser
        if browser is not None:
            browser.close()
        report_path = original.data_dir / "phase5-computer-verification.json"
        report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(
            json.dumps(
                {"report": str(report_path), "gates": report["gates"], "error": report.get("error")}
            )
        )
    return code


if __name__ == "__main__":
    raise SystemExit(main())

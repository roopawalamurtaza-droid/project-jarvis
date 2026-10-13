"""Persistent serial action receipts using the existing one-use TaskEngine.

Plans come only from explicit human commands or reviewed structured model calls.
An approval resumes only its own plan. Restart cancels, rather than replays, work.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from copy import deepcopy

from .storage import now

MAX_ACTIONS = 6
ACTIVE = {"running", "awaiting_approval"}
ALLOWED_ACTIONS = {
    "open_app",
    "focus_app",
    "open_website",
    "search_web",
    "list_applications",
    "get_system_status",
}


class ActionDispatcher:
    def __init__(self, settings, store, engine):
        self.settings, self.store, self.engine = settings, store, engine
        self._lock = threading.RLock()
        self._contexts = {}
        self._signals = {}
        self._cancel_events = {}
        with self._connect() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS action_runs (id TEXT PRIMARY KEY, data TEXT NOT NULL, updated_at TEXT NOT NULL)"
            )
        for run in self.history(256):
            if run["state"] in ACTIVE:
                for step in run["steps"]:
                    if step["state"] in {"queued", "awaiting_approval", "running"}:
                        step.update(state="cancelled", error="Interrupted; explicitly resubmit.")
                run.update(state="cancelled")
                self._save(run)

    @contextmanager
    def _connect(self):
        db = sqlite3.connect(self.store.path, timeout=5)
        try:
            with db:
                yield db
        finally:
            db.close()

    def _save(self, run):
        run["updated_at"] = now()
        with self._connect() as db:
            db.execute(
                "INSERT INTO action_runs VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data,updated_at=excluded.updated_at",
                (run["id"], json.dumps(run), run["updated_at"]),
            )
            db.execute(
                "DELETE FROM action_runs WHERE id NOT IN (SELECT id FROM action_runs ORDER BY CASE WHEN json_extract(data,'$.state') IN ('running','awaiting_approval') THEN 0 ELSE 1 END, updated_at DESC LIMIT 256)"
            )
        self.store.audit("action_plan_state", {"run_id": run["id"], "state": run["state"]})

    def history(self, limit=100):
        limit = max(1, min(int(limit), 256))
        with self._connect() as db:
            return [
                json.loads(row[0])
                for row in db.execute(
                    "SELECT data FROM action_runs ORDER BY updated_at DESC LIMIT ?", (limit,)
                )
            ]

    def context(self, session_id):
        with self._lock:
            return deepcopy(self._contexts.get(session_id, {}))

    def start(
        self,
        steps,
        *,
        session_id,
        cancel=None,
        require_approval=False,
        name="Requested desktop actions",
    ):
        if not isinstance(steps, list) or not 1 <= len(steps) <= MAX_ACTIONS:
            raise ValueError("Use between one and six actions.")
        validated = []
        for index, step in enumerate(steps):
            if not isinstance(step, dict) or set(step) - {
                "tool",
                "arguments",
                "label",
                "depends_on",
            }:
                raise ValueError("Invalid action step.")
            tool = step.get("tool")
            if tool not in ALLOWED_ACTIONS:
                raise PermissionError("This action planner cannot execute that tool.")
            args = self.engine.registry.validate(tool, step.get("arguments"))
            dependencies = step.get("depends_on", [])
            if not isinstance(dependencies, list) or any(
                type(n) is not int or not 0 <= n < index for n in dependencies
            ):
                raise ValueError("Actions may depend only on earlier steps.")
            validated.append(
                {
                    "tool": tool,
                    "arguments": args,
                    "label": str(step.get("label", tool))[:120],
                    "depends_on": sorted(set(dependencies)),
                    "state": "queued",
                    "task_id": None,
                    "result": None,
                    "error": None,
                }
            )
        if type(require_approval) is not bool:
            raise ValueError("Approval must be a boolean.")
        with self._lock:
            if sum(run["state"] in ACTIVE for run in self.history(256)) >= 32:
                raise RuntimeError(
                    "Finish or cancel a pending action plan; at most 32 may remain active."
                )
            run = {
                "id": str(uuid.uuid4()),
                "name": str(name)[:120],
                "session_id": session_id,
                "steps": validated,
                "state": "running",
                "step_index": 0,
                "require_approval": require_approval,
                "created_at": now(),
            }
            self._signals[run["id"]] = cancel
            self._cancel_events[run["id"]] = threading.Event()
            self._save(run)
            return self._continue(run)

    def _continue(self, run):
        for index in range(run["step_index"], len(run["steps"])):
            step = run["steps"][index]
            signal = self._signals.get(run["id"])
            cancelled = self._cancel_events.get(run["id"])
            if (
                run["state"] == "cancelled"
                or (cancelled is not None and cancelled.is_set())
                or (signal is not None and signal.is_set())
            ):
                self._cancel_remaining(run)
                return deepcopy(run)
            if any(run["steps"][n]["state"] != "completed" for n in step["depends_on"]):
                step.update(state="skipped", error="A required earlier action did not complete.")
                run["step_index"] = index + 1
                self._save(run)
                continue
            try:
                if step["task_id"]:
                    task = self.store.get_task(step["task_id"])
                    if task is None:
                        raise RuntimeError("Action receipt is unavailable.")
                else:
                    step["state"] = "running"
                    self._save(run)
                    task = self.engine.submit(
                        step["tool"], step["arguments"], require_approval=run["require_approval"]
                    )
                    step["task_id"] = task["id"]
                step.update(
                    state=task["state"],
                    result=task.get("result"),
                    error=task.get("error"),
                    outcome=task.get("outcome"),
                    duration_seconds=task.get("duration_seconds"),
                )
            except (ValueError, PermissionError, RuntimeError) as exc:
                step.update(
                    state="failed",
                    error=f"{type(exc).__name__}: {exc}",
                    outcome="permission_denied"
                    if isinstance(exc, PermissionError)
                    else "invalid_request",
                )
            if step["state"] == "awaiting_approval":
                run.update(state="awaiting_approval", step_index=index)
                self._save(run)
                return deepcopy(run)
            if step["state"] == "cancelled":
                self._cancel_remaining(run)
                return deepcopy(run)
            run["step_index"] = index + 1
            run["state"] = "running"
            self._update_context(run, step)
            self._save(run)
        states = [step["state"] for step in run["steps"]]
        run["state"] = (
            "completed"
            if all(s == "completed" for s in states)
            else "partial"
            if "completed" in states
            else "failed"
        )
        self._signals.pop(run["id"], None)
        self._cancel_events.pop(run["id"], None)
        self._save(run)
        return deepcopy(run)

    def _update_context(self, run, step):
        if step["state"] != "completed":
            return
        context = self._contexts.setdefault(run["session_id"], {})
        if step["tool"] in {"open_app", "focus_app"}:
            app = step["arguments"]["app"]
            applications = context.setdefault("applications", [])
            if app not in applications:
                applications.append(app)
                del applications[:-24]
            if app in {"chrome", "edge", "firefox"}:
                context["browser"] = app
        elif step["tool"] in {"open_website", "search_web"}:
            context["browser"] = step["arguments"].get("browser", self.settings.default_browser)
        while len(self._contexts) > 128:
            del self._contexts[next(iter(self._contexts))]

    def resume_for_task(self, task_id):
        with self._lock:
            for run in self.history(256):
                if (
                    run["state"] == "awaiting_approval"
                    and run["steps"][run["step_index"]]["task_id"] == task_id
                ):
                    run["state"] = "running"
                    return self._continue(run)
        return None

    def _cancel_remaining(self, run):
        for step in run["steps"][run["step_index"] :]:
            if step.get("task_id") and step["state"] == "awaiting_approval":
                self.engine.cancel(step["task_id"])
            if step["state"] not in {"completed", "failed", "skipped", "cancelled"}:
                step.update(state="cancelled", error="Cancelled at the next safe boundary.")
        run["state"] = "cancelled"
        self._signals.pop(run["id"], None)
        self._cancel_events.pop(run["id"], None)
        self._save(run)

    def cancel(self, run_id):
        event = self._cancel_events.get(run_id)
        if event is not None:
            event.set()  # revoke subsequent steps without waiting for current tool
        with self._lock:
            run = next((r for r in self.history(256) if r["id"] == run_id), None)
            if run is None:
                raise ValueError("Unknown action plan.")
            if run["state"] in ACTIVE:
                self._cancel_remaining(run)
            return deepcopy(run)

    def emergency_stop(self):
        # TaskEngine's immediate stop event revokes new submissions before this lock.
        for event in list(self._cancel_events.values()):
            event.set()
        with self._lock:
            for run in self.history(256):
                if run["state"] in ACTIVE:
                    self._cancel_remaining(run)

    def forget_session(self, session_id):
        with self._lock:
            self._contexts.pop(session_id, None)


def action_summary(run):
    """Produce speech from actual receipts, never provider-generated success."""
    phrases = []
    for step in run["steps"]:
        tool, args, result = step["tool"], step["arguments"], step.get("result") or {}
        if step["state"] == "awaiting_approval":
            phrases.append("This action needs your approval. Review Mission Control.")
        elif step["state"] in {"failed", "skipped", "cancelled"}:
            detail = (
                result.get("detail")
                if step.get("outcome") == "unable_to_verify"
                else step.get("error")
            )
            phrases.append(
                f"{step['label']}: {step['state']}. {detail or 'Review Mission Control.'}"
            )
        elif step["state"] == "completed":
            if tool in {"open_app", "focus_app"}:
                label = result.get("app", args["app"])
                if result.get("focus_verified"):
                    phrases.append(f"{label} is focused.")
                elif result.get("window_verified"):
                    phrases.append(f"{label} is open.")
                else:
                    phrases.append(
                        f"Windows accepted the {label} launch request; its window was not verified."
                    )
            elif tool in {"open_website", "search_web"}:
                phrases.append(
                    "Sent the search to your browser; the page was not inspected."
                    if tool == "search_web"
                    else "Sent the website to your browser; the page was not inspected."
                )
            elif tool == "list_applications":
                names = [a["name"] for a in result.get("applications", []) if a.get("enabled")]
                phrases.append(
                    "Enabled applications: " + ", ".join(names[:25]) + "."
                    if names
                    else "No enabled application is available in the library."
                )
            elif tool == "get_system_status":
                system = result.get("system", {})
                cpu, ram = system.get("cpu_percent"), system.get("memory_percent")
                phrases.append(
                    f"CPU: {cpu if cpu is not None else 'awaiting a second sample'} percent. RAM: {ram if ram is not None else 'unavailable'} percent."
                )
    return " ".join(phrases) or "No action completed."

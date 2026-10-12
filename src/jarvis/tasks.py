"""Bounded, serial tool execution with one-use approvals and emergency stop."""

from __future__ import annotations

import threading
import time
import uuid
from copy import deepcopy

from jarvis.storage import now
from jarvis.tools import READ_ONLY, SCHEMAS, SENSITIVE, ToolRegistry


class TaskEngine:
    def __init__(self, settings, store):
        self.settings, self.store = settings, store
        self.registry = ToolRegistry(settings)
        self._lock = threading.RLock()
        self._stopped = threading.Event()
        self._pending: dict[str, tuple[dict, float]] = {}
        # Authorizations do not survive an interrupted process or restart.
        for task in store.tasks():
            if task["state"] in {"queued", "planning", "awaiting_approval", "running", "verifying"}:
                task.update(
                    state="cancelled", error="Interrupted before completion; resubmit to authorize"
                )
                self._save(task)

    def _save(self, task):
        task["updated_at"] = now()
        self.store.put_task(task)
        self.store.audit(
            "task_state", {"task_id": task["id"], "tool": task["tool"], "state": task["state"]}
        )

    def submit(self, tool, arguments):
        with self._lock:
            if self._stopped.is_set():
                raise RuntimeError("Emergency stop active; explicitly resume before new actions")
            try:
                validated = self.registry.validate(tool, arguments)
            except (ValueError, PermissionError) as exc:
                self.store.audit(
                    "tool_denied",
                    {
                        "tool": tool if tool in SCHEMAS else "unknown",
                        "reason": type(exc).__name__,
                    },
                )
                raise
            task = {
                "id": str(uuid.uuid4()),
                "tool": tool,
                "arguments": validated,
                "state": "queued",
                "result": None,
                "error": None,
                "created_at": now(),
            }
            self._save(task)
            requires_approval = tool in SENSITIVE or (
                self.settings.mode == "manual" and tool not in READ_ONLY
            )
            if requires_approval:
                task["state"] = "awaiting_approval"
                self._pending[task["id"]] = (deepcopy(task), time.monotonic())
                self._save(task)
                return task
            return self._execute(task)

    def _execute(self, task):
        if self._stopped.is_set():
            task.update(state="cancelled", error="Emergency stop active")
            self._save(task)
            return task
        try:
            task["state"] = "running"
            self._save(task)
            result = self.registry.execute(task["tool"], task["arguments"])
            task["state"] = "verifying"
            self._save(task)
            if not result.get("verified"):
                raise RuntimeError("Tool did not verify its result")
            task.update(state="completed", result=result)
        except Exception as exc:
            # These are locally generated validation/OS exceptions, never provider response bodies.
            task.update(state="failed", error=f"{type(exc).__name__}: {exc}")
        self._save(task)
        return task

    def approve(self, task_id):
        with self._lock:
            if self._stopped.is_set():
                raise RuntimeError("Emergency stop active")
            pending = self._pending.pop(task_id, None)
            if pending is None:
                raise ValueError("No pending approval; approvals cannot be replayed")
            task, created = pending
            if time.monotonic() - created > 600:
                task.update(state="cancelled", error="Approval expired after 10 minutes")
                self._save(task)
                return task
            self.store.audit("approval_granted", {"task_id": task_id})
            return self._execute(task)

    def reject(self, task_id):
        return self.cancel(task_id)

    def cancel(self, task_id):
        with self._lock:
            pending = self._pending.pop(task_id, None)
            task = pending[0] if pending else self.store.get_task(task_id)
            if task is None:
                raise ValueError("Unknown task")
            if task["state"] in {"completed", "failed", "cancelled"}:
                return task
            task.update(state="cancelled", error="Cancelled by user")
            self._save(task)
            return task

    def emergency_stop(self):
        self._stopped.set()  # immediately revoke future execution, even while another thread is running
        with self._lock:
            for identity in list(self._pending):
                self.cancel(identity)
            self.store.audit("emergency_stop", {})

    def reset_stop(self):
        with self._lock:
            self._stopped.clear()
            self.store.audit("emergency_stop_reset", {})

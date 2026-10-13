"""Explicit saved routines built from the existing permission-controlled tools.

Routine definitions and verified task references are local data. They are never
provider instructions, executable scripts, or permission grants. Every step is
submitted through TaskEngine and receives its normal, one-use authorization.
"""

from __future__ import annotations

import json
import re
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path

from jarvis.storage import now

MAX_STEPS = 12
MAX_ROUTINES = 100
MAX_PROJECTS = 100
MAX_RUNS = 500
MAX_CONTEXTS = 128
ACTIVE_STATES = {"queued", "running", "awaiting_approval"}
TERMINAL_STATES = {"completed", "failed", "cancelled"}


class WorkflowEngine:
    """Run a user-inspected routine serially; pause at each normal approval.

    ``start`` and ``resume`` perform synchronous, bounded local tool operations;
    desktop callers should use their existing background worker. ``cancel`` is
    independently interruptible between operations. An OS operation already
    accepted cannot be rolled back by cancelling its routine.
    """

    def __init__(self, store, tasks, settings):
        self.store, self.tasks, self.settings = store, tasks, settings
        self._lock = threading.RLock()
        self._execution = threading.Lock()
        self._cancelled: dict[str, threading.Event] = {}
        self._contexts: dict[str, dict] = {}
        with self._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS workflow_routines (
                  id TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE COLLATE NOCASE,
                  data TEXT NOT NULL, updated_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS workflow_runs (
                  id TEXT PRIMARY KEY, data TEXT NOT NULL, updated_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS workflow_projects (
                  id TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE COLLATE NOCASE,
                  data TEXT NOT NULL, updated_at TEXT NOT NULL);
            """)
        # Restart never grants permission to replay an interrupted routine.
        for run in self.runs():
            if run["state"] in ACTIVE_STATES:
                task_id = run.get("task_id")
                if task_id:
                    task = self.store.get_task(task_id)
                    if task and task["state"] in ACTIVE_STATES:
                        self.tasks.cancel(task_id)
                run.update(
                    state="cancelled",
                    error="Interrupted before completion; explicitly start a new run.",
                )
                self._save_run(run)

    @contextmanager
    def _connect(self):
        db = sqlite3.connect(self.store.path, timeout=5)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def _text(value, field, limit, *, empty=False):
        if not isinstance(value, str) or len(value) > limit:
            raise ValueError(f"{field} must be text of up to {limit} characters")
        value = value.strip()
        if not empty and not value:
            raise ValueError(f"{field} cannot be empty")
        if any(ord(character) < 32 and character not in "\n\t" for character in value):
            raise ValueError(f"{field} contains unsupported control characters")
        return value

    @staticmethod
    def _session_id(value):
        if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", value):
            raise ValueError("Invalid workflow session identifier")
        return value

    def _steps(self, steps):
        if not isinstance(steps, list) or not 1 <= len(steps) <= MAX_STEPS:
            raise ValueError(f"A routine needs between 1 and {MAX_STEPS} steps")
        validated = []
        for step in steps:
            if not isinstance(step, dict) or set(step) - {"tool", "arguments", "label"}:
                raise ValueError("Each step contains only tool, arguments, and an optional label")
            if not isinstance(step.get("tool"), str):
                raise ValueError("Every step needs an existing tool name")
            arguments = self.tasks.registry.validate(step["tool"], step.get("arguments"))
            validated.append(
                {
                    "tool": step["tool"],
                    "arguments": arguments,
                    "label": self._text(
                        step.get("label", step["tool"].replace("_", " ")), "Step label", 80
                    ),
                }
            )
        return validated

    def _record(self, table, identity):
        with self._connect() as db:
            row = db.execute(f"SELECT data FROM {table} WHERE id=?", (identity,)).fetchone()
            return json.loads(row[0]) if row else None

    def _named(self, table, identity_or_name):
        value = self._text(identity_or_name, "Routine or project identifier", 120)
        with self._connect() as db:
            row = db.execute(
                f"SELECT data FROM {table} WHERE id=? OR name=? COLLATE NOCASE", (value, value)
            ).fetchone()
            return json.loads(row[0]) if row else None

    def _save_definition(self, table, record):
        record["updated_at"] = now()
        try:
            with self._connect() as db:
                db.execute(
                    f"INSERT INTO {table}(id,name,data,updated_at) VALUES(?,?,?,?) "
                    "ON CONFLICT(id) DO UPDATE SET name=excluded.name,data=excluded.data,"
                    "updated_at=excluded.updated_at",
                    (record["id"], record["name"], json.dumps(record), record["updated_at"]),
                )
        except sqlite3.IntegrityError:
            raise ValueError("Choose a unique name") from None

    def _save_run(self, run):
        run["updated_at"] = now()
        with self._connect() as db:
            db.execute(
                "INSERT INTO workflow_runs VALUES(?,?,?) ON CONFLICT(id) "
                "DO UPDATE SET data=excluded.data,updated_at=excluded.updated_at",
                (run["id"], json.dumps(run), run["updated_at"]),
            )
        self.store.audit(
            "workflow_state",
            {"run_id": run["id"], "state": run["state"], "step_index": run["step_index"]},
        )

    def _definitions(self, table):
        with self._connect() as db:
            return [
                json.loads(row[0])
                for row in db.execute(f"SELECT data FROM {table} ORDER BY name COLLATE NOCASE")
            ]

    def routines(self):
        return self._definitions("workflow_routines")

    list_routines = routines

    def create_routine(self, name, steps, description=""):
        """Save a disabled definition; inspecting/enabling never executes it."""
        name = self._text(name, "Routine name", 120)
        steps = self._steps(steps)
        description = self._text(description, "Description", 1000, empty=True)
        with self._lock:
            if len(self.routines()) >= MAX_ROUTINES:
                raise ValueError("The saved routine limit was reached")
            record = {
                "id": str(uuid.uuid4()),
                "name": name,
                "description": description,
                "steps": steps,
                "enabled": False,
                "kind": "routine",
                "created_at": now(),
            }
            self._save_definition("workflow_routines", record)
            self.store.audit("routine_created", {"routine_id": record["id"]})
            return deepcopy(record)

    def update_routine(self, identity, *, name=None, steps=None, description=None):
        """Editing disables the routine and cancels its incomplete runs."""
        with self._lock:
            record = self._named("workflow_routines", identity)
            if record is None:
                raise ValueError("Unknown routine")
            if name is not None:
                record["name"] = self._text(name, "Routine name", 120)
            if steps is not None:
                record["steps"] = self._steps(steps)
            if description is not None:
                record["description"] = self._text(description, "Description", 1000, empty=True)
            record["enabled"] = False
            # An edited custom plan needs an explicit named run, not a generic
            # development-intent shortcut authorized for the generated template.
            record["kind"] = "routine"
            record.pop("project_id", None)
            self._save_definition("workflow_routines", record)
            self._cancel_routine(record["id"])
            self.store.audit("routine_updated", {"routine_id": record["id"]})
            return deepcopy(record)

    def set_enabled(self, identity, enabled):
        if type(enabled) is not bool:
            raise ValueError("Enabled must be true or false")
        with self._lock:
            record = self._named("workflow_routines", identity)
            if record is None:
                raise ValueError("Unknown routine")
            if enabled:
                record["steps"] = self._steps(record["steps"])
            record["enabled"] = enabled
            self._save_definition("workflow_routines", record)
            if not enabled:
                self._cancel_routine(record["id"])
            self.store.audit("routine_enabled", {"routine_id": record["id"], "enabled": enabled})
            return deepcopy(record)

    def delete_routine(self, identity):
        with self._lock:
            record = self._named("workflow_routines", identity)
            if record is None:
                raise ValueError("Unknown routine")
            self._cancel_routine(record["id"])
            with self._connect() as db:
                db.execute("DELETE FROM workflow_routines WHERE id=?", (record["id"],))
            self.store.audit("routine_deleted", {"routine_id": record["id"]})

    def register_project(self, name, path):
        """Register only an existing folder inside the current approved roots."""
        name = self._text(name, "Project name", 120)
        arguments = self.tasks.registry.validate("open_folder", {"path": path})
        if not Path(arguments["path"]).is_dir():
            raise ValueError("Select an existing project folder")
        with self._lock:
            existing = self._named("workflow_projects", name)
            if existing is None and len(self.projects()) >= MAX_PROJECTS:
                raise ValueError("The saved project limit was reached")
            record = {
                "id": existing["id"] if existing else str(uuid.uuid4()),
                "name": name,
                "path": arguments["path"],
                "created_at": existing["created_at"] if existing else now(),
            }
            self._save_definition("workflow_projects", record)
            self.store.audit("project_registered", {"project_id": record["id"]})
            return deepcopy(record)

    def projects(self):
        return self._definitions("workflow_projects")

    def delete_project(self, identity):
        with self._lock:
            project = self._named("workflow_projects", identity)
            if project is None:
                raise ValueError("Unknown project")
            with self._connect() as db:
                db.execute("DELETE FROM workflow_projects WHERE id=?", (project["id"],))
            for context in self._contexts.values():
                if context.get("project", {}).get("id") == project["id"]:
                    context.pop("project", None)
            self.store.audit("project_deleted", {"project_id": project["id"]})

    def _context(self, session_id):
        session_id = self._session_id(session_id)
        if session_id not in self._contexts:
            if len(self._contexts) >= MAX_CONTEXTS:
                del self._contexts[next(iter(self._contexts))]
            self._contexts[session_id] = {"session_id": session_id}
        return self._contexts[session_id]

    def select_project(self, identity, session_id="default"):
        with self._lock:
            project = self._named("workflow_projects", identity)
            if project is None:
                raise ValueError("Unknown project")
            arguments = self.tasks.registry.validate("open_folder", {"path": project["path"]})
            if not Path(arguments["path"]).is_dir():
                raise ValueError("Project folder unavailable")
            context = self._context(session_id)
            context["project"] = project
            return deepcopy(context)

    def session_context(self, session_id="default"):
        with self._lock:
            context = deepcopy(self._context(session_id))
            if "project" in context:
                # A settings change or folder removal revokes an old reference.
                project = self._named("workflow_projects", context["project"]["id"])
                try:
                    if project is None:
                        raise ValueError("Project removed")
                    arguments = self.tasks.registry.validate(
                        "open_folder", {"path": project["path"]}
                    )
                    if not Path(arguments["path"]).is_dir():
                        raise ValueError("Project folder unavailable")
                    context["project"] = project
                except (PermissionError, ValueError):
                    context.pop("project", None)
                    context["project_unavailable"] = True
            return context

    def create_development_routine(self, project_id, name=None):
        project = self._named("workflow_projects", project_id)
        if project is None:
            raise ValueError("Unknown project")
        routine = self.create_routine(
            name or f"Development: {project['name']}",
            [
                {
                    "tool": "open_folder",
                    "arguments": {"path": project["path"]},
                    "label": "Open project folder",
                },
                {"tool": "open_app", "arguments": {"app": "vscode"}, "label": "Launch VS Code"},
            ],
            "Open the approved project in Explorer and launch VS Code. Project loading inside VS Code is not verified.",
        )
        routine.update(kind="development", project_id=project["id"])
        self._save_definition("workflow_routines", routine)
        return routine

    def start(self, identity, session_id="default", cancel=None):
        session_id = self._session_id(session_id)
        with self._lock:
            routine = self._named("workflow_routines", identity)
            if routine is None:
                raise ValueError("Unknown routine")
            if not routine["enabled"]:
                raise PermissionError("Inspect and enable this routine before running it")
            if any(run["state"] in ACTIVE_STATES for run in self.runs()):
                raise RuntimeError("Finish or cancel the active routine first")
            # Validate the entire plan before any side effect; validate again per step.
            steps = self._steps(routine["steps"])
            if routine.get("kind") == "development":
                project = self._named("workflow_projects", routine.get("project_id", ""))
                if project is None or steps[0]["arguments"].get("path") != project["path"]:
                    raise ValueError(
                        "This development routine no longer matches its registered project; recreate it"
                    )
            # This is the exact installed-path resolver used by actual launch;
            # probes never start a process or claim a loaded project/window.
            for step in steps:
                if (
                    step["tool"] == "open_app"
                    and self.tasks.registry.application_path(step["arguments"]["app"]) is None
                ):
                    raise ValueError(
                        f"{step['arguments']['app']} is not installed at a supported location; no routine steps ran"
                    )
            run = {
                "id": str(uuid.uuid4()),
                "routine_id": routine["id"],
                "name": routine["name"],
                "session_id": session_id,
                "steps": steps,
                "state": "queued",
                "step_index": 0,
                "task_id": None,
                "results": [],
                "error": None,
                "created_at": now(),
            }
            self._cancelled[run["id"]] = threading.Event()
            self._save_run(run)
            self._context(session_id)["last_workflow_id"] = run["id"]
            self._trim_runs()
        return self._advance(run["id"], cancel=cancel)

    def get_run(self, identity):
        run = self._record("workflow_runs", identity)
        if run is None:
            raise ValueError("Unknown routine run")
        return run

    def runs(self, limit=MAX_RUNS):
        with self._connect() as db:
            return [
                json.loads(row[0])
                for row in db.execute(
                    "SELECT data FROM workflow_runs ORDER BY updated_at DESC LIMIT ?",
                    (min(max(int(limit), 1), MAX_RUNS),),
                )
            ]

    @staticmethod
    def _task_result(task, index):
        result = task.get("result") or {}
        # Do not persist file contents, directory listings, or arbitrary tool output twice.
        return {
            "step_index": index,
            "task_id": task["id"],
            "tool": task["tool"],
            "state": task["state"],
            "verified": result.get("verified") is True and task["state"] == "completed",
            "evidence": str(result.get("evidence", ""))[:120],
            "error": str(task.get("error") or "")[:500],
        }

    def _advance(self, identity, cancel=None):
        with self._execution:
            while True:
                if cancel is not None and cancel.is_set():
                    return self.cancel(identity)
                with self._lock:
                    run = self.get_run(identity)
                    if run["state"] in TERMINAL_STATES:
                        self._cancelled.pop(identity, None)
                        return run
                    if run["state"] == "awaiting_approval":
                        task = self.store.get_task(run["task_id"])
                        if task is None:
                            run.update(state="failed", error="The pending task is unavailable")
                            self._save_run(run)
                            continue
                        if task["state"] == "awaiting_approval":
                            return run
                        self._accept_task(run, task)
                        continue
                    if run["step_index"] >= len(run["steps"]):
                        run.update(state="completed", task_id=None)
                        self._save_run(run)
                        continue
                    step = run["steps"][run["step_index"]]
                    cancellation = self._cancelled.get(identity)
                    run.update(state="running", task_id=None)
                    self._save_run(run)
                # Keep the cancellation lock free during an OS call.
                if cancellation is not None and cancellation.is_set():
                    continue
                if cancel is not None and cancel.is_set():
                    return self.cancel(identity)
                try:
                    task = self.tasks.submit(step["tool"], deepcopy(step["arguments"]))
                except (ValueError, PermissionError, RuntimeError) as exc:
                    with self._lock:
                        run = self.get_run(identity)
                        if run["state"] != "cancelled":
                            run.update(
                                state="failed", error=f"{type(exc).__name__}: {str(exc)[:500]}"
                            )
                            self._save_run(run)
                    continue
                with self._lock:
                    run = self.get_run(identity)
                    if cancel is not None and cancel.is_set():
                        self.cancel(identity)
                        run = self.get_run(identity)
                    if run["state"] == "cancelled":
                        if task["state"] == "awaiting_approval":
                            task = self.tasks.cancel(task["id"])
                        run["task_id"] = task["id"]
                        run["results"].append(self._task_result(task, run["step_index"]))
                        self._save_run(run)
                        continue
                    run["task_id"] = task["id"]
                    self._context(run["session_id"])["last_task_id"] = task["id"]
                    if task["state"] == "awaiting_approval":
                        run["state"] = "awaiting_approval"
                        self._save_run(run)
                        return run
                    self._accept_task(run, task)

    def _accept_task(self, run, task):
        run["results"].append(self._task_result(task, run["step_index"]))
        if task["state"] == "completed" and (task.get("result") or {}).get("verified") is True:
            run["step_index"] += 1
            run.update(state="queued", task_id=None)
        elif task["state"] == "cancelled":
            run.update(state="cancelled", error=task.get("error") or "Step cancelled")
        else:
            run.update(
                state="failed",
                error=str(task.get("error") or "Step did not verify its result")[:500],
            )
        self._save_run(run)

    def resume(self, identity, cancel=None):
        """Refresh after a normal TaskEngine approval/rejection; never approve here."""
        return self._advance(identity, cancel=cancel)

    def resume_for_task(self, task_id, cancel=None):
        for run in self.runs():
            if run["state"] == "awaiting_approval" and run.get("task_id") == task_id:
                return self.resume(run["id"], cancel=cancel)
        return None

    def cancel(self, identity):
        with self._lock:
            run = self.get_run(identity)
            if run["state"] in TERMINAL_STATES:
                return run
            event = self._cancelled.pop(identity, None)
            if event is not None:
                event.set()
            task_id = run.get("task_id")
            run.update(
                state="cancelled",
                error="Cancelled by user; accepted OS actions cannot be rolled back",
            )
            self._save_run(run)
        if task_id:
            self.tasks.cancel(task_id)
        return self.get_run(identity)

    def _cancel_routine(self, routine_id):
        for run in self.runs():
            if run["routine_id"] == routine_id and run["state"] in ACTIVE_STATES:
                self.cancel(run["id"])

    def emergency_stop(self):
        for run in self.runs():
            if run["state"] in ACTIVE_STATES:
                self.cancel(run["id"])

    def _trim_runs(self):
        with self._connect() as db:
            rows = db.execute(
                "SELECT id,data FROM workflow_runs ORDER BY updated_at DESC"
            ).fetchall()
            for row in rows[MAX_RUNS:]:
                if json.loads(row["data"])["state"] in TERMINAL_STATES:
                    db.execute("DELETE FROM workflow_runs WHERE id=?", (row["id"],))

    def prune(self, days=30):
        if type(days) is not int or not 1 <= days <= 3650:
            raise ValueError("Retention must be between 1 and 3650 days")
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        with self._lock, self._connect() as db:
            for row in db.execute(
                "SELECT id,data FROM workflow_runs WHERE updated_at < ?", (cutoff,)
            ).fetchall():
                if json.loads(row["data"])["state"] in TERMINAL_STATES:
                    db.execute("DELETE FROM workflow_runs WHERE id=?", (row["id"],))

    def export(self):
        with self._lock, self._connect() as db:
            db.execute("BEGIN")
            return {
                "schema_version": 1,
                "routines": [
                    json.loads(row[0])
                    for row in db.execute("SELECT data FROM workflow_routines ORDER BY updated_at")
                ],
                "projects": [
                    json.loads(row[0])
                    for row in db.execute("SELECT data FROM workflow_projects ORDER BY updated_at")
                ],
                "runs": [
                    json.loads(row[0])
                    for row in db.execute("SELECT data FROM workflow_runs ORDER BY updated_at")
                ],
            }

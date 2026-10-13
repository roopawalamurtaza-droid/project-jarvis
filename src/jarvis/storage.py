"""SQLite storage with short-lived connections and a versioned initial schema."""

from __future__ import annotations

import json
import re
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Store:
    def __init__(self, data_dir: Path | str):
        root = Path(data_dir)
        root.mkdir(parents=True, exist_ok=True)
        self.path = root / "jarvis.sqlite3"
        self._lock = threading.RLock()
        with self._connect() as db:
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version > 1:
                raise RuntimeError("Database was created by a newer JARVIS version")
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS messages (
                  id INTEGER PRIMARY KEY, session_id TEXT NOT NULL, role TEXT NOT NULL,
                  content TEXT NOT NULL, created_at TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS messages_session ON messages(session_id,id);
                CREATE TABLE IF NOT EXISTS memories (
                  id TEXT PRIMARY KEY, category TEXT NOT NULL, key TEXT NOT NULL,
                  content TEXT NOT NULL, source TEXT NOT NULL, updated_at TEXT NOT NULL,
                  UNIQUE(category,key));
                CREATE TABLE IF NOT EXISTS tasks (
                  id TEXT PRIMARY KEY, data TEXT NOT NULL, updated_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS audit (
                  id INTEGER PRIMARY KEY, event TEXT NOT NULL, details TEXT NOT NULL,
                  created_at TEXT NOT NULL);
                PRAGMA user_version=1;
            """)

    @contextmanager
    def _connect(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def add_message(self, session_id, role, content):
        if (
            role not in {"user", "assistant"}
            or not isinstance(content, str)
            or len(content) > 100000
        ):
            raise ValueError("Invalid conversation message")
        with self._lock, self._connect() as db:
            db.execute(
                "INSERT INTO messages(session_id,role,content,created_at) VALUES(?,?,?,?)",
                (session_id, role, content, now()),
            )

    def history(self, session_id, limit=20):
        with self._lock, self._connect() as db:
            rows = db.execute(
                "SELECT role,content FROM messages WHERE session_id=? ORDER BY id DESC LIMIT ?",
                (session_id, min(max(int(limit), 1), 200)),
            ).fetchall()
            return [dict(row) for row in reversed(rows)]

    def sessions(self):
        with self._lock, self._connect() as db:
            return [
                dict(row)
                for row in db.execute(
                    "SELECT session_id,MAX(created_at) AS updated_at,COUNT(*) AS messages FROM messages GROUP BY session_id ORDER BY updated_at DESC"
                )
            ]

    def delete_session(self, session_id):
        with self._lock, self._connect() as db:
            db.execute("DELETE FROM messages WHERE session_id=?", (session_id,))

    def memories(self, query=""):
        # Bound parameters prevent SQL injection; substring search avoids ranking overhead for MVP.
        with self._lock, self._connect() as db:
            pattern = "%" + str(query)[:500] + "%"
            return [
                dict(row)
                for row in db.execute(
                    "SELECT * FROM memories WHERE key LIKE ? OR content LIKE ? OR category LIKE ? ORDER BY updated_at DESC LIMIT 500",
                    (pattern, pattern, pattern),
                )
            ]

    def save_memory(self, category, key, content, source="user"):
        if not isinstance(source, str) or not source.strip() or len(source) > 160:
            raise ValueError("Memory source must be short nonempty text")
        if category not in {
            "preferences",
            "project",
            "business",
            "task",
            "knowledge",
            "summary",
            "application",
            "routine",
            "instructions",
        }:
            raise ValueError("Choose a supported memory category")
        if not key.strip() or len(key) > 200 or not content.strip() or len(content) > 20000:
            raise ValueError("Memory needs a key (up to 200 characters) and content (up to 20000)")
        with self._lock, self._connect() as db:
            existing = db.execute(
                "SELECT id FROM memories WHERE category=? AND key=?", (category, key)
            ).fetchone()
            identity = existing[0] if existing else str(uuid.uuid4())
            record = dict(
                id=identity,
                category=category,
                key=key,
                content=content,
                source=source,
                updated_at=now(),
            )
            db.execute(
                "INSERT INTO memories VALUES(:id,:category,:key,:content,:source,:updated_at) ON CONFLICT(category,key) DO UPDATE SET content=excluded.content,source=excluded.source,updated_at=excluded.updated_at",
                record,
            )
            return record

    def delete_memory(self, identity):
        with self._lock, self._connect() as db:
            db.execute("DELETE FROM memories WHERE id=?", (identity,))

    def relevant_memories(self, query="", limit=10):
        """Rank explicit references by token matches, then recency; no invented relationships."""
        tokens = set(re.findall(r"\w{3,}", str(query).lower()[:500]))
        ignored = {"the", "what", "that", "this", "please", "jarvis", "about", "with", "remember"}
        tokens -= ignored
        records = []
        if tokens:
            selected = sorted(tokens)[:20]
            clauses = " OR ".join("lower(key) LIKE ? OR lower(content) LIKE ?" for _ in selected)
            parameters = [
                pattern
                for token in selected
                for pattern in ("%" + token.replace("%", "").replace("_", "") + "%",) * 2
            ]
            with self._lock, self._connect() as db:
                records = [
                    dict(row)
                    for row in db.execute(
                        "SELECT * FROM memories WHERE "
                        + clauses
                        + " ORDER BY updated_at DESC LIMIT 500",
                        parameters,
                    )
                ]
        if not records:
            records = self.memories()

        def score(item):
            key = set(re.findall(r"\w+", item["key"].lower()))
            body = set(re.findall(r"\w+", item["content"].lower()))
            return len(tokens & key) * 3 + len(tokens & body)

        # Stable ordering keeps the existing recent-first order for equal relevance.
        records.sort(key=score, reverse=True)
        if tokens and any(score(item) for item in records):
            records = [item for item in records if score(item)]
        return records[: min(max(int(limit), 1), 30)]

    def prune_memories(self, days):
        """Explicit user-triggered retention; normal startup never deletes saved memory."""
        days = int(days)
        if not 1 <= days <= 3650:
            raise ValueError("Choose 1 to 3650 days")
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        with self._lock, self._connect() as db:
            result = db.execute("DELETE FROM memories WHERE updated_at < ?", (cutoff,))
            return result.rowcount

    def put_task(self, task):
        record = dict(task)
        # A file read is permission to view, not to persist the file in task history.
        if record.get("tool") == "read_file" and isinstance(record.get("result"), dict):
            record["result"] = {k: v for k, v in record["result"].items() if k != "content"}
        with self._lock, self._connect() as db:
            db.execute(
                "INSERT INTO tasks VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data,updated_at=excluded.updated_at",
                (record["id"], json.dumps(record), now()),
            )

    def tasks(self):
        with self._lock, self._connect() as db:
            return [
                json.loads(row[0])
                for row in db.execute("SELECT data FROM tasks ORDER BY updated_at DESC LIMIT 500")
            ]

    def get_task(self, identity):
        with self._lock, self._connect() as db:
            row = db.execute("SELECT data FROM tasks WHERE id=?", (identity,)).fetchone()
            return json.loads(row[0]) if row else None

    def audit(self, event, details):
        with self._lock, self._connect() as db:
            db.execute(
                "INSERT INTO audit(event,details,created_at) VALUES(?,?,?)",
                (event, json.dumps(details), now()),
            )

    def audits(self, limit=100):
        with self._lock, self._connect() as db:
            rows = db.execute(
                "SELECT * FROM audit ORDER BY id DESC LIMIT ?", (min(max(int(limit), 1), 1000),)
            )
            return [dict(row) | {"details": json.loads(row["details"])} for row in rows]

    def prune(self, days=30):
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        with self._lock, self._connect() as db:
            db.execute("DELETE FROM messages WHERE created_at < ?", (cutoff,))
            db.execute("DELETE FROM tasks WHERE updated_at < ?", (cutoff,))
            db.execute("DELETE FROM audit WHERE created_at < ?", (cutoff,))

    def export(self):
        # Explicit export is a complete snapshot, independent of UI pagination limits.
        with self._lock, self._connect() as db:
            db.execute("BEGIN")
            memories = [
                dict(row) for row in db.execute("SELECT * FROM memories ORDER BY updated_at")
            ]
            tasks = [
                json.loads(row[0])
                for row in db.execute("SELECT data FROM tasks ORDER BY updated_at")
            ]
            sessions = []
            for row in db.execute(
                "SELECT session_id,MAX(created_at) AS updated_at,COUNT(*) AS messages FROM messages GROUP BY session_id ORDER BY updated_at"
            ):
                history = [
                    dict(message)
                    for message in db.execute(
                        "SELECT role,content FROM messages WHERE session_id=? ORDER BY id",
                        (row["session_id"],),
                    )
                ]
                sessions.append({**dict(row), "history": history})
            audit = [
                dict(row) | {"details": json.loads(row["details"])}
                for row in db.execute("SELECT * FROM audit ORDER BY id")
            ]
            return {
                "schema_version": 1,
                "memories": memories,
                "tasks": tasks,
                "sessions": sessions,
                "audit": audit,
            }

    def close(self):
        # Connections are scoped to each call; nothing long-lived to release.
        pass

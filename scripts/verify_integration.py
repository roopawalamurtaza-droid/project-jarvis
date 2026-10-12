"""Explicit local-model and persistent-memory verification in isolated test data."""

import json
from pathlib import Path

from jarvis.__main__ import build_service
from jarvis.config import Settings, load_settings

root = Path(__file__).resolve().parents[1]
source_settings = load_settings(root / ".local")
data = root / ".local" / "integration-check"
workspace = data / "workspace"
workspace.mkdir(parents=True, exist_ok=True)
settings = Settings(
    data_dir=data, provider="ollama", model=source_settings.model, allowed_roots=[workspace]
)
first = build_service(settings)
first.chat("/remember preferences editor VS Code")
first.store.close()
second = build_service(settings)
reply = second.chat("What is my preferred editor? Answer briefly. /no_think")
sample = workspace / "verification.txt"
sample.write_text("This is JARVIS verification data, not a personal document.", encoding="utf-8")
listed = second.engine.submit("list_directory", {"path": str(workspace)})
read = second.engine.submit("read_file", {"path": str(sample)})
created = second.engine.submit("create_directory", {"path": str(workspace / "approved-test")})
was_pending = created["state"] == "awaiting_approval"
approved = second.engine.approve(created["id"])
report = {
    "real_memory_response": reply["text"],
    "provider": reply["provider"],
    "memory_recall_verified": "vs code" in reply["text"].lower()
    or "visual studio code" in reply["text"].lower(),
    "list_state": listed["state"],
    "read_state": read["state"],
    "creation_required_approval": was_pending,
    "approved_state": approved["state"],
    "read_content_not_persisted": "content" not in second.store.get_task(read["id"])["result"],
}
(root / ".local" / "integration-verification.json").write_text(
    json.dumps(report, indent=2), encoding="utf-8"
)
second.emergency_stop()
second.store.close()
print(json.dumps(report, indent=2))
if not report["memory_recall_verified"] or not all(
    task["state"] == "completed" for task in (listed, read, approved)
):
    raise SystemExit(1)

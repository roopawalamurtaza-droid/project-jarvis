import importlib.util
import json
import subprocess
import zipfile
from pathlib import Path

import pytest

from jarvis.config import Settings
from jarvis.conversation import route_voice_command
from jarvis.health import build_identity, startup_health


def test_health_identifies_source_without_recording(tmp_path):
    identity = build_identity()
    assert identity["version"] == "0.3.0"
    assert identity["git_commit"]
    assert identity["executable"]
    report = startup_health(Settings(data_dir=tmp_path))
    assert report["wake_permission"] is False
    assert report["microphone"].startswith("Off")
    assert report["backend"].startswith("Select")
    assert "missing" in report["speech_model"]


def test_compound_sleep_is_exact_and_contextual_thanks_continues():
    assert route_voice_command("Thanks, Jarvis. Go to sleep.") == "end"
    assert route_voice_command("Thanks, Jarvis, go to sleep after opening Chrome") is None


def test_handoff_archive_retains_history_and_excludes_runtime_data(tmp_path):
    specification = importlib.util.spec_from_file_location(
        "handoff_export", Path(__file__).resolve().parents[1] / "scripts/export_handoff.py"
    )
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)

    def git(*args):
        return subprocess.run(
            ["git", *args], cwd=tmp_path, check=True, capture_output=True, text=True
        ).stdout.strip()

    git("init", "-b", "feature/handsfree-voice")
    (tmp_path / ".gitignore").write_text(".local/\ntransfer/\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("Committed source", encoding="utf-8")
    git("add", ".gitignore", "README.md")
    git("-c", "user.name=Test", "-c", "user.email=test@localhost", "commit", "-m", "test")
    local = tmp_path / ".local"
    local.mkdir()
    (local / "secrets.dpapi.json").write_text("private exclusion fixture", encoding="utf-8")
    archive_path = module.export(tmp_path)
    with zipfile.ZipFile(archive_path) as archive:
        assert not any(".local" in name for name in archive.namelist())
        assert archive.read("source/README.md") == b"Committed source"
        assert "project-jarvis.bundle" in archive.namelist()
        assert json.loads(archive.read("MANIFEST.json"))["git_commit"] == git("rev-parse", "HEAD")
    assert archive_path.with_suffix(".zip.sha256").is_file()
    (tmp_path / "README.md").write_text("uncommitted", encoding="utf-8")
    with pytest.raises(RuntimeError, match="Commit"):
        module.export(tmp_path)

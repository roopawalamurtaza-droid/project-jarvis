"""Generate packaged source identity before PyInstaller builds the application."""

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from jarvis import __version__

root = Path(__file__).resolve().parents[1]


def git(*args):
    return subprocess.run(
        ["git", *args], cwd=root, check=True, capture_output=True, text=True
    ).stdout.strip()


sources = {
    str(path.relative_to(root)).replace("\\", "/"): hashlib.sha256(path.read_bytes()).hexdigest()
    for path in sorted((root / "src/jarvis").glob("*.py"))
}
data = {
    "version": __version__,
    "git_commit": git("rev-parse", "HEAD"),
    "branch": git("branch", "--show-current"),
    "build_date_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    "dirty": bool(git("status", "--porcelain")),
    "source_sha256": sources,
}
target = root / "build/build_info.json"
target.parent.mkdir(exist_ok=True)
target.write_text(json.dumps(data, indent=2), encoding="utf-8")
print(f"Build {__version__}, {data['git_commit'][:12]}, dirty={data['dirty']}")

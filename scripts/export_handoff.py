"""Export committed source and all local Git history, excluding user/runtime data."""

from __future__ import annotations

import hashlib
import io
import json
import subprocess
import zipfile
from pathlib import Path


def export(root: Path) -> Path:
    def git(*args):
        return subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)

    if git("status", "--porcelain").stdout.strip():
        raise RuntimeError("Commit or resolve all non-ignored changes before exporting.")
    head = git("rev-parse", "HEAD").stdout.decode().strip()
    branch = git("branch", "--show-current").stdout.decode().strip()
    output = root / "transfer"
    output.mkdir(exist_ok=True)
    bundle = output / "project-jarvis.bundle"
    git("bundle", "create", str(bundle), "--all")
    git("bundle", "verify", str(bundle))
    source = zipfile.ZipFile(io.BytesIO(git("archive", "--format=zip", "HEAD").stdout))
    target = output / "PROJECT_JARVIS_HANDOFF.zip"
    files = {}
    with source, zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        for item in source.infolist():
            data = source.read(item)
            name = "source/" + item.filename
            archive.writestr(name, data)
            if not item.is_dir():
                files[name] = hashlib.sha256(data).hexdigest()
        data = bundle.read_bytes()
        archive.writestr(bundle.name, data)
        files[bundle.name] = hashlib.sha256(data).hexdigest()
        archive.writestr(
            "MANIFEST.json",
            json.dumps(
                {
                    "git_commit": head,
                    "branch": branch,
                    "sha256": files,
                    "excluded": [
                        ".local",
                        ".venv",
                        "build",
                        "dist",
                        "credentials",
                        "live settings",
                        "personal memory",
                        "microphone recordings",
                        "downloaded models",
                    ],
                },
                indent=2,
            ),
        )
        archive.writestr(
            "TRANSFER.txt",
            "Read source/PROJECT_HANDOFF.md first. For Git history, run: git clone -b feature/handsfree-voice project-jarvis.bundle Jarvis\nInstall dependencies and models as documented. No user data or keys are included.\n",
        )
    with zipfile.ZipFile(target) as archive:
        if archive.testzip() is not None:
            raise RuntimeError("Export integrity check failed")
        manifest = json.loads(archive.read("MANIFEST.json"))
        for name, digest in manifest["sha256"].items():
            if hashlib.sha256(archive.read(name)).hexdigest() != digest:
                raise RuntimeError("Export hash mismatch: " + name)
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    target.with_suffix(".zip.sha256").write_text(
        digest + "  " + target.name + "\n", encoding="utf-8"
    )
    print(f"Export verified: {target.name}, {head}, {digest}")
    return target


if __name__ == "__main__":
    export(Path(__file__).resolve().parents[1])

"""Export and verify the full frozen folder. Excludes live data and models."""

import hashlib
import json
import zipfile
from pathlib import Path


def export(root):
    folder = root / "dist" / "JARVIS"
    identity = json.loads((folder / "_internal/jarvis/build_info.json").read_text())
    target = root / "transfer" / ("JARVIS-Windows-" + identity["version"] + ".zip")
    target.parent.mkdir(exist_ok=True)
    hashes = {}
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=5) as archive:
        for path in sorted(folder.rglob("*")):
            if path.is_file():
                name = path.relative_to(folder.parent).as_posix()
                archive.write(path, name)
                hashes[name] = hashlib.sha256(path.read_bytes()).hexdigest()
        archive.writestr(
            "BUILD_MANIFEST.json", json.dumps({"build": identity, "sha256": hashes}, indent=2)
        )
        archive.writestr(
            "INSTALL.txt",
            """JARVIS Windows development build
Keep the entire JARVIS folder together. Exit the running app before replacement.
Extract separately and back up the old complete JARVIS folder. On this computer
the normal path is C:\\Jarvis\\dist\\JARVIS\\JARVIS.exe; Start JARVIS.cmd selects it.
Preserve C:\\Jarvis\\.local (settings/memory/keys/models). Never overwrite it with templates.
Launch: .\\JARVIS\\JARVIS.exe --data-dir C:\\Jarvis\\.local
Check Diagnostics: version, Git commit, UTC build date and actual executable path
against BUILD_MANIFEST.json. Start Ollama and select an installed model.
Speak replies is on Assistant; hands-free permission and devices are in Settings.
Existing opt-ins are preserved. New computers require explicit microphone consent,
offline Whisper model setup and fresh API keys. See PROJECT_HANDOFF.md.
No user data, keys or models are included. Unsigned build; fresh-PC testing pending.
""",
        )
    with zipfile.ZipFile(target) as archive:
        if archive.testzip() is not None:
            raise RuntimeError("Build archive integrity failure")
        for name, digest in hashes.items():
            if hashlib.sha256(archive.read(name)).hexdigest() != digest:
                raise RuntimeError("Build file hash mismatch: " + name)
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    target.with_suffix(".zip.sha256").write_text(digest + "  " + target.name + "\n")
    print(
        json.dumps(
            {
                "archive": str(target),
                "bytes": target.stat().st_size,
                "sha256": digest,
                "build_commit": identity["git_commit"],
                "verified_files": len(hashes),
            }
        )
    )
    return target


if __name__ == "__main__":
    export(Path(__file__).resolve().parents[1])

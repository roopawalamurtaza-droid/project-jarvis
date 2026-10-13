"""Narrow desktop tools. Model-generated shell commands are never accepted."""

from __future__ import annotations

import os
import re
import stat
import subprocess
import time
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class PathArgs(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    path: str = Field(min_length=1, max_length=2048)


class AppArgs(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    app: Literal["notepad", "calculator", "vscode", "chrome"]


SCHEMAS = {
    "list_directory": PathArgs,
    "read_file": PathArgs,
    "open_folder": PathArgs,
    "create_directory": PathArgs,
    "open_app": AppArgs,
}
READ_ONLY = {"list_directory", "read_file"}
SENSITIVE = {"create_directory"}
PRIVATE_PARTS = {".git", ".codex", ".agents", ".aws", ".ssh", ".gnupg", "secrets.dpapi.json"}
PRIVATE_SUFFIXES = {".pem", ".key", ".pfx", ".p12", ".kdbx"}


def tool_schemas():
    return [
        {
            "name": name,
            "description": name.replace("_", " "),
            "parameters": schema.model_json_schema(),
        }
        for name, schema in SCHEMAS.items()
    ]


class ToolRegistry:
    def __init__(self, settings):
        self.settings = settings
        self._children: list[subprocess.Popen] = []

    def scoped_path(self, raw: str) -> Path:
        if raw.startswith(("\\\\", "//")) or "\x00" in raw:
            raise PermissionError("Network paths and null bytes are forbidden")
        path = Path(raw).expanduser()
        if not path.is_absolute():
            raise PermissionError("Provide an absolute path within an allowed folder")
        for part in path.parts[1:]:
            lowered = part.lower()
            if ":" in part or part.endswith((".", " ")):
                raise PermissionError("Alternate streams and ambiguous Windows paths are forbidden")
            if re.fullmatch(r"(con|prn|aux|nul|com[1-9]|lpt[1-9])(\..*)?", lowered):
                raise PermissionError("Windows device paths are forbidden")
            if lowered in PRIVATE_PARTS or lowered == ".env" or lowered.startswith(".env."):
                raise PermissionError("Credential and system metadata paths are protected")
        if path.suffix.lower() in PRIVATE_SUFFIXES:
            raise PermissionError("Credential files are protected")
        resolved = path.resolve()
        roots = [Path(root) for root in self.settings.allowed_roots]
        if not any(resolved.is_relative_to(root) for root in roots):
            raise PermissionError("Path is outside the configured allowed folders")
        # Reject links/junctions rather than follow potentially retargetable filesystem objects.
        current = path
        while current != current.parent:
            if current.exists() or current.is_symlink():
                metadata = current.lstat()
                if (
                    stat.S_ISLNK(metadata.st_mode)
                    or getattr(metadata, "st_file_attributes", 0) & 0x400
                ):
                    raise PermissionError("Symbolic links and Windows junctions are forbidden")
            current = current.parent
        return resolved

    def validate(self, tool: str, arguments: dict) -> dict:
        if tool not in SCHEMAS:
            raise ValueError("Unknown tool; unrestricted execution is unavailable")
        if not isinstance(arguments, dict):
            raise ValueError("Tool arguments must be an object")
        validated = SCHEMAS[tool].model_validate(arguments).model_dump()
        if "path" in validated:
            validated["path"] = str(self.scoped_path(validated["path"]))
        return validated

    def execute(self, tool, arguments):
        args = self.validate(tool, arguments)  # revalidate immediately before execution
        if tool == "open_app":
            return self._open_app(args["app"])
        path = self.scoped_path(args["path"])
        if tool == "list_directory":
            if not path.is_dir():
                raise ValueError("The selected path is not an existing directory")
            entries = []
            # Bound enumeration and returned data independently of directory size.
            for index, child in enumerate(path.iterdir()):
                if index >= 200:
                    break
                metadata = child.lstat()
                linked = stat.S_ISLNK(metadata.st_mode) or bool(
                    getattr(metadata, "st_file_attributes", 0) & 0x400
                )
                entries.append(
                    {
                        "name": child.name,
                        "directory": stat.S_ISDIR(metadata.st_mode) and not linked,
                        "link": linked,
                    }
                )
            return {"verified": True, "path": str(path), "entries": entries, "limit": 200}
        if tool == "read_file":
            if not path.is_file():
                raise ValueError("The selected path is not an existing file")
            with path.open("rb") as source:
                data = source.read(65537)
            if len(data) > 65536:
                raise ValueError("Text file exceeds the 64 KiB read limit")
            if b"\x00" in data:
                raise ValueError("This tool reads UTF-8 text files only")
            text = data.decode("utf-8-sig")
            return {
                "verified": True,
                "path": str(path),
                "content": text,
                "bytes": len(data),
                "untrusted": True,
            }
        if tool == "create_directory":
            path.mkdir(parents=False, exist_ok=True)
            return {"verified": path.is_dir(), "path": str(path)}
        if tool == "open_folder":
            if not path.is_dir():
                raise ValueError("The selected path is not an existing directory")
            if os.name != "nt":
                raise RuntimeError("Opening Explorer requires Windows")
            # No shell; separate fixed executable and an exact, validated directory argument.
            executable = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "explorer.exe"
            return self._launch([str(executable), str(path)], "Explorer")
        raise ValueError("Unknown tool")

    def application_path(self, app):
        """Resolve an allowlisted installed application without launching it."""
        if os.name != "nt":
            raise RuntimeError("Desktop application launch requires Windows")
        system = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
        candidates = {
            "notepad": [system / "notepad.exe"],
            "calculator": [system / "calc.exe"],
            "chrome": [
                Path(os.environ.get("ProgramFiles", "")) / "Google/Chrome/Application/chrome.exe",
                Path(os.environ.get("ProgramFiles(x86)", ""))
                / "Google/Chrome/Application/chrome.exe",
                Path(os.environ.get("LOCALAPPDATA", "")) / "Google/Chrome/Application/chrome.exe",
            ],
            "vscode": [
                Path(os.environ.get("LOCALAPPDATA", "")) / "Programs/Microsoft VS Code/Code.exe",
                Path(os.environ.get("ProgramFiles", "")) / "Microsoft VS Code/Code.exe",
            ],
        }[app]
        executable = next((candidate for candidate in candidates if candidate.is_file()), None)
        return executable

    def _open_app(self, app):
        executable = self.application_path(app)
        if executable is None:
            raise RuntimeError("Requested application is not installed at a supported location")
        return self._launch([str(executable)], app)

    def _launch(self, argv, label):
        child = subprocess.Popen(
            argv,
            shell=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        time.sleep(0.15)
        code = child.poll()
        self._children = [process for process in self._children if process.poll() is None]
        if code is None:
            self._children.append(child)
        if code not in {None, 0}:
            raise RuntimeError("Application launcher exited unsuccessfully")
        return {
            "verified": True,
            "app": label,
            "pid": child.pid,
            "evidence": "process_running" if code is None else "launcher_accepted",
            "detail": "Launch request verified; window visibility and project loading were not verified.",
        }

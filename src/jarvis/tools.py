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
    app: str = Field(min_length=1, max_length=160)


class WebsiteArgs(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    target: str = Field(min_length=1, max_length=4096)
    browser: Literal["default", "chrome", "edge", "firefox"] | None = None
    new_window: bool | None = None


class SearchArgs(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    query: str = Field(min_length=1, max_length=500)
    engine: Literal["google", "bing", "duckduckgo", "youtube"] | None = None
    browser: Literal["default", "chrome", "edge", "firefox"] | None = None
    new_window: bool | None = None


class EmptyArgs(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


SCHEMAS = {
    "list_directory": PathArgs,
    "read_file": PathArgs,
    "open_folder": PathArgs,
    "create_directory": PathArgs,
    "open_app": AppArgs,
    "focus_app": AppArgs,
    "open_website": WebsiteArgs,
    "search_web": SearchArgs,
    "list_applications": EmptyArgs,
    "get_system_status": EmptyArgs,
}
READ_ONLY = {"list_directory", "read_file", "list_applications", "get_system_status"}
SENSITIVE = {"create_directory"}
PRIVATE_PARTS = {".git", ".codex", ".agents", ".aws", ".ssh", ".gnupg", "secrets.dpapi.json"}
PRIVATE_SUFFIXES = {".pem", ".key", ".pfx", ".p12", ".kdbx"}


def tool_schemas():
    descriptions = {
        "open_app": "Launch or focus an explicitly requested installed application, using an exact name or alias. No command-line arguments or scripts.",
        "focus_app": "Focus an existing visible window for an exact installed application. Windows may refuse foreground focus.",
        "open_website": "Open an explicit known site alias or public HTTPS URL in the user's browser. Unknown sites require approval. Does not read the page.",
        "search_web": "Open a user-requested, safely encoded search in Google, Bing, DuckDuckGo or YouTube. This is browser navigation, not completed research.",
        "list_applications": "Read the local installed application catalog, not a list of active processes.",
        "get_system_status": "Measure actual CPU and RAM, and supported GPU metrics. Values may be unavailable.",
    }
    return [
        {
            "name": name,
            "description": descriptions.get(name, name.replace("_", " ")),
            "parameters": schema.model_json_schema(),
        }
        for name, schema in SCHEMAS.items()
    ]


class ToolRegistry:
    def __init__(self, settings):
        self.settings = settings
        self._children: list[subprocess.Popen] = []
        from .applications import ApplicationRegistry
        from .awareness import SystemMetricsProvider
        from .browser_actions import BrowserActionService
        from .windows_actions import WindowsActionService

        self.applications = ApplicationRegistry(settings)
        self.windows = WindowsActionService(self.applications)
        self.browser = BrowserActionService(settings, self.windows)
        self.metrics = SystemMetricsProvider()

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
        if tool in {"open_app", "focus_app"}:
            from .applications import BLOCKED_EXECUTABLES, ApplicationNotFound, normalized_name

            name = normalized_name(validated["app"])
            if name.removesuffix(".exe") in BLOCKED_EXECUTABLES or any(c in name for c in "/\\:;|"):
                raise PermissionError(
                    "Command interpreters and arbitrary command lines are restricted"
                )
            # Freeze aliases to a stable catalog ID, even when disabled. Missing
            # apps stay as explicit targets so the executor can record not-found.
            try:
                validated["app"] = self.applications.resolve(name)["id"]
            except ApplicationNotFound:
                validated["app"] = name
        if tool == "open_website":
            validated["target"] = self.browser.resolve_url(validated["target"])
        if tool in {"open_website", "search_web"}:
            validated["browser"] = validated["browser"] or self.settings.default_browser
            if validated["new_window"] is None:
                validated["new_window"] = self.settings.browser_new_window
            if tool == "search_web":
                validated["engine"] = validated["engine"] or self.settings.default_search_engine
                if not validated["query"].strip() or any(ord(c) < 32 for c in validated["query"]):
                    raise ValueError("Search query must be readable text")
        if "path" in validated:
            validated["path"] = str(self.scoped_path(validated["path"]))
        return validated

    def requires_approval(self, tool, arguments):
        return tool == "open_website" and self.browser.requires_approval(arguments["target"])

    def authorization_snapshot(self, tool, arguments):
        if tool in {"open_app", "focus_app"} or (
            tool in {"open_website", "search_web"} and arguments.get("browser") != "default"
        ):
            from .applications import ApplicationNotFound

            name = arguments["app"] if "app" in arguments else arguments["browser"]
            try:
                app = self.applications.resolve(name)
                return {"id": app["id"], "target": app["target"], "kind": app["kind"]}
            except ApplicationNotFound:
                return {"id": name, "missing": True}
        return None

    def execute(self, tool, arguments):
        args = self.validate(tool, arguments)  # revalidate immediately before execution
        if tool == "open_app":
            return self._open_app(args["app"])
        if tool == "focus_app":
            self._desktop_permission()
            return self.windows.focus(args["app"])
        if tool == "open_website":
            return self.browser.open_website(**args)
        if tool == "search_web":
            return self.browser.search_web(**args)
        if tool == "list_applications":
            return {
                "verified": True,
                "applications": self.applications.list_apps(),
                "evidence": "local_catalog",
                "detail": "Discovery metadata, not running processes",
            }
        if tool == "get_system_status":
            return {
                "verified": True,
                "system": self.metrics.sample().as_dict(),
                "evidence": "system_measurement",
            }
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
            self._desktop_permission()
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
        return self.windows.application_path(app)

    def _desktop_permission(self):
        if not self.settings.desktop_actions_enabled:
            raise PermissionError("Desktop actions are disabled in Settings")

    def _open_app(self, app):
        self._desktop_permission()
        return self.windows.launch(app)

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

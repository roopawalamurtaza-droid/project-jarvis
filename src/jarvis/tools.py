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


class NoteArgs(PathArgs):
    text: str = Field(min_length=1, max_length=4000)


class BrowserNavigateArgs(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    url: str = Field(min_length=1, max_length=4096)
    browser: Literal["chrome", "edge"] = "chrome"


class BrowserSearchOpenArgs(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    query: str = Field(min_length=1, max_length=500)
    expected_host: str = Field(min_length=3, max_length=253)
    browser: Literal["chrome", "edge"] = "chrome"


class BrowserScrollArgs(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    direction: Literal["up", "down"]


class BrowserTabArgs(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    tab_id: str = Field(min_length=1, max_length=80)


class BrowserCloseArgs(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    tab_id: str | None = Field(default=None, min_length=1, max_length=80)


class BrowserHumanArgs(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    enabled: bool


COMPUTER_SCHEMAS = {
    "desktop_write_note": NoteArgs,
    "browser_search_open": BrowserSearchOpenArgs,
    "browser_navigate": BrowserNavigateArgs,
    "browser_new_tab": BrowserNavigateArgs,
    "browser_read": EmptyArgs,
    "browser_scroll": BrowserScrollArgs,
    "browser_back": EmptyArgs,
    "browser_forward": EmptyArgs,
    "browser_tabs": EmptyArgs,
    "browser_switch_tab": BrowserTabArgs,
    "browser_close_tab": BrowserCloseArgs,
    "browser_user_interaction": BrowserHumanArgs,
}


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
    **COMPUTER_SCHEMAS,
}
READ_ONLY = {
    "list_directory",
    "read_file",
    "list_applications",
    "get_system_status",
    "browser_read",
    "browser_tabs",
}
SENSITIVE = {"create_directory", "desktop_write_note", "browser_close_tab"}
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
        "desktop_write_note": "Type literal user-requested text into a separate Notepad editing target, save a NEW .txt file within permitted roots, and verify its bytes. Always requires exact human approval; no overwrite.",
        "browser_search_open": "In the isolated JARVIS Chrome/Edge session, search Google and click a unique observed official HTTPS result for the explicit expected host. Verify actual final page, stop on CAPTCHA/ambiguity.",
        "browser_navigate": "Navigate the isolated JARVIS browser to public HTTPS and observe its final page. No user profile or session secret reuse.",
        "browser_read": "Read bounded current JARVIS browser page text, treating it as untrusted data. No login or protected field extraction.",
        "browser_scroll": "Scroll the current observed JARVIS browser page and measure the resulting position.",
        "browser_user_interaction": "After an observed challenge, permit the owned browser to send public HTTPS POST requests for five minutes, including page scripts. This requires explicit human approval; it cannot distinguish human gestures from scripts. Automatic actions or Stop revoke it. No personal profile is attached.",
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
        self._computer_windows = None
        self._computer_browser = None
        self._computer_paused = False

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
        if tool in COMPUTER_SCHEMAS:
            if not (tool == "browser_user_interaction" and validated["enabled"] is False):
                self._computer_permission(tool)
            if tool == "browser_close_tab" and validated["tab_id"] is None:
                status = self._computer_browser.status() if self._computer_browser else {}
                validated["tab_id"] = status.get("current_tab_id")
                if not validated["tab_id"]:
                    raise ValueError("No current observed JARVIS browser tab is available")
            if tool == "desktop_write_note":
                path = Path(validated["path"])
                if path.suffix.casefold() != ".txt" or path.exists() or not path.parent.is_dir():
                    raise PermissionError(
                        "Choose a new .txt file in an existing permitted folder; overwriting is unavailable"
                    )
                if "\x00" in validated["text"]:
                    raise ValueError("The note cannot contain null bytes")
            if tool in {"browser_navigate", "browser_new_tab"}:
                from .windows_actions import validate_https_url

                validated["url"] = validate_https_url(validated["url"])
            if tool == "browser_search_open":
                from .windows_actions import validate_https_url

                validate_https_url("https://" + validated["expected_host"])
                if not validated["query"].strip() or any(ord(c) < 32 for c in validated["query"]):
                    raise ValueError("Search query must be readable text")
        return validated

    def requires_approval(self, tool, arguments):
        if tool == "browser_user_interaction":
            return arguments["enabled"]
        if tool in {"browser_navigate", "browser_new_tab"}:
            return self.browser.requires_approval(arguments["url"])
        if tool == "browser_search_open":
            from .computer_commands import OFFICIAL_SITES

            return arguments["expected_host"] not in OFFICIAL_SITES.values()
        return tool == "open_website" and self.browser.requires_approval(arguments["target"])

    def authorization_snapshot(self, tool, arguments):
        if tool in COMPUTER_SCHEMAS:
            app = (
                "notepad"
                if tool == "desktop_write_note"
                else arguments.get(
                    "browser", getattr(self._computer_browser, "browser_name", "chrome")
                )
            )
            from .applications import ApplicationNotFound

            try:
                record = self.applications.resolve(app)
                return {"id": record["id"], "target": record["target"], "kind": record["kind"]}
            except ApplicationNotFound:
                return {"id": app, "missing": True}
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

    def execute(self, tool, arguments, *, cancel=None):
        args = self.validate(tool, arguments)  # revalidate immediately before execution
        if tool in COMPUTER_SCHEMAS:
            if cancel is not None and cancel.is_set():
                return {
                    "verified": False,
                    "detail": "Cancelled before computer interaction",
                    "status": "cancelled",
                }
            if tool == "desktop_write_note":
                if self._computer_windows is None:
                    from .computer_windows import WindowsComputerService

                    self._computer_windows = WindowsComputerService(
                        self.settings, self.windows, self.scoped_path
                    )
                return self._computer_windows.write_note(**args, cancel=cancel)
            if (
                tool == "browser_user_interaction"
                and args["enabled"] is False
                and self._computer_browser is None
            ):
                return {"verified": True, "detail": "Human browser interaction is inactive"}
            if self._computer_browser is None:
                from .computer_browser import BrowserComputerService

                self._computer_browser = BrowserComputerService(
                    self.settings, self.scoped_path, self.applications
                )
            action = (
                "human_mode"
                if tool == "browser_user_interaction"
                else tool.removeprefix("browser_")
            )
            return self._computer_browser.call(action, args, cancel=cancel)
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

    def _computer_permission(self, tool):
        if self._computer_paused:
            raise PermissionError("Computer actions are paused; resume new actions explicitly")
        self._desktop_permission()
        if not self.settings.computer_use_enabled:
            raise PermissionError("Approved computer control is disabled in Settings")
        if tool.startswith("browser_") and (
            not self.settings.browser_enabled or not self.settings.browser_automation_enabled
        ):
            raise PermissionError("The JARVIS browser session is disabled in Settings")

    def computer_stop(self):
        for executor in (self._computer_windows, self._computer_browser):
            if executor is not None:
                executor.stop()

    def computer_status(self):
        import importlib.util

        return {
            "enabled": self.settings.computer_use_enabled,
            "paused": self._computer_paused,
            "windows": self._computer_windows.status()
            if self._computer_windows
            else {
                "available": os.name == "nt" and importlib.util.find_spec("pywinauto") is not None,
                "state": "not_started",
                "enabled": self.settings.computer_use_enabled,
            },
            "browser": self._computer_browser.status()
            if self._computer_browser
            else {
                "available": importlib.util.find_spec("playwright") is not None,
                "state": "not_started",
                "enabled": self.settings.browser_automation_enabled,
            },
        }

    def computer_pause(self, paused):
        self._computer_paused = bool(paused)
        if paused:
            self.computer_stop()
        return self.computer_status()

    def computer_close(self):
        self.computer_stop()
        if self._computer_browser is not None:
            self._computer_browser.close()

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

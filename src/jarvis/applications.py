"""Local, bounded application discovery and explicit launch permissions.

App Paths and Start Menu metadata are discovery hints, never command lines.
Only reviewed records can execute. No catalog is sent to an AI provider.
"""

from __future__ import annotations

import copy
import ctypes
import hashlib
import json
import ntpath
import os
import re
import stat
import struct
import threading
import time
import uuid
from pathlib import Path


class ApplicationNotFound(ValueError):
    """No exact application name or alias matches."""


class AmbiguousApplicationError(ValueError):
    def __init__(self, matches):
        self.matches = copy.deepcopy(matches)
        super().__init__("Several applications match; choose an exact application name or ID")


# Executable tools whose ordinary purpose bypasses the narrow action boundary.
BLOCKED_EXECUTABLES = {
    "cmd",
    "powershell",
    "pwsh",
    "wscript",
    "cscript",
    "mshta",
    "rundll32",
    "regsvr32",
    "reg",
    "regedit",
    "mmc",
    "control",
    "runas",
    "schtasks",
    "sc",
    "net",
    "net1",
    "shutdown",
    "taskkill",
    "wmic",
    "certutil",
    "bitsadmin",
    "msiexec",
    "installutil",
    "python",
    "pythonw",
    "py",
    "node",
    "deno",
    "bun",
    "ruby",
    "perl",
    "php",
    "java",
    "javaw",
    "bash",
    "sh",
    "wsl",
    "wt",
    "conhost",
    "ssh",
    "sftp",
    "ftp",
    "curl",
    "wget",
    "nircmd",
    "psexec",
    "procexp",
    "procdump",
    "lsass",
    "mimikatz",
}
KNOWN = {
    "notepad": ("Notepad", ["windows notepad"], {"notepad.exe"}),
    "calculator": ("Calculator", ["calc", "windows calculator"], {"calc.exe", "calculatorapp.exe"}),
    "vscode": ("Visual Studio Code", ["vs code", "vscode", "code"], {"code.exe"}),
    "chrome": ("Google Chrome", ["chrome"], {"chrome.exe"}),
    "edge": ("Microsoft Edge", ["edge"], {"msedge.exe"}),
    "firefox": ("Mozilla Firefox", ["firefox"], {"firefox.exe"}),
    "explorer": (
        "File Explorer",
        ["explorer", "windows explorer", "windows file explorer"],
        {"explorer.exe"},
    ),
    "task_manager": ("Task Manager", ["task manager", "taskmanager"], {"taskmgr.exe"}),
    "settings": ("Windows Settings", ["settings"], {"systemsettings.exe"}),
    "spotify": ("Spotify", ["spotify music"], {"spotify.exe"}),
    "discord": ("Discord", [], {"discord.exe"}),
    "android_studio": ("Android Studio", ["android studio", "studio"], {"studio64.exe"}),
    "steam": ("Steam", [], {"steam.exe"}),
    "telegram": ("Telegram", ["telegram desktop"], {"telegram.exe"}),
}
PACKAGED = {
    "calculator": "Microsoft.WindowsCalculator_8wekyb3d8bbwe!App",
    "notepad": "Microsoft.WindowsNotepad_8wekyb3d8bbwe!App",
    "spotify": "SpotifyAB.SpotifyMusic_zpdnekdrzrea0!Spotify",
    "settings": "windows.immersivecontrolpanel_cw5n1h2txyewy!microsoft.windows.immersivecontrolpanel",
}
MAX_APPS = 512
MAX_CUSTOM = 100
MAX_ALIASES = 20


def normalized_name(value: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 160:
        raise ValueError("Use a nonempty application name of at most 160 characters")
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ValueError("Application names must not contain control characters")
    return " ".join(value.casefold().split())


def validate_executable(raw: str | Path) -> Path:
    """Validate a local regular EXE and every ancestor without following reparse points."""
    text = str(raw)
    if len(text) > 2048 or "\x00" in text or text.startswith(("\\\\", "//")):
        raise PermissionError("Only local executable paths are permitted")
    path = Path(text)
    if not path.is_absolute() or path.suffix.casefold() != ".exe":
        raise PermissionError("Choose an absolute path to a local EXE")
    if path.stem.casefold() in BLOCKED_EXECUTABLES or re.fullmatch(
        r"(?:python(?:w)?[0-9.]*)|(?:powershell[0-9.]*)|(?:pwsh[0-9.]*)", path.stem.casefold()
    ):
        raise PermissionError(
            "Command interpreters, script runners and system administration tools are restricted"
        )
    for part in path.parts[1:]:
        if (
            ":" in part
            or part.endswith((".", " "))
            or re.fullmatch(r"(con|prn|aux|nul|com[1-9]|lpt[1-9])(\..*)?", part.casefold())
        ):
            raise PermissionError(
                "Device paths, alternate streams and ambiguous paths are forbidden"
            )
        if part.casefold() in {".ssh", ".aws", ".gnupg", ".codex", ".git"}:
            raise PermissionError("Credential and private metadata directories are protected")
    current = path
    while current != current.parent:
        metadata = current.lstat()
        if stat.S_ISLNK(metadata.st_mode) or getattr(metadata, "st_file_attributes", 0) & 0x400:
            raise PermissionError("Links and Windows junctions cannot be application targets")
        current = current.parent
    if not stat.S_ISREG(path.lstat().st_mode):
        raise PermissionError("Application target must be a regular executable file")
    return path.resolve(strict=True)


def _known_candidates() -> dict[str, list[Path]]:
    def root(variable, fallback):
        value = os.environ.get(variable, fallback)
        return Path(value) if value else None

    windows = root("SystemRoot", r"C:\Windows")
    programs = root("ProgramFiles", r"C:\Program Files")
    programs32 = root("ProgramFiles(x86)", r"C:\Program Files (x86)")
    local = root("LOCALAPPDATA", "")
    roaming = root("APPDATA", "")
    result = {key: [] for key in KNOWN}
    if windows:
        result["notepad"].append(windows / "System32/notepad.exe")
        result["calculator"].append(windows / "System32/calc.exe")
        result["explorer"].append(windows / "explorer.exe")
        result["task_manager"].append(windows / "System32/Taskmgr.exe")
    for base in (programs, programs32, local):
        if not base:
            continue
        result["chrome"].append(base / "Google/Chrome/Application/chrome.exe")
        result["edge"].append(base / "Microsoft/Edge/Application/msedge.exe")
        result["firefox"].append(base / "Mozilla Firefox/firefox.exe")
    if local:
        result["vscode"].append(local / "Programs/Microsoft VS Code/Code.exe")
        result["telegram"].append(local / "Telegram Desktop/Telegram.exe")
        # Discord uses versioned app directories, not the generic Update.exe command runner.
        directory = local / "Discord"
        try:
            versions = sorted(directory.glob("app-*"), reverse=True)[:10]
            result["discord"].extend(path / "Discord.exe" for path in versions if path.is_dir())
        except OSError:
            pass
    if programs:
        result["vscode"].append(programs / "Microsoft VS Code/Code.exe")
        result["android_studio"].append(programs / "Android/Android Studio/bin/studio64.exe")
        result["telegram"].append(programs / "Telegram Desktop/Telegram.exe")
    if programs32:
        result["steam"].append(programs32 / "Steam/steam.exe")
    if roaming:
        result["spotify"].append(roaming / "Spotify/Spotify.exe")
        result["telegram"].append(roaming / "Telegram Desktop/Telegram.exe")
    return result


def _app_paths():
    if os.name != "nt":
        return []
    import winreg

    result = []
    key_name = r"Software\Microsoft\Windows\CurrentVersion\App Paths"
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
            try:
                with winreg.OpenKey(hive, key_name, 0, winreg.KEY_READ | view) as key:
                    count = min(winreg.QueryInfoKey(key)[0], MAX_APPS)
                    for index in range(count):
                        name = winreg.EnumKey(key, index)
                        if not name.casefold().endswith(".exe"):
                            continue
                        try:
                            with winreg.OpenKey(key, name) as entry:
                                value, kind = winreg.QueryValueEx(entry, "")
                            if kind not in {winreg.REG_SZ, winreg.REG_EXPAND_SZ} or not isinstance(
                                value, str
                            ):
                                continue
                            # App Paths contains one path, never parse or execute a command line.
                            value = os.path.expandvars(value).strip()
                            if value.startswith('"') and value.endswith('"'):
                                value = value[1:-1]
                            result.append(
                                {"name": Path(name).stem, "target": value, "source": "app_paths"}
                            )
                        except OSError:
                            continue
            except OSError:
                continue
    return result[:MAX_APPS]


class _GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", ctypes.c_uint32),
        ("Data2", ctypes.c_uint16),
        ("Data3", ctypes.c_uint16),
        ("Data4", ctypes.c_ubyte * 8),
    ]

    @classmethod
    def parse(cls, value):
        return cls.from_buffer_copy(uuid.UUID(value).bytes_le)


def _com_method(pointer, index, restype, *argtypes):
    table = ctypes.cast(pointer, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    return ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *argtypes)(table[index])


def _shortcut_target(path: Path):
    """Read one simple local LinkInfo target without loading native ShellLink COM.

    MS-SHLLINK §§2.1–2.3: only bounded local paths are discovery hints. Links
    with arguments, network targets, advertised installers, elevation or
    environment-dependent targets require an explicit custom EXE instead.
    https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-shllink/6813269d-0cc8-4be2-933f-e96e8e3412dc
    """
    try:
        if not path.is_absolute() or str(path).startswith(("\\\\", "//")):
            return None
        current = path
        while current != current.parent:
            metadata = current.lstat()
            if stat.S_ISLNK(metadata.st_mode) or getattr(metadata, "st_file_attributes", 0) & 0x400:
                return None
            current = current.parent
        if not path.is_file() or path.stat().st_size > 128 * 1024:
            return None
        with path.open("rb") as source:
            data = source.read(128 * 1024 + 1)
        if len(data) < 76 or len(data) > 128 * 1024:
            return None
        if (
            struct.unpack_from("<I", data)[0] != 76
            or data[4:20] != uuid.UUID("00021401-0000-0000-C000-000000000046").bytes_le
        ):
            return None
        flags = struct.unpack_from("<I", data, 20)[0]
        restricted = 0x20 | 0x100 | 0x200 | 0x1000 | 0x2000 | 0x20000 | 0x2000000
        if not flags & 2 or flags & restricted:
            return None
        offset = 76
        if flags & 1:
            offset += 2 + struct.unpack_from("<H", data, offset)[0]
        size, header_size, info_flags, volume, local, network, suffix = struct.unpack_from(
            "<7I", data, offset
        )
        if (
            size < 28
            or offset + size > len(data)
            or header_size not in {28, 36}
            or header_size > size
            or info_flags != 1
            or network != 0
            or not header_size <= volume < size
        ):
            return None
        info = data[offset : offset + size]

        def string_at(position, unicode=False):
            if not header_size <= position < size:
                raise ValueError("Invalid shortcut string offset")
            step = 2 if unicode else 1
            for end in range(position, min(size, position + 2049 * step), step):
                if end + step <= size and info[end : end + step] == b"\0" * step:
                    return info[position:end].decode("utf-16-le" if unicode else "ascii")
            raise ValueError("Unterminated or oversized shortcut string")

        if header_size == 36:
            local, suffix = struct.unpack_from("<2I", info, 28)
            target = string_at(local, True) + string_at(suffix, True)
        else:
            # ASCII is a portable subset of the system code page. Non-ASCII
            # legacy ANSI links fail closed rather than guessing their path.
            target = string_at(local) + string_at(suffix)
        drive, _ = ntpath.splitdrive(target)
        if (
            not ntpath.isabs(target)
            or not re.fullmatch(r"[A-Za-z]:", drive)
            or ntpath.splitext(target)[1].casefold() != ".exe"
            or len(target) > 2048
            or any(ord(char) < 32 or ord(char) == 127 for char in target)
        ):
            return None
        return {"name": path.stem, "target": target, "source": "start_menu"}
    except (OSError, ValueError, struct.error, UnicodeError):
        return None


def _start_menu_entries():
    result = []
    scanned = 0
    roots = []
    deadline = time.monotonic() + 2
    for variable in ("APPDATA", "ProgramData"):
        if os.environ.get(variable):
            roots.append(Path(os.environ[variable]) / "Microsoft/Windows/Start Menu/Programs")
    for root in roots:
        try:
            if (
                str(root).startswith(("\\\\", "//"))
                or not root.is_dir()
                or root.is_symlink()
                or getattr(root.lstat(), "st_file_attributes", 0) & 0x400
            ):
                continue
        except OSError:
            continue
        for directory, folders, files in os.walk(root, followlinks=False):
            if time.monotonic() > deadline:
                return result
            base = Path(directory)
            folders[:] = sorted(folders)[:100] if len(base.relative_to(root).parts) < 8 else []
            folders[:] = [
                name
                for name in folders
                if not (base / name).is_symlink()
                and not getattr((base / name).lstat(), "st_file_attributes", 0) & 0x400
            ]
            for name in sorted(files):
                scanned += 1
                if scanned > 1500:
                    return result
                if not name.casefold().endswith(".lnk"):
                    continue
                path = base / name
                try:
                    if path.is_symlink() or path.stat().st_size > 128 * 1024:
                        continue
                    record = _shortcut_target(path)
                    if record:
                        result.append(record)
                except (OSError, ValueError):
                    continue
    return result[:MAX_APPS]


def _packaged_entries():
    """Discover only fixed known package identities, with executable fallbacks elsewhere."""
    if os.name != "nt":
        return []
    import winreg

    path = r"Software\Classes\Local Settings\Software\Microsoft\Windows\CurrentVersion\AppModel\Repository\Packages"
    packages = []
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as key:
            packages = [
                winreg.EnumKey(key, index)
                for index in range(min(winreg.QueryInfoKey(key)[0], MAX_APPS))
            ]
    except OSError:
        return []
    result = []
    for identity, aumid in PACKAGED.items():
        family = aumid.split("!", 1)[0]
        package_name, publisher = family.rsplit("_", 1)
        if any(
            name.casefold().startswith(package_name.casefold() + "_")
            and name.casefold().endswith("_" + publisher.casefold())
            for name in packages
        ):
            result.append(
                {
                    "id": identity,
                    "name": KNOWN[identity][0],
                    "target": aumid,
                    "source": "known_package",
                    "kind": "packaged",
                }
            )
    return result


class ApplicationRegistry:
    """A lazy cached catalog whose custom records and permissions stay local."""

    def __init__(self, settings):
        self.settings = settings
        self._records = None
        self._complete = False
        self._refreshed = None
        self._errors = []
        self._lock = threading.RLock()
        self._configuration = {"version": 1, "overrides": {}, "custom": []}
        self._load_configuration()

    @property
    def configuration_path(self):
        return Path(self.settings.data_dir) / "applications.json"

    def _load_configuration(self):
        path = self.configuration_path
        if not path.exists():
            return
        try:
            if path.stat().st_size > 256 * 1024:
                raise ValueError("Application configuration exceeds its size limit")
            data = json.loads(path.read_text(encoding="utf-8"))
            if (
                not isinstance(data, dict)
                or data.get("version") != 1
                or not isinstance(data.get("overrides"), dict)
                or not isinstance(data.get("custom"), list)
            ):
                raise ValueError("Application configuration has an unsupported format")
            if len(data["overrides"]) > MAX_APPS or len(data["custom"]) > MAX_CUSTOM:
                raise ValueError("Application configuration exceeds its record limit")
            self._configuration = data
        except (OSError, ValueError, TypeError):
            self._errors.append(
                "Saved application configuration could not be loaded; defaults remain active"
            )

    def _save_configuration(self):
        target = self.configuration_path
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(".tmp")
        temporary.write_text(json.dumps(self._configuration, indent=2), encoding="utf-8")
        temporary.replace(target)

    def refresh(self, *, full=True):
        with self._lock:
            records = []
            seen = set()
            canonical = set()
            candidates = _known_candidates() if os.name == "nt" else {}

            def add(raw, *, known_id=None, enabled=False):
                try:
                    kind = raw.get("kind", "exe")
                    target = raw["target"]
                    if kind == "exe":
                        target = str(validate_executable(target))
                    elif kind != "packaged" or target not in PACKAGED.values():
                        return
                    if kind == "packaged" and known_id in canonical:
                        # System32 launchers activate the same fixed Store app.
                        # Keep the supported EXE preference and its unique ID;
                        # windows() can verify its corresponding known AUMID.
                        return
                    key = (kind, target.casefold())
                    if key in seen or len(records) >= MAX_APPS:
                        return
                    seen.add(key)
                    if known_id and known_id not in canonical:
                        identity = known_id
                        canonical.add(known_id)
                    else:
                        identity = (
                            raw.get("id") if not known_id else None
                        ) or "app_" + hashlib.sha256(
                            (kind + target.casefold()).encode()
                        ).hexdigest()[:16]
                    if any(record["id"] == identity for record in records):
                        return
                    if known_id:
                        name, aliases, _ = KNOWN[known_id]
                        aliases = [*aliases, known_id.replace("_", " ")]
                    else:
                        name, aliases = raw["name"], raw.get("aliases", [])
                    normalized_name(name)
                    aliases = list(dict.fromkeys(normalized_name(alias) for alias in aliases))[
                        :MAX_ALIASES
                    ]
                    override = self._configuration["overrides"].get(identity, {})
                    if not isinstance(override, dict):
                        override = {}
                    added = override.get("aliases", [])
                    removed = override.get("removed_aliases", [])
                    if isinstance(added, list) and isinstance(removed, list):
                        aliases = [alias for alias in aliases if alias not in removed]
                        aliases.extend(normalized_name(alias) for alias in added[:MAX_ALIASES])
                    permission = override.get("enabled", enabled)
                    # A canonical alias may resolve to a different installation
                    # after refresh. A reviewed grant belongs to its exact target,
                    # not to a familiar executable basename or reusable app ID.
                    if (
                        permission is True
                        and "enabled" in override
                        and (override.get("target") != target or override.get("kind") != kind)
                    ):
                        permission = False
                    favorite = override.get("favorite", False)
                    records.append(
                        {
                            "id": identity,
                            "name": name,
                            "aliases": list(dict.fromkeys(aliases))[:MAX_ALIASES],
                            "target": target,
                            "kind": kind,
                            "source": raw["source"],
                            "enabled": permission if isinstance(permission, bool) else False,
                            "favorite": favorite if isinstance(favorite, bool) else False,
                        }
                    )
                except (OSError, ValueError, TypeError, KeyError):
                    return

            for identity, paths in candidates.items():
                for path in paths:
                    before = len(records)
                    add(
                        {"target": path, "source": "known_location"},
                        known_id=identity,
                        enabled=True,
                    )
                    if len(records) != before:
                        break
            sources = (_packaged_entries, _app_paths)
            if full:
                sources += (_start_menu_entries,)
            for discover in sources:
                try:
                    discovered = discover()
                    for raw in discovered[:MAX_APPS]:
                        known_id = (
                            raw.get("id")
                            if raw.get("kind") == "packaged"
                            else next(
                                (
                                    identity
                                    for identity, (_, _, filenames) in KNOWN.items()
                                    if Path(raw["target"]).name.casefold() in filenames
                                ),
                                None,
                            )
                        )
                        add(raw, known_id=known_id, enabled=raw.get("source") == "known_package")
                except (OSError, ValueError, TypeError):
                    self._errors.append("One application discovery source is unavailable")
            for custom in self._configuration["custom"]:
                if isinstance(custom, dict):
                    add({**custom, "source": "custom", "kind": "exe"})
            self._records = records
            self._complete = full
            self._refreshed = time.monotonic()
            return copy.deepcopy(records)

    def list_apps(self, query=""):
        with self._lock:
            if self._records is None or not self._complete:
                self.refresh()
            query = normalized_name(query) if query else ""
            return copy.deepcopy(
                [
                    record
                    for record in self._records
                    if not query
                    or any(
                        query in normalized_name(value)
                        for value in [record["id"], record["name"], *record["aliases"]]
                    )
                ]
            )

    def resolve(self, name):
        query = normalized_name(name)
        with self._lock:
            # Canonical commands such as "chrome" use cheap registry/package
            # metadata first. Complete library discovery remains explicit;
            # unresolved targets and noncanonical names require that catalog.
            if self._records is None:
                self.refresh(full=query not in KNOWN)
            if not self._complete and query not in KNOWN:
                self.refresh()

            def matching():
                direct = [record for record in self._records if record["id"].casefold() == query]
                return direct or [
                    record
                    for record in self._records
                    if query in [normalized_name(record["name"]), *record["aliases"]]
                ]

            matches = matching()
            if not matches and not self._complete:
                self.refresh()
                matches = matching()
        if not matches:
            raise ApplicationNotFound(
                "I could not find an exact installed application or alias for this name"
            )
        if len(matches) > 1:
            raise AmbiguousApplicationError(matches)
        return copy.deepcopy(matches[0])

    def register_custom(self, name, path, aliases=None):
        normalized_name(name)
        target = validate_executable(path)
        aliases = aliases or []
        if not isinstance(aliases, list) or len(aliases) > MAX_ALIASES:
            raise ValueError("Use at most 20 aliases")
        aliases = list(dict.fromkeys(normalized_name(alias) for alias in aliases))
        with self._lock:
            if len(self._configuration["custom"]) >= MAX_CUSTOM:
                raise ValueError("Application library already contains 100 custom applications")
            if any(
                record["target"].casefold() == str(target).casefold() for record in self.list_apps()
            ):
                raise ValueError("This executable is already registered")
            identity = "custom_" + uuid.uuid4().hex[:16]
            self._configuration["custom"].append(
                {"id": identity, "name": name.strip(), "aliases": aliases, "target": str(target)}
            )
            self._save_configuration()
            self.refresh()
            return self.resolve(identity)

    def _set(self, identity, key, value):
        with self._lock:
            record = self.resolve(identity)
            overrides = self._configuration["overrides"].setdefault(record["id"], {})
            overrides[key] = value
            if key == "enabled":
                overrides["target"] = record["target"]
                overrides["kind"] = record["kind"]
            self._save_configuration()
            self.refresh(full=self._complete)
            return self.resolve(record["id"])

    def set_enabled(self, identity, enabled, *, expected_target=None, expected_kind=None):
        if not isinstance(enabled, bool):
            raise ValueError("Application permission must be true or false")
        if expected_target is not None and not isinstance(expected_target, str):
            raise ValueError("The reviewed application target must be text")
        if expected_kind is not None and expected_kind not in {"exe", "packaged"}:
            raise ValueError("The reviewed application kind is invalid")
        with self._lock:
            record = self.resolve(identity)
            if (
                expected_target is not None
                and record["target"] != expected_target
                or expected_kind is not None
                and record["kind"] != expected_kind
            ):
                raise PermissionError(
                    "Application target changed after review; refresh the library and review it again"
                )
            if enabled and record["kind"] == "exe":
                validate_executable(record["target"])
            return self._set(identity, "enabled", enabled)

    def set_favorite(self, identity, favorite):
        if not isinstance(favorite, bool):
            raise ValueError("Favorite must be true or false")
        return self._set(identity, "favorite", favorite)

    def set_alias(self, identity, alias):
        alias = normalized_name(alias)
        record = self.resolve(identity)
        if len(record["aliases"]) >= MAX_ALIASES and alias not in record["aliases"]:
            raise ValueError("Application already has 20 aliases")
        with self._lock:
            override = self._configuration["overrides"].setdefault(record["id"], {})
            override["aliases"] = list(dict.fromkeys([*override.get("aliases", []), alias]))
            override["removed_aliases"] = [
                value for value in override.get("removed_aliases", []) if value != alias
            ]
            self._save_configuration()
            self.refresh()
            return self.resolve(record["id"])

    def remove_alias(self, identity, alias):
        alias = normalized_name(alias)
        record = self.resolve(identity)
        with self._lock:
            override = self._configuration["overrides"].setdefault(record["id"], {})
            override["aliases"] = [value for value in override.get("aliases", []) if value != alias]
            override["removed_aliases"] = list(
                dict.fromkeys([*override.get("removed_aliases", []), alias])
            )[:MAX_ALIASES]
            self._save_configuration()
            self.refresh()
            return self.resolve(record["id"])

    def health(self):
        with self._lock:
            if self._records is None:
                self.refresh(full=False)
            records = copy.deepcopy(self._records)
        return {
            "available": os.name == "nt",
            "cached": self._records is not None,
            "complete_catalog": self._complete,
            "applications": len(records),
            "enabled": sum(record["enabled"] for record in records),
            "custom": sum(record["source"] == "custom" for record in records),
            "last_refresh_age_seconds": round(time.monotonic() - self._refreshed, 2)
            if self._refreshed is not None
            else None,
            "errors": list(dict.fromkeys(self._errors))[-5:],
            "scope": "Local catalog only; newly discovered arbitrary applications require permission",
            "shortcut_discovery": "Bounded binary local LinkInfo only; arguments and special shortcut targets are skipped",
        }

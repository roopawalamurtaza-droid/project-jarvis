"""Application discovery is metadata-only and permission changes stay local."""

import json
import struct
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

from jarvis import applications
from jarvis.applications import (
    AmbiguousApplicationError,
    ApplicationNotFound,
    ApplicationRegistry,
    validate_executable,
)


@pytest.fixture
def catalog(tmp_path, monkeypatch):
    monkeypatch.setattr(applications, "_known_candidates", lambda: {})
    monkeypatch.setattr(applications, "_app_paths", lambda: [])
    monkeypatch.setattr(applications, "_start_menu_entries", lambda: [])
    monkeypatch.setattr(applications, "_packaged_entries", lambda: [])
    return ApplicationRegistry(SimpleNamespace(data_dir=tmp_path / "data"))


def exe(tmp_path, name="Editor.exe"):
    path = tmp_path / name
    path.write_bytes(b"MZ-test fixture")
    return path


def test_custom_registration_starts_disabled_and_persists_permissions(catalog, tmp_path):
    record = catalog.register_custom("Portable Editor", exe(tmp_path), ["my editor"])
    assert record["enabled"] is False
    assert record["source"] == "custom"
    assert catalog.resolve(" MY   EDITOR ")["id"] == record["id"]
    catalog.set_enabled(record["id"], True)
    catalog.set_favorite(record["id"], True)
    restored = ApplicationRegistry(catalog.settings)
    assert restored.resolve("my editor")["enabled"] is True
    assert restored.resolve("my editor")["favorite"] is True
    assert "provider" not in catalog.configuration_path.read_text()


def test_alias_add_remove_persists_and_name_remains_resolvable(catalog, tmp_path):
    record = catalog.register_custom("Editor", exe(tmp_path), ["original alias"])
    catalog.set_alias(record["id"], "  Personal   Editor ")
    assert catalog.resolve("personal editor")["id"] == record["id"]
    catalog.remove_alias(record["id"], "original alias")
    with pytest.raises(ApplicationNotFound):
        catalog.resolve("original alias")
    restored = ApplicationRegistry(catalog.settings)
    assert restored.resolve("Editor")["id"] == record["id"]
    assert restored.resolve("personal editor")["id"] == record["id"]


def test_alias_ambiguity_never_selects_first_or_fuzzy(catalog, tmp_path):
    first = catalog.register_custom("First Editor", exe(tmp_path), ["editor"])
    second = catalog.register_custom("Second Editor", exe(tmp_path, "Other.exe"), ["editor"])
    with pytest.raises(AmbiguousApplicationError) as raised:
        catalog.resolve("editor")
    assert {record["id"] for record in raised.value.matches} == {first["id"], second["id"]}
    with pytest.raises(ApplicationNotFound):
        catalog.resolve("first edito")


def test_discovery_is_lazy_cached_and_returns_detached_records(catalog, tmp_path, monkeypatch):
    calls = []
    path = exe(tmp_path)
    monkeypatch.setattr(
        applications,
        "_app_paths",
        lambda: (
            calls.append(True) or [{"name": "Editor", "target": str(path), "source": "app_paths"}]
        ),
    )
    assert calls == []
    records = catalog.list_apps()
    assert len(calls) == 1
    assert records[0]["enabled"] is False
    records[0]["enabled"] = True
    assert catalog.list_apps()[0]["enabled"] is False
    assert len(calls) == 1
    catalog.refresh()
    assert len(calls) == 2


def test_known_supported_locations_keep_canonical_ids(catalog, tmp_path, monkeypatch):
    path = exe(tmp_path, "Code.exe")
    monkeypatch.setattr(applications, "_known_candidates", lambda: {"vscode": [path]})
    record = catalog.resolve("VS Code")
    assert record["id"] == "vscode"
    assert record["enabled"] is True
    assert catalog.resolve("Visual Studio Code")["target"] == str(path)


def test_unknown_registered_path_is_disabled_even_when_known_basename(
    catalog, tmp_path, monkeypatch
):
    path = exe(tmp_path, "chrome.exe")
    monkeypatch.setattr(
        applications,
        "_app_paths",
        lambda: [{"name": "Chrome", "target": str(path), "source": "app_paths"}],
    )
    record = catalog.resolve("chrome")
    assert record["id"] == "chrome"
    assert record["enabled"] is False
    catalog.set_enabled("chrome", True)
    assert catalog.resolve("Google Chrome")["enabled"] is True


def test_reviewed_permission_does_not_follow_canonical_id_to_changed_target(
    catalog, tmp_path, monkeypatch
):
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    targets = [exe(first, "chrome.exe"), exe(second, "chrome.exe")]
    current = [targets[0]]
    monkeypatch.setattr(
        applications,
        "_app_paths",
        lambda: [{"name": "Chrome", "target": str(current[0]), "source": "app_paths"}],
    )
    catalog.set_enabled("chrome", True)
    current[0] = targets[1]
    catalog.refresh()
    assert catalog.resolve("chrome")["enabled"] is False
    assert ApplicationRegistry(catalog.settings).resolve("chrome")["enabled"] is False
    catalog.set_enabled("chrome", True)
    assert catalog.resolve("chrome")["enabled"] is True


def test_unbound_saved_permission_cannot_enable_discovered_application(
    catalog, tmp_path, monkeypatch
):
    target = exe(tmp_path, "chrome.exe")
    monkeypatch.setattr(
        applications,
        "_app_paths",
        lambda: [{"name": "Chrome", "target": str(target), "source": "app_paths"}],
    )
    catalog.configuration_path.parent.mkdir(parents=True)
    catalog.configuration_path.write_text(
        json.dumps({"version": 1, "custom": [], "overrides": {"chrome": {"enabled": True}}})
    )
    restored = ApplicationRegistry(catalog.settings)
    assert restored.resolve("chrome")["enabled"] is False


def test_permission_grant_rejects_target_changed_after_library_preview(
    catalog, tmp_path, monkeypatch
):
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    targets = [exe(first, "chrome.exe"), exe(second, "chrome.exe")]
    current = [targets[0]]
    monkeypatch.setattr(
        applications,
        "_app_paths",
        lambda: [{"name": "Chrome", "target": str(current[0]), "source": "app_paths"}],
    )
    preview = catalog.resolve("chrome")
    current[0] = targets[1]
    catalog.refresh()
    with pytest.raises(PermissionError, match="changed after review"):
        catalog.set_enabled(
            "chrome", True, expected_target=preview["target"], expected_kind=preview["kind"]
        )
    assert catalog.resolve("chrome")["enabled"] is False
    current_preview = catalog.resolve("chrome")
    assert (
        catalog.set_enabled(
            "chrome",
            True,
            expected_target=current_preview["target"],
            expected_kind=current_preview["kind"],
        )["enabled"]
        is True
    )


def test_permission_grant_rejects_changed_or_invalid_preview_kind(catalog, tmp_path):
    preview = catalog.register_custom("Editor", exe(tmp_path))
    with pytest.raises(PermissionError, match="changed after review"):
        catalog.set_enabled(
            preview["id"], True, expected_target=preview["target"], expected_kind="packaged"
        )
    with pytest.raises(ValueError):
        catalog.set_enabled(preview["id"], True, expected_target=123)
    with pytest.raises(ValueError):
        catalog.set_enabled(preview["id"], True, expected_kind="script")
    assert catalog.resolve(preview["id"])["enabled"] is False


def test_deduplicate_same_target_across_sources(catalog, tmp_path, monkeypatch):
    path = exe(tmp_path, "chrome.exe")
    monkeypatch.setattr(applications, "_known_candidates", lambda: {"chrome": [path]})
    monkeypatch.setattr(
        applications,
        "_app_paths",
        lambda: [{"name": "Chrome", "target": str(path), "source": "app_paths"}],
    )
    assert len(catalog.list_apps()) == 1
    assert catalog.resolve("chrome")["source"] == "known_location"


def test_canonical_id_explicitly_selects_supported_variant(catalog, tmp_path, monkeypatch):
    installed = exe(tmp_path, "chrome.exe")
    other_dir = tmp_path / "portable"
    other_dir.mkdir()
    other = exe(other_dir, "chrome.exe")
    monkeypatch.setattr(applications, "_known_candidates", lambda: {"chrome": [installed]})
    monkeypatch.setattr(
        applications,
        "_app_paths",
        lambda: [{"name": "Chrome", "target": str(other), "source": "app_paths"}],
    )
    assert catalog.resolve("chrome")["target"] == str(installed)
    with pytest.raises(AmbiguousApplicationError):
        catalog.resolve("Google Chrome")


def test_only_fixed_known_packaged_identity_is_retained(catalog, monkeypatch):
    monkeypatch.setattr(
        applications,
        "_packaged_entries",
        lambda: [
            {
                "id": "settings",
                "name": "Windows Settings",
                "target": applications.PACKAGED["settings"],
                "kind": "packaged",
                "source": "known_package",
            },
            {
                "id": "evil",
                "name": "Injected",
                "target": "arbitrary!App",
                "kind": "packaged",
                "source": "known_package",
            },
        ],
    )
    records = catalog.list_apps()
    assert len(records) == 1
    assert records[0]["id"] == "settings"
    assert records[0]["enabled"] is True


def test_fixed_store_variant_does_not_duplicate_known_system_launcher_id(
    catalog, tmp_path, monkeypatch
):
    launcher = exe(tmp_path, "notepad.exe")
    monkeypatch.setattr(applications, "_known_candidates", lambda: {"notepad": [launcher]})
    monkeypatch.setattr(
        applications,
        "_packaged_entries",
        lambda: [
            {
                "id": "notepad",
                "name": "Notepad",
                "target": applications.PACKAGED["notepad"],
                "kind": "packaged",
                "source": "known_package",
            }
        ],
    )
    assert len(catalog.list_apps()) == 1
    assert catalog.resolve("Notepad")["target"] == str(launcher)
    assert catalog.resolve("notepad")["kind"] == "exe"


@pytest.mark.parametrize(
    "name",
    [
        "cmd.exe",
        "powershell.exe",
        "python3.12.exe",
        "pythonw.exe",
        "node.exe",
        "regedit.exe",
        "runas.exe",
        "mshta.exe",
        "rundll32.exe",
        "wsl.exe",
        "certutil.exe",
    ],
)
def test_restricted_executable_names_cannot_be_registered(catalog, tmp_path, name):
    with pytest.raises(PermissionError):
        catalog.register_custom("App", exe(tmp_path, name))


@pytest.mark.parametrize(
    "raw",
    [
        "relative.exe",
        "C:\\safe\\test.exe:stream",
        "\\\\server\\share\\app.exe",
        "\\\\?\\C:\\app.exe",
        "C:\\safe\\nul.exe",
        "C:\\safe\\app.cmd",
        "C:\\safe\\app.exe\x00",
    ],
)
def test_unsafe_paths_are_rejected(raw):
    with pytest.raises((PermissionError, OSError)):
        validate_executable(raw)


def test_nonregular_exe_path_is_rejected(tmp_path):
    path = tmp_path / "directory.exe"
    path.mkdir()
    with pytest.raises(PermissionError):
        validate_executable(path)


def test_changed_or_missing_custom_target_is_not_retained(catalog, tmp_path):
    path = exe(tmp_path)
    record = catalog.register_custom("Editor", path)
    path.unlink()
    with pytest.raises(OSError):
        catalog.set_enabled(record["id"], True)
    catalog.refresh()
    assert catalog.list_apps() == []


def test_bad_configuration_uses_safe_defaults(tmp_path, monkeypatch):
    monkeypatch.setattr(applications, "_known_candidates", lambda: {})
    monkeypatch.setattr(applications, "_app_paths", lambda: [])
    monkeypatch.setattr(applications, "_start_menu_entries", lambda: [])
    monkeypatch.setattr(applications, "_packaged_entries", lambda: [])
    (tmp_path / "applications.json").write_text('{"version":1,"custom":"broken","overrides":[]}')
    catalog = ApplicationRegistry(SimpleNamespace(data_dir=tmp_path))
    assert catalog.list_apps() == []
    assert catalog.health()["errors"]


def test_registration_duplicate_and_invalid_boolean_controls(catalog, tmp_path):
    path = exe(tmp_path)
    record = catalog.register_custom("Editor", path)
    with pytest.raises(ValueError):
        catalog.register_custom("Other", path)
    with pytest.raises(ValueError):
        catalog.set_enabled(record["id"], "yes")
    with pytest.raises(ValueError):
        catalog.set_favorite(record["id"], 1)


def test_name_and_alias_bounds(catalog, tmp_path):
    with pytest.raises(ValueError):
        catalog.register_custom("Editor\ncmd", exe(tmp_path))
    with pytest.raises(ValueError):
        catalog.register_custom("Editor", exe(tmp_path), [str(index) for index in range(21)])


def test_search_does_not_modify_resolution_or_catalog(catalog, tmp_path):
    catalog.register_custom("Portable Editor", exe(tmp_path), ["edit"])
    assert len(catalog.list_apps("table")) == 1
    assert catalog.list_apps("Chrome") == []
    assert (
        json.loads(catalog.configuration_path.read_text())["custom"][0]["name"] == "Portable Editor"
    )


def test_reparse_metadata_is_rejected(tmp_path, monkeypatch):
    path = exe(tmp_path)
    original = Path.lstat

    def linked(selected):
        metadata = original(selected)
        if selected == path:
            return SimpleNamespace(st_mode=metadata.st_mode, st_file_attributes=0x400)
        return metadata

    monkeypatch.setattr(Path, "lstat", linked)
    with pytest.raises(PermissionError):
        validate_executable(path)


def test_discovery_metadata_containing_command_arguments_is_never_executable(
    catalog, tmp_path, monkeypatch
):
    path = exe(tmp_path)
    monkeypatch.setattr(
        applications,
        "_app_paths",
        lambda: [{"name": "Editor", "target": f'"{path}" --run shell', "source": "app_paths"}],
    )
    assert catalog.list_apps() == []


def test_canonical_known_resolve_avoids_shortcuts_until_explicit_catalog_request(
    catalog, tmp_path, monkeypatch
):
    target = exe(tmp_path, "chrome.exe")
    scans = []
    monkeypatch.setattr(applications, "_known_candidates", lambda: {"chrome": [target]})
    monkeypatch.setattr(applications, "_start_menu_entries", lambda: scans.append(True) or [])
    assert catalog.resolve("chrome")["target"] == str(target)
    assert catalog.health()["complete_catalog"] is False
    assert scans == []
    catalog.list_apps()
    assert scans == [True]
    assert catalog.health()["complete_catalog"] is True


def test_missing_known_app_checks_shortcuts_and_remains_disabled(catalog, tmp_path, monkeypatch):
    target = exe(tmp_path, "chrome.exe")
    monkeypatch.setattr(
        applications,
        "_start_menu_entries",
        lambda: [{"name": "Chrome", "target": str(target), "source": "start_menu"}],
    )
    assert catalog.resolve("chrome")["enabled"] is False
    assert catalog.health()["complete_catalog"] is True


def shortcut_bytes(target, *, unicode=False, id_list=False, flags=0):
    """A bounded MS-SHLLINK local LinkInfo fixture, not a launched shortcut."""
    header = bytearray(76)
    struct.pack_into("<I", header, 0, 76)
    header[4:20] = uuid.UUID("00021401-0000-0000-C000-000000000046").bytes_le
    struct.pack_into("<I", header, 20, 2 | (1 if id_list else 0) | flags)
    header_size = 36 if unicode else 28
    volume = struct.pack("<4I", 17, 3, 0, 16) + b"\0"
    local = target.encode("ascii", errors="replace") + b"\0"
    suffix = b"\0"
    payload = volume + local + suffix
    if unicode:
        local_unicode = target.encode("utf-16-le") + b"\0\0"
        suffix_unicode = b"\0\0"
        unicode_offsets = (
            header_size + len(payload),
            header_size + len(payload) + len(local_unicode),
        )
        payload += local_unicode + suffix_unicode
    info = struct.pack(
        "<7I",
        header_size + len(payload),
        header_size,
        1,
        header_size,
        header_size + len(volume),
        0,
        header_size + len(volume) + len(local),
    )
    if unicode:
        info += struct.pack("<2I", *unicode_offsets)
    return bytes(header) + (b"\x02\0\0\0" if id_list else b"") + info + payload


@pytest.mark.parametrize(
    "unicode,id_list", [(False, False), (False, True), (True, False), (True, True)]
)
def test_binary_shortcut_discovers_plain_local_exe_without_native_com(
    tmp_path, monkeypatch, unicode, id_list
):
    target = r"C:\Apps\音楽\Editor.exe" if unicode else r"C:\Apps\Editor.exe"
    shortcut = tmp_path / "Editor.lnk"
    shortcut.write_bytes(shortcut_bytes(target, unicode=unicode, id_list=id_list))
    monkeypatch.setattr(
        applications.ctypes, "WinDLL", lambda *a, **k: pytest.fail("Native shortcut COM was loaded")
    )
    assert applications._shortcut_target(shortcut) == {
        "name": "Editor",
        "target": target,
        "source": "start_menu",
    }


@pytest.mark.parametrize("flags", [0x20, 0x100, 0x200, 0x1000, 0x2000, 0x20000, 0x2000000])
def test_binary_shortcut_rejects_arguments_and_special_activation_flags(tmp_path, flags):
    shortcut = tmp_path / "Special.lnk"
    shortcut.write_bytes(shortcut_bytes(r"C:\Apps\Editor.exe", flags=flags))
    assert applications._shortcut_target(shortcut) is None


@pytest.mark.parametrize(
    "target",
    [
        r"\\server\share\Editor.exe",
        r"relative\Editor.exe",
        r"C:\Apps\Run.cmd",
        "C:\\Apps\\Bad\n.exe",
    ],
)
def test_binary_shortcut_rejects_nonlocal_or_nonexe_targets(tmp_path, target):
    shortcut = tmp_path / "Unsafe.lnk"
    shortcut.write_bytes(shortcut_bytes(target))
    assert applications._shortcut_target(shortcut) is None


@pytest.mark.parametrize(
    "fault",
    ["short", "header", "clsid", "size", "offset", "network", "unicode_offset", "oversized"],
)
def test_binary_shortcut_invalid_sizes_offsets_and_headers_fail_closed(tmp_path, fault):
    data = bytearray(shortcut_bytes(r"C:\Apps\Editor.exe", unicode=True))
    if fault == "short":
        data = data[:75]
    elif fault == "header":
        struct.pack_into("<I", data, 0, 77)
    elif fault == "clsid":
        data[4] = 0
    elif fault == "size":
        struct.pack_into("<I", data, 76, len(data) + 1)
    elif fault == "offset":
        struct.pack_into("<I", data, 76 + 28, 12)
    elif fault == "network":
        struct.pack_into("<I", data, 76 + 8, 3)
    elif fault == "unicode_offset":
        struct.pack_into("<I", data, 76 + 32, len(data) + 1)
    elif fault == "oversized":
        data.extend(b"x" * (128 * 1024))
    shortcut = tmp_path / "Malformed.lnk"
    shortcut.write_bytes(data)
    assert applications._shortcut_target(shortcut) is None

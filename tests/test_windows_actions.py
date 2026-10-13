"""Launch acceptance, window visibility and foreground focus are separate facts."""

from types import SimpleNamespace

import pytest

from jarvis import applications, windows_actions
from jarvis.applications import ApplicationRegistry
from jarvis.windows_actions import WindowsActionService, validate_https_url


class Backend:
    def __init__(self):
        self.visible = []
        self.focus_allowed = True
        self.spawned = []
        self.activated = []
        self.opened = []
        self.exit_code = None

    def windows(self, record):
        return list(self.visible)

    def focus(self, hwnd):
        return self.focus_allowed

    def spawn(self, argv):
        self.spawned.append(argv)
        return SimpleNamespace(pid=77, poll=lambda: self.exit_code)

    def activate(self, identity):
        self.activated.append(identity)
        return 88

    def open_default_url(self, url):
        self.opened.append(url)
        return {"evidence": "https_association_accepted", "pid": None}


@pytest.fixture
def actions(tmp_path, monkeypatch):
    monkeypatch.setattr(applications, "_app_paths", lambda: [])
    monkeypatch.setattr(applications, "_start_menu_entries", lambda: [])
    monkeypatch.setattr(applications, "_packaged_entries", lambda: [])
    monkeypatch.setattr(windows_actions.time, "sleep", lambda _: None)
    paths = {}
    for identity, filename in {
        "chrome": "chrome.exe",
        "vscode": "Code.exe",
        "firefox": "firefox.exe",
        "edge": "msedge.exe",
    }.items():
        path = tmp_path / filename
        path.write_bytes(b"MZ-test fixture")
        paths[identity] = [path]
    monkeypatch.setattr(applications, "_known_candidates", lambda: paths)
    registry = ApplicationRegistry(SimpleNamespace(data_dir=tmp_path / "data"))
    backend = Backend()
    return WindowsActionService(registry, backend=backend, verification_timeout=0), backend


def test_running_process_evidence_is_not_window_evidence(actions):
    service, backend = actions
    result = service.launch("chrome")
    assert result["verified"] is True
    assert result["evidence"] == "process_running"
    assert result["window_verified"] is False
    assert result["focus_verified"] is False
    assert result["pid"] == 77
    assert backend.spawned == [[str(service.application_path("chrome"))]]


def test_launcher_success_with_exited_process_is_honest(actions):
    service, backend = actions
    backend.exit_code = 0
    assert service.launch("chrome")["evidence"] == "launcher_accepted"


def test_launcher_failure_is_not_reported_success(actions):
    service, backend = actions
    backend.exit_code = 3
    with pytest.raises(OSError):
        service.launch("chrome")
    assert service.last_result is None


def test_existing_visible_window_is_focused_without_duplicate_launch(actions):
    service, backend = actions
    backend.visible = [{"hwnd": 100, "pid": 42}]
    result = service.launch("chrome")
    assert result["verified"] is True
    assert result["window_verified"] is True
    assert result["focus_verified"] is True
    assert result["evidence"] == "foreground_window_verified"
    assert backend.spawned == []


def test_windows_focus_refusal_does_not_trigger_duplicate_launch(actions):
    service, backend = actions
    backend.visible = [{"hwnd": 100, "pid": 42}]
    backend.focus_allowed = False
    result = service.launch("chrome")
    assert result["verified"] is True
    assert result["window_verified"] is True
    assert result["focus_verified"] is False
    assert result["evidence"] == "visible_window_verified"
    assert "did not grant foreground focus" in result["detail"]
    assert backend.spawned == []


def test_explicit_focus_refusal_retains_actual_visible_window_evidence(actions):
    service, backend = actions
    backend.visible = [{"hwnd": 100, "pid": 42}]
    backend.focus_allowed = False
    result = service.focus("chrome")
    assert result["verified"] is False
    assert result["window_verified"] is True
    assert result["focus_verified"] is False
    assert result["evidence"] == "visible_window_focus_refused"
    assert backend.spawned == []


def test_explicit_focus_cannot_claim_nonexistent_window(actions):
    service, backend = actions
    result = service.focus("vscode")
    assert result["verified"] is False
    assert result["evidence"] == "no_matching_visible_window"
    assert backend.spawned == []


def test_new_window_uses_only_fixed_supported_flags(actions):
    service, backend = actions
    backend.visible = [{"hwnd": 100, "pid": 42}]
    result = service.launch("chrome", new_window=True)
    assert backend.spawned[0][1:] == ["--new-window"]
    assert result["window_verified"] is True
    assert result["new_window_verified"] is False
    assert result["focus_verified"] is False


def test_target_revalidation_prevents_missing_executable_launch(actions):
    service, backend = actions
    path = service.application_path("chrome")
    path.unlink()
    with pytest.raises(OSError):
        service.launch("chrome")
    assert backend.spawned == []


def test_disabled_application_never_calls_backend(actions):
    service, backend = actions
    service.registry.set_enabled("chrome", False)
    with pytest.raises(PermissionError):
        service.launch("chrome")
    with pytest.raises(PermissionError):
        service.focus("chrome")
    assert backend.spawned == []


def test_fixed_packaged_app_uses_native_activation(actions, monkeypatch):
    service, backend = actions
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
            }
        ],
    )
    service.registry.refresh()
    assert service.application_path("settings") is None
    result = service.launch("settings")
    assert result["evidence"] == "packaged_activation_accepted"
    assert result["pid"] == 88
    assert backend.activated == [applications.PACKAGED["settings"]]
    assert backend.spawned == []


def test_default_browser_acceptance_never_claims_page_navigation(actions):
    service, backend = actions
    result = service.open_url("https://example.com/search?q=python", new_window=True)
    assert backend.opened == ["https://example.com/search?q=python"]
    assert result["verified"] is True
    assert result["navigation_verified"] is False
    assert result["new_window_verified"] is False
    assert result["window_verified"] is False


@pytest.mark.parametrize(
    "browser,new_window,flags",
    [
        ("chrome", False, []),
        ("chrome", True, ["--new-window"]),
        ("edge", True, ["--new-window"]),
        ("firefox", False, ["-new-tab"]),
        ("firefox", True, ["-new-window"]),
    ],
)
def test_selected_browser_uses_absolute_exe_and_separate_url_argument(
    actions, browser, new_window, flags
):
    service, backend = actions
    url = "https://example.com/search?q=hello%20world&x=1"
    result = service.open_url(url, browser=browser, new_window=new_window)
    assert backend.spawned == [[str(service.application_path(browser)), *flags, url]]
    assert result["navigation_verified"] is False


@pytest.mark.parametrize(
    "url",
    [
        "file:///C:/Users/test",
        "javascript:alert(1)",
        "http://example.com",
        "https://user:password@example.com",
        "https://localhost",
        "https://127.0.0.1",
        "https://[::1]",
        "https://10.0.0.1",
        "https://example.local",
        "https://example.com:8443",
        "https://example.com\\@evil.com",
        "https://example.com/%0d%0a",
        "https://example.com/ bad",
        "https://example%2ecom",
        "https://-bad.example",
        "https://example.com\x00",
    ],
)
def test_unsafe_urls_never_reach_native_backend(actions, url):
    service, backend = actions
    with pytest.raises((ValueError, PermissionError)):
        service.open_url(url)
    assert backend.opened == []
    assert backend.spawned == []


def test_unknown_browser_or_nonboolean_flags_rejected(actions):
    service, backend = actions
    with pytest.raises(ValueError):
        service.open_url("https://example.com", browser="cmd")
    with pytest.raises(ValueError):
        service.launch("chrome", prefer_focus="yes")
    with pytest.raises(ValueError):
        service.open_url("https://example.com", new_window=1)
    assert backend.spawned == []


def test_https_url_preserves_encoded_search_and_unicode_domain():
    assert (
        validate_https_url("https://example.com/?q=a%2Bb%26c") == "https://example.com/?q=a%2Bb%26c"
    )
    assert validate_https_url("https://bücher.de/") == "https://bücher.de/"


def test_allowed_unicode_search_query_reaches_native_browser_handoff(actions):
    from jarvis.browser_actions import BrowserActionService

    service, backend = actions
    browser = BrowserActionService(SimpleNamespace(), service)
    result = browser.search_web("😀" * 500)
    assert result["launch_verified"] is True
    assert 4096 < len(result["url"]) <= 8192
    assert backend.opened == [result["url"]]
    assert result["navigation_verified"] is False


def test_native_spawn_always_shell_false(monkeypatch):
    calls = []
    monkeypatch.setattr(
        windows_actions.subprocess, "Popen", lambda argv, **kwargs: calls.append((argv, kwargs))
    )
    backend = object.__new__(windows_actions._NativeWindowsBackend)
    backend.spawn([r"C:\Apps\Editor.exe"])
    assert calls[0][1]["shell"] is False
    assert calls[0][1]["stdin"] == windows_actions.subprocess.DEVNULL

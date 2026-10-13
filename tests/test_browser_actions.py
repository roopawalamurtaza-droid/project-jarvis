"""URL validation, permission boundaries, and actual launcher evidence contracts."""

from copy import deepcopy
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest

from jarvis.browser_actions import BrowserActionService, validate_external_url


class Launcher:
    def __init__(self):
        self.calls = []
        self.result = {"verified": True, "evidence": "launcher_accepted", "pid": 321}

    def open_url(self, url, *, browser="default", new_window=False):
        self.calls.append((url, browser, new_window))
        return self.result


@pytest.fixture
def system():
    settings = SimpleNamespace(
        browser_enabled=True,
        default_browser="default",
        default_search_engine="google",
        browser_new_window=False,
        preferred_websites={},
    )
    launcher = Launcher()
    return BrowserActionService(settings, launcher), settings, launcher


@pytest.mark.parametrize(
    ("target", "expected"),
    [
        (" YouTube ", "https://www.youtube.com/"),
        ("GOOGLE   MAPS", "https://www.google.com/maps"),
        ("Gmail", "https://mail.google.com/"),
        ("GitHub", "https://github.com/"),
        ("NVIDIA drivers", "https://www.nvidia.com/en-us/drivers/"),
        ("Flutter installation guide", "https://docs.flutter.dev/install"),
        ("python.org", "https://python.org/"),
        (
            "https://PYTHON.ORG:443/downloads/?x=one%20two#guide",
            "https://python.org/downloads/?x=one%20two#guide",
        ),
        ("openai.com/api", "https://openai.com/api"),
        ("https://xn--bcher-kva.de/", "https://xn--bcher-kva.de/"),
    ],
)
def test_resolves_only_site_names_or_valid_addresses(system, target, expected):
    service, _, launcher = system
    assert service.resolve_url(target) == expected
    assert launcher.calls == []


@pytest.mark.parametrize(
    "target",
    [
        "",
        " ",
        "Python tutorials",
        "please search Google",
        "Chrome",
        "file:///C:/Windows",
        "javascript:alert(1)",
        "data:text/html,test",
        "ms-settings:privacy",
        "shell:AppsFolder",
        "http://python.org/",
        "ftp://python.org/",
        "//python.org/path",
        "https://",
        "https://user:password@python.org/",
        "https://@python.org/",
        "https://python.org@evil.com/",
        "https://python.org:80/",
        "https://python.org:11434/",
        "https://python.org:/",
        "https://python.org:0443/",
        "https://python.org:bad/",
        "https://python.org./",
        "https://localhost/",
        "https://localhost.company.com/",
        "https://api.localdomain.com/",
        "https://my-pc.local/",
        "https://private.internal/",
        "https://workstation.home/",
        "https://office.lan/",
        "https://hidden.onion/",
        "https://foo.test/",
        "https://foo.invalid/",
        "https://example.com/",
        "https://www.example.net/",
        "https://example.org/",
        "https://metadata.google.internal/",
        "https://169.254.169.254/",
        "https://127.0.0.1/",
        "https://10.0.0.1/",
        "https://192.168.1.1/",
        "https://8.8.8.8/",
        "https://[::1]/",
        "https://[2606:4700:4700::1111]/",
        "https://2130706433/",
        "https://127.1/",
        "https://0177.0.0.1/",
        "https://0x7f000001/",
        "https://a..com/",
        "https://-bad.com/",
        "https://bad-.com/",
        "https://foo_bar.com/",
        "https://bücher.de/",
        "https://xn--a.com/",
        "https://xn--abc-.com/",
        "https://python.org/a b",
        'https://python.org/"thing"',
        "https://python.org/<script>",
        "https://python.org\\evil.com/",
        "https://python.org/%5cwindows",
        "https://python.org/%255cwindows",
        "https://python.org/%00",
        "https://python.org/%0A",
        "https://python.org/%250D",
        "https://python.org/%7f",
        "https://python.org/%252525250A",
        "https://python.org/%252525252525252525250A",
        "https://python.org/%C2%85",
        "https://python.org/%EF%BB%BF",
        "https://python.org/%no",
        "https://python.org/%",
        "https://python.org/\n",
        "https://python.org/\x00",
        "https://python.org/\u202e",
        "https://" + "a" * 64 + ".com",
        "https://python.org/" + "x" * 2048,
    ],
)
def test_rejects_unsafe_ambiguous_and_nonwebsite_targets_without_launch(system, target):
    service, _, launcher = system
    with pytest.raises(ValueError):
        service.open_website(target)
    assert launcher.calls == []


@pytest.mark.parametrize("target", [None, 123, True, ["python.org"], {"url": "python.org"}])
def test_wrong_types_are_not_coerced(system, target):
    service, _, launcher = system
    with pytest.raises(ValueError):
        service.open_website(target)
    assert not launcher.calls


def test_unknown_hosts_and_spoofed_known_hosts_require_approval(system):
    service, _, _ = system
    assert not service.requires_approval("GitHub")
    assert not service.requires_approval("https://github.com/issues")
    assert service.requires_approval("https://github.com.suspicious.tld/")
    assert service.requires_approval("https://unknown-public-domain.com/")
    assert service.requires_approval("https://app.github.com/")
    assert service.requires_approval("https://xn--bcher-kva.de/")


def test_saved_aliases_are_validated_and_do_not_make_unknown_hosts_trusted(system):
    service, settings, launcher = system
    settings.preferred_websites = {
        "My Documents": "https://docs.flutter.dev/install",
        "Company Portal": "https://company-portal.com/home",
    }
    assert service.resolve_url("my   documents") == "https://docs.flutter.dev/install"
    assert not service.requires_approval("My Documents")
    assert service.requires_approval("Company Portal")
    assert launcher.calls == []
    settings.preferred_websites = {"YouTube": "https://another-public-domain.com/"}
    assert service.requires_approval("YouTube")


@pytest.mark.parametrize(
    "mapping",
    [
        {"Company": "http://company.com"},
        {"Private": "https://127.0.0.1"},
        {"Empty": ""},
        {"": "https://python.org"},
        {"123": "https://python.org"},
        {"Bad\nName": "https://python.org"},
        {"x" * 81: "https://python.org"},
        {"A": "https://python.org", " a ": "https://github.com"},
        {"site" + str(i): "https://python.org" for i in range(101)},
        [],
        None,
    ],
)
def test_invalid_preferred_sites_fail_closed(system, mapping):
    service, settings, launcher = system
    settings.preferred_websites = mapping
    with pytest.raises(ValueError):
        service.open_website("GitHub")
    assert not launcher.calls
    assert service.health()["status"] == "configuration_error"


def test_launch_evidence_does_not_claim_navigation_or_mutate_shared_result(system):
    service, settings, launcher = system
    launcher.result.update(
        navigation_verified=True, window_verified=True, detail="Internal launch detail"
    )
    before_settings = deepcopy(vars(settings))
    before_result = deepcopy(launcher.result)
    result = service.open_website("YouTube")
    assert launcher.calls == [("https://www.youtube.com/", "default", False)]
    assert result["verified"] is True
    assert result["launch_verified"] is True
    assert result["navigation_verified"] is False
    assert result["window_verified"] is True
    assert result["evidence"] == "launcher_accepted"
    assert result["pid"] == 321
    assert "page loading" in result["detail"]
    assert vars(settings) == before_settings
    assert launcher.result == before_result


def test_uses_validated_settings_and_per_call_options(system):
    service, settings, launcher = system
    settings.default_browser = "edge"
    settings.browser_new_window = True
    service.open_website("GitHub")
    service.open_website("GitHub", browser="firefox", new_window=False)
    assert [call[1:] for call in launcher.calls] == [("edge", True), ("firefox", False)]
    assert settings.default_browser == "edge"
    assert settings.browser_new_window is True


@pytest.mark.parametrize("browser", ["powershell", "chrome --bad", "CHROME", "", False, [], 42])
def test_rejects_browser_argument_injection(system, browser):
    service, _, launcher = system
    with pytest.raises(ValueError):
        service.open_website("GitHub", browser=browser)
    assert not launcher.calls


@pytest.mark.parametrize("new_window", ["true", 1, 0, [], {}])
def test_window_preference_requires_actual_boolean(system, new_window):
    service, _, launcher = system
    with pytest.raises(ValueError):
        service.open_website("GitHub", new_window=new_window)
    assert not launcher.calls


@pytest.mark.parametrize("engine", ["google", "bing", "duckduckgo", "youtube"])
def test_search_encodes_user_query_as_data_at_fixed_provider(system, engine):
    service, _, launcher = system
    query = "Python & C++ / 日本語 ?x=1#heading --flag"
    result = service.search_web(query, engine=engine, browser="chrome")
    parsed = urlsplit(launcher.calls[0][0])
    parameter = "search_query" if engine == "youtube" else "q"
    assert parse_qs(parsed.query) == {parameter: [query]}
    assert parsed.fragment == ""
    assert launcher.calls[0][1:] == ("chrome", False)
    assert result["engine"] == engine
    assert result["navigation_verified"] is False
    assert result["research_completed"] is False
    assert result["action"] == "search_web"


def test_search_uses_configured_engine_and_trims_outer_spaces(system):
    service, settings, launcher = system
    settings.default_search_engine = "youtube"
    result = service.search_web("  Flutter docs  ")
    assert result["url"] == "https://www.youtube.com/results?search_query=Flutter+docs"
    assert len(launcher.calls) == 1


@pytest.mark.parametrize(
    "query", ["", " ", None, 3, "x" * 501, "x\n", "x\x00", "x\u202e", "\ud800"]
)
def test_invalid_search_queries_do_not_launch(system, query):
    service, _, launcher = system
    with pytest.raises(ValueError):
        service.search_web(query)
    assert not launcher.calls


@pytest.mark.parametrize("engine", ["https://evil.com/?q=", "shell", "Google", "", 1, []])
def test_search_engine_is_not_an_arbitrary_url_or_command(system, engine):
    service, _, launcher = system
    with pytest.raises(ValueError):
        service.search_web("Python", engine=engine)
    assert not launcher.calls


@pytest.mark.parametrize("enabled", [False, "true", 1, None])
def test_browser_disable_cannot_be_coerced_or_bypassed(system, enabled):
    service, settings, launcher = system
    settings.browser_enabled = enabled
    assert service.health()["status"] == "disabled"
    with pytest.raises(PermissionError):
        service.open_website("YouTube")
    with pytest.raises(PermissionError):
        service.search_web("Python")
    assert not launcher.calls


def test_missing_launcher_or_browser_error_is_reported_without_false_success(system):
    service, _, launcher = system

    def missing(*args, **kwargs):
        raise FileNotFoundError("Selected browser is not installed")

    launcher.open_url = missing
    with pytest.raises(FileNotFoundError, match="not installed"):
        service.open_website("GitHub", browser="firefox")
    service.windows_actions = object()
    assert service.health()["status"] == "unavailable"
    with pytest.raises(RuntimeError, match="unavailable"):
        service.open_website("GitHub")


@pytest.mark.parametrize("result", [{"verified": False}, {"verified": "true"}, {}])
def test_unverified_launch_stays_unverified(system, result):
    service, _, launcher = system
    launcher.result = result
    actual = service.open_website("GitHub")
    assert actual["verified"] is False
    assert actual["launch_verified"] is False
    assert actual["navigation_verified"] is False


def test_invalid_launcher_result_is_an_error(system):
    service, _, launcher = system
    launcher.result = True
    with pytest.raises(RuntimeError, match="invalid result"):
        service.open_website("GitHub")


def test_health_is_explicit_about_limits_and_does_not_launch(system):
    service, _, launcher = system
    health = service.health()
    assert health["enabled"]
    assert health["launcher_available"]
    assert health["default_browser"] == "default"
    assert health["default_search_engine"] == "google"
    assert health["navigation_observation_supported"] is False
    assert health["research_supported"] is False
    assert health["last_error"] is None
    assert not launcher.calls


def test_contract_works_with_old_settings_without_mutating_them():
    settings = SimpleNamespace()
    launcher = Launcher()
    service = BrowserActionService(settings, launcher)
    assert service.open_website("GitHub")["verified"]
    assert service.search_web("Python")["engine"] == "google"
    assert vars(settings) == {}


def test_direct_validation_is_alias_free():
    with pytest.raises(ValueError):
        validate_external_url("YouTube")
    assert validate_external_url("https://github.com/") == "https://github.com/"

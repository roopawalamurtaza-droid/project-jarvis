"""Explicit website/search actions using ordinary Windows browser activation.

This adapter does not inspect tabs, attach to authenticated profiles, read pages,
or execute instructions from web content. A verified launcher request is not
proof that a page loaded. Unknown destinations still need dispatcher approval.
"""

from __future__ import annotations

import ipaddress
import os
import re
import unicodedata
from typing import Any
from urllib.parse import unquote, urlencode, urlsplit, urlunsplit

# Exact destinations, rather than a broad suffix allowlist: "github.com.evil.tld"
# and arbitrary subdomains do not inherit a familiar site's trust decision.
KNOWN_WEBSITES = {
    "youtube": "https://www.youtube.com/",
    "github": "https://github.com/",
    "gmail": "https://mail.google.com/",
    "google": "https://www.google.com/",
    "google maps": "https://www.google.com/maps",
    "maps": "https://www.google.com/maps",
    "nvidia": "https://www.nvidia.com/",
    "nvidia drivers": "https://www.nvidia.com/en-us/drivers/",
    "python": "https://www.python.org/",
    "python documentation": "https://docs.python.org/3/",
    "flutter": "https://flutter.dev/",
    "flutter documentation": "https://docs.flutter.dev/",
    "flutter installation guide": "https://docs.flutter.dev/install",
    "visual studio code": "https://code.visualstudio.com/",
    "vscode website": "https://code.visualstudio.com/",
    "microsoft": "https://www.microsoft.com/",
    "bing": "https://www.bing.com/",
    "duckduckgo": "https://duckduckgo.com/",
    "wikipedia": "https://www.wikipedia.org/",
    "stackoverflow": "https://stackoverflow.com/",
    "stack overflow": "https://stackoverflow.com/",
}
TRUSTED_HOSTS = frozenset(urlsplit(url).hostname for url in KNOWN_WEBSITES.values())
BROWSERS = frozenset({"default", "chrome", "edge", "firefox"})
SEARCH_ENGINES = {
    "google": ("https://www.google.com/search", "q"),
    "bing": ("https://www.bing.com/search", "q"),
    "duckduckgo": ("https://duckduckgo.com/", "q"),
    "youtube": ("https://www.youtube.com/results", "search_query"),
}
_SPECIAL_SUFFIXES = frozenset(
    {
        "localhost",
        "local",
        "localdomain",
        "internal",
        "intranet",
        "home",
        "lan",
        "corp",
        "test",
        "invalid",
        "example",
        "onion",
        "arpa",
        "alt",
    }
)
_RESERVED_NAMES = frozenset(
    {
        "example.com",
        "example.net",
        "example.org",
        "metadata.google.internal",
        "instance-data.ec2.internal",
    }
)
_DNS_LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\Z")
_PERCENT_ESCAPE = re.compile(r"%[0-9a-fA-F]{2}")


def _text(value: Any, label: str, limit: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError(f"{label} must contain 1 to {limit} characters")
    if any(unicodedata.category(character).startswith("C") for character in value):
        raise ValueError(f"{label} contains a control or formatting character")
    return value.strip()


def validate_external_url(value: str) -> str:
    """Validate a public HTTPS address without fetching it or resolving DNS.

    Host validation rejects local/special names and IP literals. It cannot prove
    a public domain's current DNS records or eventual redirect destination; the
    ordinary browser retains responsibility for navigation and its protections.
    """
    target = _text(value, "Website address", 2048)
    if not target.isascii() or any(character.isspace() for character in target):
        raise ValueError("Use an ASCII website address without spaces; use search for words")
    if any(character in target for character in '\\<>"'):
        raise ValueError("Backslashes and ambiguous URL characters are forbidden")
    # Keep encoded controls/backslashes out of the Windows/browser handoff too.
    if "%" in _PERCENT_ESCAPE.sub("", target):
        raise ValueError("Website address contains an invalid percent escape")
    decoded = target
    for _ in range(8):
        following = unquote(decoded, errors="strict")
        if any(unicodedata.category(character).startswith("C") for character in following):
            raise ValueError("Encoded control characters are forbidden")
        if "\\" in following:
            raise ValueError("Encoded backslashes are forbidden")
        if following == decoded:
            break
        decoded = following
    else:
        raise ValueError("Excessively nested website URL encoding is forbidden")
    if "://" not in target:
        target = "https://" + target
    try:
        parsed = urlsplit(target)
        host = parsed.hostname
        port = parsed.port
    except ValueError:
        raise ValueError("Website address is malformed") from None
    if parsed.scheme != "https" or not host:
        raise ValueError("Only external HTTPS website addresses are supported")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("Website addresses must not contain credentials")
    if port not in {None, 443}:
        raise ValueError("Only the standard HTTPS port is supported")
    host = host.lower()
    if parsed.netloc.lower() not in {host, f"{host}:443"}:
        raise ValueError("Website authority is ambiguous")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise ValueError("IP addresses, including private and metadata addresses, are forbidden")
    labels = host.split(".")
    if (
        len(host) > 253
        or len(labels) < 2
        or not all(_DNS_LABEL.fullmatch(label) for label in labels)
        or not re.fullmatch(r"[a-z]{2,63}|xn--[a-z0-9-]{1,59}", labels[-1])
    ):
        raise ValueError("Use a valid public domain; use search for a search term")
    try:
        for label in labels:
            if label.startswith("xn--"):
                decoded_label = label.encode("ascii").decode("idna")
                if decoded_label.encode("idna").decode("ascii").lower() != label or any(
                    unicodedata.category(character).startswith("C") for character in decoded_label
                ):
                    raise ValueError("International domain encoding is invalid")
    except UnicodeError:
        raise ValueError("International domain encoding is invalid") from None
    if labels[-1] in _SPECIAL_SUFFIXES or any(
        host == name or host.endswith("." + name) for name in _RESERVED_NAMES
    ):
        raise ValueError("Local, reserved, and metadata destinations are forbidden")
    if any(label in {"localhost", "localdomain"} for label in labels):
        raise ValueError("Local destination names are forbidden")
    return urlunsplit(("https", host, parsed.path or "/", parsed.query, parsed.fragment))


class BrowserActionService:
    """Bounded action adapter; the caller must apply its one-use approvals."""

    def __init__(self, settings, windows_actions):
        self.settings = settings
        self.windows_actions = windows_actions

    def _sites(self) -> dict[str, str]:
        supplied = getattr(self.settings, "preferred_websites", {})
        if not isinstance(supplied, dict) or len(supplied) > 100:
            raise ValueError("Configure up to 100 preferred websites")
        result = {}
        for name, address in supplied.items():
            alias = " ".join(_text(name, "Website alias", 80).casefold().split())
            if not any(character.isalpha() for character in alias):
                raise ValueError("Website aliases must contain a name")
            if alias in result:
                raise ValueError("Website aliases must be unique ignoring case and spacing")
            result[alias] = validate_external_url(address)
        return result

    def resolve_url(self, target: str) -> str:
        value = _text(target, "Website target", 2048)
        alias = " ".join(value.casefold().split())
        sites = self._sites()
        if alias in sites:
            return sites[alias]
        if alias in KNOWN_WEBSITES:
            return KNOWN_WEBSITES[alias]
        return validate_external_url(value)

    def requires_approval(self, target: str) -> bool:
        """Unknown exact hosts require dispatcher approval even for saved aliases."""
        return urlsplit(self.resolve_url(target)).hostname not in TRUSTED_HOSTS

    def _enabled(self) -> None:
        if getattr(self.settings, "browser_enabled", True) is not True:
            raise PermissionError("Browser actions are disabled in Settings")
        if not callable(getattr(self.windows_actions, "open_url", None)):
            raise RuntimeError("The local Windows browser launcher is unavailable")

    def _browser(self, browser: str | None) -> str:
        selected = (
            getattr(self.settings, "default_browser", "default") if browser is None else browser
        )
        if not isinstance(selected, str) or selected not in BROWSERS:
            raise ValueError("Choose default, chrome, edge, or firefox as the browser")
        return selected

    def _new_window(self, new_window: bool | None) -> bool:
        selected = (
            getattr(self.settings, "browser_new_window", False)
            if new_window is None
            else new_window
        )
        if type(selected) is not bool:
            raise ValueError("New window preference must be true or false")
        return selected

    def _open(self, url: str, browser: str | None, new_window: bool | None) -> dict:
        self._enabled()
        selected = self._browser(browser)
        separate = self._new_window(new_window)
        result = self.windows_actions.open_url(url, browser=selected, new_window=separate)
        if not isinstance(result, dict):
            raise RuntimeError("The Windows browser launcher returned an invalid result")
        verified = result.get("verified") is True
        # Ignore any navigation claim from a launcher: this component has no
        # page-observation channel. Preserve measured process/window evidence.
        result = dict(result)
        result.update(
            verified=verified,
            launch_verified=verified,
            url=url,
            browser=selected,
            new_window_requested=separate,
            navigation_verified=False,
            research_completed=False,
            evidence=result.get("evidence", "launch_unverified"),
            detail=(
                "Browser launch request verified; page loading and active-tab navigation "
                "were not observed."
                if verified
                else "Browser launch request could not be verified; page loading was not observed."
            ),
        )
        return result

    def open_website(
        self, target: str, *, browser: str | None = None, new_window: bool | None = None
    ) -> dict:
        """Open a validated target after the dispatcher has granted permission."""
        url = self.resolve_url(target)
        result = self._open(url, browser, new_window)
        result["action"] = "open_website"
        return result

    def search_web(
        self,
        query: str,
        *,
        engine: str | None = None,
        browser: str | None = None,
        new_window: bool | None = None,
    ) -> dict:
        """Open encoded search results; this performs no research or page reading."""
        text = _text(query, "Search query", 500)
        selected = (
            getattr(self.settings, "default_search_engine", "google") if engine is None else engine
        )
        if not isinstance(selected, str) or selected not in SEARCH_ENGINES:
            raise ValueError("Choose google, bing, duckduckgo, or youtube as the search engine")
        base, parameter = SEARCH_ENGINES[selected]
        url = base + "?" + urlencode({parameter: text})
        result = self._open(url, browser, new_window)
        result.update(action="search_web", engine=selected, research_completed=False)
        return result

    def health(self) -> dict:
        enabled = getattr(self.settings, "browser_enabled", True) is True
        launcher = callable(getattr(self.windows_actions, "open_url", None))
        try:
            browser = self._browser(None)
            engine = getattr(self.settings, "default_search_engine", "google")
            if engine not in SEARCH_ENGINES:
                raise ValueError("The default search engine is invalid")
            new_window = self._new_window(None)
            count = len(self._sites())
            error = None
        except (ValueError, TypeError) as exc:
            browser, engine, new_window, count = None, None, None, 0
            error = str(exc)
        available = enabled and launcher and os.name == "nt" and error is None
        return {
            "enabled": enabled,
            "status": (
                "disabled"
                if not enabled
                else "configuration_error"
                if error
                else "ready"
                if available
                else "unavailable"
            ),
            "windows_platform": os.name == "nt",
            "desktop_session_verified": False,
            "launcher_available": launcher,
            "default_browser": browser,
            "default_search_engine": engine,
            "new_window_requested": new_window,
            "preferred_website_count": count,
            "navigation_observation_supported": False,
            "research_supported": False,
            "last_error": error,
            "detail": "Ordinary browser activation; installed-browser availability is checked on launch.",
        }

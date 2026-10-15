"""Owned, bounded browser observation and navigation for the computer-use dispatcher.

The dispatcher supplies permission decisions. This adapter never attaches a
personal profile, reads cookies, submits forms, or treats page text as authority.
Network checks are defense in depth, not an operating-system network sandbox.
"""

from __future__ import annotations

import ipaddress
import queue
import re
import socket
import threading
import time
from concurrent.futures import Future, TimeoutError
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

from .browser_actions import validate_external_url

_ACTIONS = frozenset(
    {
        "search_open",
        "navigate",
        "read",
        "scroll",
        "back",
        "forward",
        "tabs",
        "new_tab",
        "switch_tab",
        "close_tab",
        "click",
        "type",
        "select",
        "human_mode",
    }
)
_MAX_TABS = 8
_MAX_TARGETS = 60
_TARGET_AGE = 30.0
_RISKY = re.compile(
    r"\b(?:delete|remove|purchase|buy|checkout|pay|transfer|send|submit|publish|deploy|"
    r"logout|sign.?out|sign.?in|login|register|password|token|secret|credential|"
    r"subscribe|unsubscribe|approve|authorize|upload|download)\b",
    re.I,
)
_SECRET = re.compile(
    r"(?:\b(?:sk|ghp|github_pat|AIza)[-_][A-Za-z0-9_-]{12,}|"
    r"\b(?:api[_ -]?key|password|access[_ -]?token|secret)\s*[:=]\s*\S+)",
    re.I,
)


def _safe_text(value: Any, limit: int = 500) -> str:
    text = str(value or "")
    text = "".join(c for c in text if c in "\n\t" or ord(c) >= 32)
    text = _SECRET.sub("[redacted]", text[:limit])
    return re.sub(r"https://[^\s<>\"']+", lambda match: _safe_url(match.group()), text)


def _safe_url(value: str) -> str:
    """Diagnostics exclude credentials, fragments, and all query values."""
    try:
        parsed = urlsplit(value)
        if parsed.scheme != "https" or not parsed.hostname:
            return "about:blank" if value == "about:blank" else "[unavailable]"
        return urlunsplit(("https", parsed.hostname, parsed.path[:500], "", ""))
    except ValueError:
        return "[unavailable]"


def _host_match(value: str, expected: str) -> bool:
    try:
        host = urlsplit(value).hostname or ""
    except ValueError:
        return False
    base = expected.removeprefix("www.")
    return host in {base, "www." + base}


class _UserInteractionRequired(PermissionError):
    """Authentication and website challenges must be handled by the human."""


class _PublicDNS:
    """One bounded resolver worker; timeout never starts additional threads."""

    def __init__(self):
        self._jobs: queue.Queue = queue.Queue(maxsize=1)
        self._cache: dict[str, tuple[float, tuple[str, ...]]] = {}
        self._closed = threading.Event()
        self._thread = threading.Thread(target=self._run, name="jarvis-browser-dns", daemon=True)
        self._thread.start()

    def _run(self):
        while not self._closed.is_set():
            try:
                item = self._jobs.get(timeout=0.1)
            except queue.Empty:
                continue
            host, future = item
            if future.cancelled():
                continue
            try:
                addresses = tuple(
                    {row[4][0] for row in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)}
                )
                if not addresses or any(
                    not ipaddress.ip_address(address).is_global for address in addresses
                ):
                    raise PermissionError("The website resolves to a private or special network")
                if not future.done():
                    future.set_result(addresses)
            except Exception:
                if not future.done():
                    future.set_exception(PermissionError("Public website DNS verification failed"))

    def validate(self, url: str) -> str:
        value = validate_external_url(url)
        host = urlsplit(value).hostname
        cached = self._cache.get(host)
        if cached and time.monotonic() - cached[0] < 15:
            return value
        future: Future = Future()
        try:
            self._jobs.put_nowait((host, future))
        except queue.Full:
            raise TimeoutError("Browser DNS verification is busy") from None
        try:
            addresses = future.result(timeout=3)
        except TimeoutError:
            future.cancel()
            raise TimeoutError("Browser DNS verification timed out") from None
        if len(self._cache) >= 200:
            self._cache.clear()
        self._cache[host] = (time.monotonic(), addresses)
        return value

    def close(self):
        self._closed.set()


@dataclass
class _Job:
    action: str
    arguments: dict
    future: Future = field(default_factory=Future)
    cancel: threading.Event = field(default_factory=threading.Event)
    external_cancel: Any = None
    manual_epoch: int = 0


class BrowserComputerService:
    """One Playwright owner thread shared safely by successive Qt workers.

    Calls have a 60-second total budget; individual browser operations use short
    timeouts. Stop is cooperative and observed at request boundaries and between
    steps. It cannot interrupt a native Playwright call before that call's timeout.
    """

    def __init__(self, settings, scoped_path, applications=None):
        self.settings = settings
        self.scoped_path = scoped_path
        self.applications = applications
        self._application_registry = applications
        self._executable_path = None
        self._jobs: queue.Queue = queue.Queue(maxsize=1)
        self._lock = threading.Lock()
        self._submit_lock = threading.Lock()
        self._closing = threading.Event()
        self._active: _Job | None = None
        self._thread: threading.Thread | None = None
        self._playwright = None
        self._browser = None
        self._context = None
        self._channel = None
        self._page = None
        self._pages: dict[str, Any] = {}
        self._targets: dict[str, dict] = {}
        self._observation = 0
        self._tab_serial = 0
        self._blocked = 0
        self._manual_until = 0.0
        self._manual_epoch = 0
        self._last_challenge = False
        self._dns: _PublicDNS | None = None
        self._metadata = {
            "status": "not_started",
            "ready": False,
            "active": False,
            "isolated_profile": True,
            "personal_session_attached": False,
            "last_error": None,
            "tab_count": 0,
            "browser": None,
            "current_url": None,
            "current_title": None,
            "current_tab_id": None,
            "network_policy": "public_https_read_only",
            "manual_mode": False,
        }

    def status(self) -> dict:
        with self._lock:
            result = dict(self._metadata)
        result["enabled"] = all(
            getattr(self.settings, flag, False) is True
            for flag in (
                "browser_enabled",
                "desktop_actions_enabled",
                "computer_use_enabled",
                "browser_automation_enabled",
            )
        )
        return result

    @property
    def browser_name(self) -> str:
        selected = self._channel or getattr(self.settings, "default_browser", "default")
        return "chrome" if selected == "default" else selected

    def _set_status(self, **updates):
        with self._lock:
            self._metadata.update(updates)

    @staticmethod
    def _validate(action, arguments):
        if not isinstance(action, str) or action not in _ACTIONS or not isinstance(arguments, dict):
            raise ValueError("Unsupported browser action or arguments")
        allowed = {
            "search_open": {"query", "expected_host", "browser"},
            "navigate": {"url", "browser"},
            "new_tab": {"url", "browser"},
            "scroll": {"direction"},
            "switch_tab": {"tab_id"},
            "close_tab": {"tab_id"},
            "click": {"target_id"},
            "type": {"target_id", "text"},
            "select": {"target_id", "value"},
            "read": set(),
            "tabs": set(),
            "back": set(),
            "forward": set(),
            "human_mode": {"enabled"},
        }[action]
        if set(arguments) - allowed:
            raise ValueError("Unknown browser arguments; arbitrary selectors are forbidden")
        if action == "human_mode" and type(arguments.get("enabled")) is not bool:
            raise ValueError("Manual browser interaction permission must be true or false")
        if action in {"navigate", "new_tab"}:
            validate_external_url(arguments.get("url"))
        if "browser" in arguments and arguments["browser"] not in {"chrome", "edge", "default"}:
            raise ValueError("Computer browser supports installed Chrome or Edge")
        if action == "search_open":
            query = arguments.get("query")
            if (
                not isinstance(query, str)
                or not query.strip()
                or len(query) > 500
                or any(ord(c) < 32 for c in query)
            ):
                raise ValueError("Search query must contain 1 to 500 readable characters")
            host = arguments.get("expected_host", "python.org")
            if (
                not isinstance(host, str)
                or urlsplit("https://" + host + "/").hostname != host
                or validate_external_url("https://" + host + "/") != "https://" + host + "/"
            ):
                raise ValueError("Expected result must be an exact public host")
        if action == "scroll" and arguments.get("direction") not in {"up", "down"}:
            raise ValueError("Scroll direction must be up or down")
        for key in ("tab_id", "target_id"):
            if key in arguments and (
                not isinstance(arguments[key], str)
                or not re.fullmatch(r"[a-z0-9-]{1,64}", arguments[key])
            ):
                raise ValueError("Use an observed browser identifier")
        for key in ("text", "value"):
            if key in arguments and (
                not isinstance(arguments[key], str)
                or len(arguments[key]) > 2000
                or any(ord(c) < 32 and c not in "\n\t" for c in arguments[key])
            ):
                raise ValueError("Browser input must be bounded text")
        required = {
            "switch_tab": "tab_id",
            "click": "target_id",
            "type": "text",
            "select": "value",
        }.get(action)
        if required and required not in arguments:
            raise ValueError("Required browser argument is missing")
        if action in {"click", "type", "select"} and "target_id" not in arguments:
            raise ValueError("Use a freshly observed browser target identifier")

    def call(self, action: str, arguments: dict, *, cancel=None) -> dict:
        self._validate(action, arguments)
        if action == "human_mode" and arguments["enabled"] is False:
            # Revocation always works with permissions off, while busy, or before launch.
            self._revoke_manual()
            return {
                "action": action,
                "verified": True,
                "status": "completed",
                "evidence": "manual_network_permission_revoked",
                "detail": "Owned browser returned to read-only network policy",
            }
        if getattr(self.settings, "browser_enabled", True) is not True:
            raise PermissionError("Browser actions are disabled in Settings")
        if getattr(self.settings, "desktop_actions_enabled", False) is not True:
            raise PermissionError("Desktop actions are disabled in Settings")
        if (
            getattr(self.settings, "computer_use_enabled", False) is not True
            or getattr(self.settings, "browser_automation_enabled", False) is not True
        ):
            raise PermissionError("Enable computer use and browser automation in Settings")
        if self._closing.is_set():
            return self._failure(action, "closed", "The browser service is closed")
        if not self._submit_lock.acquire(blocking=False):
            return self._failure(action, "busy", "Another browser action is running")
        try:
            with self._lock:
                if self._active is not None:
                    return self._failure(
                        action, "busy", "A stopped browser action is still settling"
                    )
            if self._thread is None:
                self._thread = threading.Thread(
                    target=self._run, name="jarvis-browser-owner", daemon=True
                )
                self._thread.start()
            with self._lock:
                epoch = self._manual_epoch
            job = _Job(action, dict(arguments), external_cancel=cancel, manual_epoch=epoch)
            self._jobs.put_nowait(job)
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline:
                if self._cancelled(job):
                    job.cancel.set()
                try:
                    return job.future.result(timeout=0.1)
                except TimeoutError:
                    continue
            job.cancel.set()
            return self._failure(
                action, "timeout", "The browser action exceeded its bounded time budget"
            )
        finally:
            self._submit_lock.release()

    @staticmethod
    def _failure(action, code, detail):
        return {
            "action": action,
            "verified": False,
            "status": "cancelled" if code == "cancelled" else "failed",
            "evidence": code,
            "detail": detail,
        }

    def _cancelled(self, job):
        external = job.external_cancel
        return (
            self._closing.is_set()
            or job.cancel.is_set()
            or (
                external is not None
                and callable(getattr(external, "is_set", None))
                and external.is_set()
            )
        )

    def _check(self):
        if self._active is not None and self._cancelled(self._active):
            raise InterruptedError("Browser operation cancelled")
        if (
            self._active is not None
            and self._active.action == "human_mode"
            and self._active.arguments.get("enabled") is True
            and self._active.manual_epoch != self._manual_epoch
        ):
            raise InterruptedError("Manual browser permission was revoked while waiting")
        if not all(
            getattr(self.settings, flag, False) is True
            for flag in (
                "browser_enabled",
                "desktop_actions_enabled",
                "computer_use_enabled",
                "browser_automation_enabled",
            )
        ):
            raise PermissionError("Computer browser permission was revoked")
        if self._application_registry is not None and self._channel is not None:
            record = self._application_registry.resolve(self._channel)
            if (
                record.get("enabled") is not True
                or record.get("kind") != "exe"
                or record.get("target") != self._executable_path
            ):
                raise PermissionError("The exact browser installation permission changed")

    def stop(self) -> None:
        self._revoke_manual()
        with self._lock:
            active = self._active
        if active is not None:
            active.cancel.set()
        try:
            queued = self._jobs.get_nowait()
        except queue.Empty:
            return
        queued.cancel.set()
        queued.future.set_result(
            self._failure(queued.action, "cancelled", "Queued browser action cancelled")
        )

    def close(self) -> None:
        self._closing.set()
        self.stop()
        if self._thread is not None and self._thread is not threading.current_thread():
            self._thread.join(timeout=18)
        self._set_status(status="closed", active=False, ready=False)

    def _run(self):
        try:
            while not self._closing.is_set():
                try:
                    job = self._jobs.get(timeout=0.1)
                except queue.Empty:
                    if self._manual_until:
                        if time.monotonic() >= self._manual_until:
                            self._revoke_manual()
                            self._set_status(
                                status="stopped",
                                last_error="Manual browser network permission expired after five minutes",
                            )
                        else:
                            try:
                                self._check()
                                if (
                                    self._page is None
                                    or self._page.is_closed()
                                    or not self._browser.is_connected()
                                ):
                                    raise RuntimeError("The owned browser was closed")
                                # Pump on the owner thread so browser gestures and routed
                                # CAPTCHA requests keep working while the agent is paused.
                                self._page.wait_for_timeout(50)
                            except Exception:
                                self._revoke_manual()
                                self._set_status(
                                    status="browser_closed",
                                    ready=False,
                                    last_error="Manual interaction stopped because the owned browser closed or permission changed",
                                )
                    continue
                with self._lock:
                    self._active = job
                self._set_status(active=True, status="running")
                try:
                    self._check()
                    if job.action not in {"human_mode", "read"}:
                        self._revoke_manual()
                    result = self._perform(job.action, job.arguments)
                    self._check()
                    self._set_status(
                        status="awaiting_user" if self._manual_until else "ready",
                        ready=self._context is not None,
                        last_error=None,
                    )
                except InterruptedError:
                    self._revoke_manual()
                    result = self._failure(
                        job.action, "cancelled", "Browser action stopped; no further steps were run"
                    )
                    self._set_status(status="stopped")
                except _UserInteractionRequired:
                    result = self._failure(
                        job.action,
                        "user_interaction_required",
                        "The website requires human login or CAPTCHA interaction; no protection was bypassed",
                    )
                    result["user_interaction_required"] = True
                    self._set_status(status="awaiting_user", last_error=result["detail"])
                except PermissionError as exc:
                    result = self._failure(
                        job.action,
                        "permission_blocked",
                        _safe_text(str(exc), 300)
                        or "Unsafe network, protected form, or unobserved target was blocked",
                    )
                    self._set_status(status="blocked", last_error=result["detail"])
                except (TimeoutError, socket.timeout):
                    result = self._failure(
                        job.action, "timeout", "Browser or DNS operation timed out"
                    )
                    self._set_status(status="error", last_error=result["detail"])
                except Exception as exc:
                    code = (
                        "dependency_unavailable"
                        if isinstance(exc, ImportError)
                        else "timeout"
                        if type(exc).__name__ == "TimeoutError"
                        else "browser_error"
                    )
                    detail = (
                        "Install the packaged Playwright runtime and Chrome or Edge"
                        if code == "dependency_unavailable"
                        else "Browser operation timed out"
                        if code == "timeout"
                        else "Browser action failed; no successful completion was claimed"
                    )
                    result = self._failure(job.action, code, detail)
                    self._set_status(status="error", last_error=detail)
                with self._lock:
                    self._active = None
                self._set_status(active=False)
                if not job.future.done():
                    job.future.set_result(result)
        finally:
            self._cleanup()
            if self._dns is not None:
                self._dns.close()
                self._dns = None

    def _cleanup(self):
        self._revoke_manual()
        for resource in (self._context, self._browser):
            try:
                if resource is not None:
                    resource.close()
            except Exception:
                pass
        try:
            if self._playwright is not None:
                self._playwright.stop()
        except Exception:
            pass
        self._playwright = self._browser = self._context = self._page = None
        self._executable_path = None
        self._channel = None
        self._pages.clear()
        self._targets.clear()
        self._last_challenge = False
        self._set_status(
            ready=False, tab_count=0, current_tab_id=None, current_url=None, current_title=None
        )

    def _revoke_manual(self):
        with self._lock:
            self._manual_epoch += 1
            self._manual_until = 0.0
            self._metadata.update(manual_mode=False, network_policy="public_https_read_only")

    def _ensure_browser(self, selected=None):
        selected = selected or self._channel or getattr(self.settings, "default_browser", "default")
        if selected == "default":
            selected = "chrome"
        if selected not in {"chrome", "edge"}:
            raise ValueError("Use installed Chrome or Edge for computer browser actions")
        if self._browser is not None and self._browser.is_connected():
            if selected != self._channel:
                raise ValueError(
                    "Close the current owned browser before selecting a different browser"
                )
            return
        # A user-closed or crashed owned browser gets one new isolated context.
        self._cleanup()
        from playwright.sync_api import sync_playwright

        from .applications import ApplicationRegistry, validate_executable

        if self._application_registry is None:
            self._application_registry = ApplicationRegistry(self.settings)
        applications = self._application_registry
        record = applications.resolve(selected)
        if record.get("enabled") is not True or record.get("kind") != "exe":
            raise PermissionError("The exact browser installation is not enabled")
        executable = validate_executable(record["target"])
        if executable.name.casefold() != ("chrome.exe" if selected == "chrome" else "msedge.exe"):
            raise PermissionError("The enabled browser target has an unexpected executable name")
        self._executable_path = record["target"]
        self._channel = selected
        if self._dns is None:
            self._dns = _PublicDNS()
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(
            executable_path=str(executable),
            headless=False,
            timeout=12000,
            chromium_sandbox=True,
        )
        self._context = self._browser.new_context(
            accept_downloads=False,
            service_workers="block",
            permissions=[],
            viewport={"width": 1280, "height": 800},
            ignore_https_errors=False,
        )
        self._context.set_default_timeout(6000)
        self._context.set_default_navigation_timeout(15000)
        self._context.route("**/*", self._route)
        # Service workers are blocked, and WebSockets are not needed for read-only work.
        self._context.route_web_socket("**/*", lambda ws: ws.close())
        self._context.on("page", self._register_page)
        self._channel = selected
        self._page = self._context.new_page()
        self._register_page(self._page)
        self._set_status(ready=True, browser=selected, status="ready")

    def _route(self, route):
        request = route.request
        try:
            self._check()
            methods = {"GET", "HEAD"}
            if self._manual_until and time.monotonic() < self._manual_until:
                methods.add("POST")
            if request.method not in methods:
                raise PermissionError("Forms and state-changing network methods are blocked")
            self._dns.validate(request.url)
        except Exception:
            self._blocked += 1
            route.abort("blockedbyclient")
            return
        route.continue_()

    def _register_page(self, page):
        if page in self._pages.values():
            return
        if len(self._pages) >= _MAX_TABS:
            page.close()
            return
        self._tab_serial += 1
        tab_id = "tab-" + str(self._tab_serial)
        self._pages[tab_id] = page
        page.on("dialog", lambda dialog: dialog.dismiss())
        page.on("download", lambda download: download.cancel())
        self._set_status(tab_count=len(self._pages))

    def _live_page(self):
        self._pages = {key: page for key, page in self._pages.items() if not page.is_closed()}
        self._set_status(tab_count=len(self._pages))
        if self._page is None or self._page.is_closed():
            self._page = next(iter(self._pages.values()), None)
        if self._page is None:
            self._page = self._context.new_page()
            self._register_page(self._page)
        return self._page

    def _guard_page(self, page):
        if page.url != "about:blank":
            self._dns.validate(page.url)
        title = _safe_text(page.title(), 300)
        self._set_status(current_url=_safe_url(page.url), current_title=title)
        if (
            re.search(
                r"captcha|unusual traffic|verify (?:you are|that you)|sign in|log in", title, re.I
            )
            or "/sorry/" in page.url
        ):
            self._last_challenge = True
            raise _UserInteractionRequired(
                "User interaction is required for an authentication or CAPTCHA challenge"
            )
        self._last_challenge = False

    def _goto(self, page, url):
        self._check()
        target = self._dns.validate(url)
        self._targets.clear()
        response = page.goto(target, wait_until="domcontentloaded", timeout=15000)
        self._check()
        self._guard_page(page)
        if response is None or response.status >= 400:
            raise RuntimeError("The page did not return a successful navigation response")
        return response.status

    def _snapshot(self, page, *, text=True):
        self._check()
        self._guard_page(page)
        self._observation += 1
        observation_id = self._observation
        self._targets.clear()
        # These fixed scripts only observe DOM; no page-provided code/selectors run.
        observed = page.evaluate("""() => {
            const nodes = Array.from(document.querySelectorAll('a[href],input,textarea,select'));
            return nodes.slice(0, 600).filter(e => {
                const r=e.getBoundingClientRect(); const s=getComputedStyle(e);
                return r.width>0 && r.height>0 && s.visibility!=='hidden' && s.display!=='none';
            }).slice(0, 60).map(e => ({tag:e.tagName.toLowerCase(), type:e.type||'',
                name:(e.getAttribute('aria-label')||e.getAttribute('placeholder')||e.innerText||e.name||'').slice(0,160),
                href:e.tagName==='A'?e.href:null, id:e.id||null,
                autocomplete:e.autocomplete||'', disabled:!!e.disabled,
                options:e.tagName==='SELECT'?Array.from(e.options).slice(0,40).map(o=>({value:o.value.slice(0,160),label:o.label.slice(0,160)})):[]
            })); }""")
        targets = []
        for index, item in enumerate(observed[:_MAX_TARGETS]):
            if item.get("disabled") or item.get("type") in {
                "password",
                "hidden",
                "file",
                "submit",
                "button",
            }:
                continue
            if _RISKY.search(
                " ".join(str(item.get(key) or "") for key in ("name", "autocomplete", "href"))
            ):
                continue
            tag = item.get("tag")
            if tag == "a":
                try:
                    validate_external_url(item.get("href"))
                except (ValueError, TypeError):
                    continue
            elif tag == "input" and item.get("type") not in {"search", "text", "email", "url"}:
                continue
            target_id = f"target-{observation_id}-{index}"
            item.update(page=page, url=page.url, observed_at=time.monotonic())
            self._targets[target_id] = item
            result = {
                "target_id": target_id,
                "kind": tag,
                "name": _safe_text(item.get("name"), 160),
            }
            if tag == "a":
                result["url"] = _safe_url(item["href"])
            if tag == "select":
                result["options"] = item.get("options", [])
            targets.append(result)
        body = ""
        if text:
            body = page.evaluate("""() => {
                const copy=document.body?document.body.cloneNode(true):document.createElement('div');
                copy.querySelectorAll('input,textarea,select,script,style,noscript,[contenteditable],iframe').forEach(e=>e.remove());
                return (copy.innerText||copy.textContent||'').slice(0,10000);
            }""")
        title = _safe_text(page.title(), 300)
        url = _safe_url(page.url)
        tab_id = next(key for key, value in self._pages.items() if value is page)
        self._set_status(
            current_url=url, current_title=title, current_tab_id=tab_id, tab_count=len(self._pages)
        )
        return {
            "url": url,
            "title": title,
            "tab_id": tab_id,
            "observation_id": observation_id,
            "targets": targets,
            "content": _safe_text(body, 10000),
            "untrusted_content": True,
            "blocked_request_count": self._blocked,
        }

    def _target(self, target_id, kinds):
        item = self._targets.get(target_id)
        if (
            item is None
            or item.get("tag") not in kinds
            or time.monotonic() - item["observed_at"] > _TARGET_AGE
        ):
            raise PermissionError("Target is missing, stale, or unsupported")
        page = self._live_page()
        if item["page"] is not page or item["url"] != page.url:
            raise PermissionError("The active page has changed")
        self._guard_page(page)
        # Re-resolve the exact observed semantic identity; never accept a selector.
        if item["tag"] == "a":
            locator = page.get_by_role("link", name=item["name"], exact=True)
            if locator.count() != 1 or locator.get_attribute("href") is None:
                raise PermissionError("The navigation target is ambiguous or changed")
            href = locator.evaluate("e => e.href")
            if href != item["href"]:
                raise PermissionError("The navigation target changed")
            self._dns.validate(href)
        else:
            name = item["name"]
            locator = page.get_by_label(name, exact=True)
            if locator.count() == 0:
                locator = page.get_by_placeholder(name, exact=True)
            if not name or locator.count() != 1:
                raise PermissionError("The input target is ambiguous or changed")
            fresh = locator.evaluate(
                "e=>({tag:e.tagName.toLowerCase(),type:e.type||'',autocomplete:e.autocomplete||'',disabled:!!e.disabled})"
            )
            if (
                fresh["tag"] != item["tag"]
                or fresh["type"] != item["type"]
                or fresh["disabled"]
                or _RISKY.search(fresh["autocomplete"])
            ):
                raise PermissionError("The input target changed or became protected")
        if not locator.is_visible() or not locator.is_enabled():
            raise PermissionError("The target is not available")
        return page, locator, item

    def _perform(self, action, arguments):
        if action == "human_mode" and not arguments["enabled"]:
            self._revoke_manual()
            return {
                "action": action,
                "verified": True,
                "status": "completed",
                "evidence": "manual_network_permission_revoked",
                "detail": "Owned browser returned to read-only network policy",
            }
        self._ensure_browser(arguments.get("browser"))
        page = self._live_page()
        if action == "human_mode":
            if not self._last_challenge:
                raise PermissionError(
                    "Manual network permission is available only for an observed login or CAPTCHA challenge"
                )
            self._targets.clear()
            with self._lock:
                if self._active is not None and self._active.manual_epoch != self._manual_epoch:
                    raise InterruptedError("Manual browser permission was revoked while waiting")
                self._manual_until = time.monotonic() + 300
                self._metadata.update(
                    manual_mode=True,
                    network_policy="public_https_manual_post",
                    status="awaiting_user",
                )
            return {
                "action": action,
                "verified": True,
                "status": "awaiting_user",
                "evidence": "explicit_manual_network_permission_enabled",
                "expires_in_seconds": 300,
                "detail": "Agent actions are paused. The owned public-HTTPS browser may send POST requests for five minutes, including page scripts; human gestures cannot be cryptographically distinguished. Stop or the next automatic action revokes this grant.",
                "page": {
                    "url": _safe_url(page.url),
                    "title": _safe_text(page.title(), 300),
                    "untrusted_content": True,
                },
            }
        result = {
            "action": action,
            "verified": True,
            "status": "completed",
            "evidence": "observed_browser_state",
        }
        if action in {"navigate", "new_tab"}:
            if action == "new_tab":
                if len(self._pages) >= _MAX_TABS:
                    raise ValueError("The owned browser tab limit was reached")
                page = self._context.new_page()
                self._register_page(page)
                self._page = page
            result["http_status"] = self._goto(page, arguments["url"])
            result["navigation_verified"] = True
        elif action == "search_open":
            expected = arguments.get("expected_host", "python.org")
            search_url = "https://www.google.com/search?" + urlencode(
                {"q": arguments["query"].strip()}
            )
            self._goto(page, search_url)
            self._check()
            links = page.locator("a").filter(has=page.locator("h3"))
            count = min(links.count(), 100)
            matches = {}
            for index in range(count):
                link = links.nth(index)
                if not link.is_visible():
                    continue
                href = link.evaluate("e => e.href")
                parsed = urlsplit(href)
                resolved = href
                if parsed.hostname == "www.google.com" and parsed.path == "/url":
                    parameters = parse_qs(parsed.query)
                    resolved = (parameters.get("q") or parameters.get("url") or [""])[0]
                if _host_match(resolved, expected):
                    self._dns.validate(resolved)
                    canonical = urlunsplit(urlsplit(resolved)._replace(fragment=""))
                    matches.setdefault(canonical, (link, resolved))
            if not matches:
                return self._failure(
                    action,
                    "result_not_found",
                    "No visible search result matched the exact requested public host; no guessed result was opened",
                )
            if len(matches) > 1:
                result = self._failure(
                    action,
                    "ambiguous_results",
                    "Several distinct results matched the requested host; read the current search page and choose an observed target",
                )
                result["page"] = self._snapshot(page, text=False)
                return result
            selected = next(iter(matches.values()))
            self._targets.clear()
            self._check()
            selected[0].click(timeout=6000)
            page.wait_for_load_state("domcontentloaded", timeout=15000)
            self._check()
            self._guard_page(page)
            if not _host_match(page.url, expected):
                return self._failure(
                    action,
                    "result_navigation_unverified",
                    "The selected result did not reach the requested exact host",
                )
            result.update(
                search_url=_safe_url(search_url),
                selected_result=_safe_url(selected[1]),
                expected_host=expected,
                search_verified=True,
                navigation_verified=True,
            )
        elif action == "scroll":
            self._guard_page(page)
            before = page.evaluate("() => ({x:scrollX,y:scrollY})")
            page.mouse.wheel(0, 650 if arguments["direction"] == "down" else -650)
            page.wait_for_timeout(150)
            after = page.evaluate("() => ({x:scrollX,y:scrollY})")
            result.update(before=before, after=after, moved=before != after)
        elif action in {"back", "forward"}:
            self._targets.clear()
            response = (page.go_back if action == "back" else page.go_forward)(
                wait_until="domcontentloaded", timeout=15000
            )
            if response is None:
                return self._failure(
                    action,
                    "no_history",
                    "The owned tab has no navigation history in that direction",
                )
            self._guard_page(page)
            result["navigation_verified"] = response.status < 400
            result["verified"] = response.status < 400
        elif action == "tabs":
            result["tabs"] = [
                {
                    "tab_id": key,
                    "url": _safe_url(value.url),
                    "title": _safe_text(value.title(), 300),
                    "active": value is page,
                }
                for key, value in self._pages.items()
            ]
        elif action == "switch_tab":
            page = self._pages.get(arguments["tab_id"])
            if page is None or page.is_closed():
                raise PermissionError("The observed tab is no longer available")
            page.bring_to_front()
            self._page = page
        elif action == "close_tab":
            target = self._pages.get(arguments.get("tab_id")) if arguments.get("tab_id") else page
            if target is None or target.is_closed():
                raise PermissionError("The observed tab is no longer available")
            target.close(run_before_unload=False)
            self._pages = {
                key: value for key, value in self._pages.items() if not value.is_closed()
            }
            self._targets.clear()
            result.update(tab_closed=True, remaining_tabs=len(self._pages))
            if not self._pages:
                self._page = None
                self._set_status(
                    tab_count=0, current_url=None, current_title=None, current_tab_id=None
                )
                return result
            self._page = next(iter(self._pages.values()))
            page = self._page
        elif action in {"click", "type", "select"}:
            page, locator, item = self._target(
                arguments.get("target_id"),
                {"a"}
                if action == "click"
                else {"input", "textarea"}
                if action == "type"
                else {"select"},
            )
            self._check()
            if action == "click":
                locator.click(timeout=6000)
                page.wait_for_load_state("domcontentloaded", timeout=15000)
                self._guard_page(page)
            elif action == "type":
                if _SECRET.search(arguments["text"]):
                    raise PermissionError("Secret input is unsupported")
                locator.fill(arguments["text"], timeout=6000)
                result["verified"] = locator.input_value(timeout=3000) == arguments["text"]
                result["evidence"] = "input_value_compared_without_disclosure"
            else:
                if arguments["value"] not in {
                    option["value"] for option in item.get("options", [])
                }:
                    raise PermissionError("The option was not observed")
                values = locator.select_option(value=arguments["value"], timeout=6000)
                result["verified"] = values == [arguments["value"]]
        result["page"] = self._snapshot(page, text=action == "read")
        result["detail"] = "Actual owned browser state observed; webpage content is untrusted"
        return result

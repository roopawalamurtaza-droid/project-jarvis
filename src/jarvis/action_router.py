"""Parse explicit human action requests into a bounded, validated plan.

Provider prose, saved memories, webpages and receipts never enter this parser.
Context identifies a previously requested browser, never an observed active tab.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .browser_actions import KNOWN_WEBSITES

MAX_ACTIONS = 6
APP_ALIASES = {
    "google chrome": "chrome",
    "chrome": "chrome",
    "vs code": "vscode",
    "visual studio code": "vscode",
    "vscode": "vscode",
    "notepad": "notepad",
    "calculator": "calculator",
    "calc": "calculator",
    "file explorer": "explorer",
    "windows explorer": "explorer",
    "explorer": "explorer",
    "task manager": "task_manager",
    "windows settings": "settings",
    "microsoft edge": "edge",
    "edge": "edge",
    "firefox": "firefox",
    "spotify": "spotify",
    "discord": "discord",
    "android studio": "android_studio",
    "steam": "steam",
    "telegram": "telegram",
}
BROWSERS = {"chrome", "edge", "firefox"}


@dataclass(frozen=True)
class ActionPlan:
    steps: list[dict] = field(default_factory=list)
    answer: str | None = None
    needs_model: bool = False


def command_text(message):
    text = message.strip()
    text = re.sub(r"^(?:hey\s+)?jarvis[\s,:]+", "", text, flags=re.I)
    for _ in range(4):
        shortened = re.sub(
            r"^(?:now\s+|and\s+|then\s+|also\s+|please\s+|(?:can|could|would) you\s+)",
            "",
            text,
            flags=re.I,
        )
        if shortened == text:
            break
        text = shortened
    return text.strip()


def _name(value):
    value = re.sub(r"\s+(?:too|as well|please|for me)[.!?]*$", "", value.strip(), flags=re.I)
    return value.rstrip(".!? ").strip("\"'")


def parse_actions(message, settings, *, context=None, store=None):
    """Return a plan, a truthful local answer, or None for ordinary chat."""
    text = command_text(message)
    lower = text.lower().rstrip(".!? ")
    context = context or {}
    if lower in {"what applications did you open", "which applications did you open"}:
        records = context.get("applications", [])
        return ActionPlan(
            answer=(
                "Recorded launch or focus requests in this conversation: "
                + ", ".join(records)
                + ". This is task history, not a list of currently running windows."
                if records
                else "No verified application request is recorded in this conversation."
            )
        )
    if re.match(r"^(?:research|investigate)\s+", lower):
        return ActionPlan(
            answer="Live web research is not connected. I can open a browser search if you ask; I cannot claim to have read or compared the pages."
        )
    if lower.startswith("find ") and not re.match(r"^find (?:the )?official\b", lower):
        return ActionPlan(
            answer="Do you mean a browser search or an approved local folder? Say ‘search for’ to open web results. Local recursive file finding is not implemented."
        )
    if re.match(r"^(?:use (?:the )?tools to|execute (?:this|the) request|carry out)\s+", lower):
        return ActionPlan(needs_model=True)
    if lower in {
        "list installed applications",
        "show installed applications",
        "what apps are installed",
    }:
        return ActionPlan(
            [{"tool": "list_applications", "arguments": {}, "label": "List application library"}]
        )
    if lower in {
        "report cpu usage",
        "report ram usage",
        "show system status",
        "what is my cpu usage",
        "what is my ram usage",
    }:
        return ActionPlan(
            [{"tool": "get_system_status", "arguments": {}, "label": "Measure system status"}]
        )
    # The existing scoped folder/project commands keep their existing path policy.
    simple_open = re.fullmatch(r"(?:open|launch|start)\s+(.+)", lower)
    if simple_open and not re.search(r"[,]|\band\b", simple_open[1]):
        target = _name(simple_open[1]).removeprefix("my ")
        if target in {
            "downloads",
            "downloads folder",
            "documents",
            "documents folder",
            "desktop",
            "desktop folder",
            "development environment",
            "flutter project",
        }:
            return None
        if store and any(
            m.get("category") == "project" and m.get("key", "").lower() == target
            for m in store.memories()
        ):
            return None

    another_tab = bool(re.match(r"^open another tab and\s+", text, flags=re.I))
    if another_tab:
        text = re.sub(r"^open another tab and\s+", "", text, flags=re.I)
    parts = re.split(
        r"\s+(?:and\s+then|then|and)\s+(?=(?:open|launch|start|search|look up|switch to|focus)\b)",
        text,
        flags=re.I,
    )
    selected_browser = context.get("browser", getattr(settings, "default_browser", "default"))
    steps = []
    last_browser_step = None
    for part in parts:
        part = command_text(part)
        if re.match(r"^open another tab and\s+", part, flags=re.I):
            part = re.sub(r"^open another tab and\s+", "", part, flags=re.I)
        search = re.fullmatch(
            r"(?:search|look up|find)\s+(?:(google|bing|duckduckgo|youtube)\s+)?(?:for\s+)?(.+)",
            part,
            flags=re.I,
        )
        if search:
            query = search[2].strip().rstrip(".!? ")
            if not query:
                return ActionPlan(answer="What should I search for?")
            args = {
                "query": query,
                "engine": (
                    search[1] or getattr(settings, "default_search_engine", "google")
                ).lower(),
                "browser": selected_browser,
            }
            steps.append(
                {
                    "tool": "search_web",
                    "arguments": args,
                    "label": "Open browser search",
                    "depends_on": [last_browser_step] if last_browser_step is not None else [],
                }
            )
            continue
        operation = re.fullmatch(
            r"(open|launch|start|bring up|switch to|focus)\s+(.+)", part, flags=re.I
        )
        if not operation:
            return ActionPlan(needs_model=True) if steps else None
        verb, raw = operation[1].lower(), _name(operation[2])
        if not raw:
            return ActionPlan(answer="Which application or website should I open?")
        # Comma/and lists contain application names, never command-line arguments.
        names = [
            n.strip() for n in re.split(r",\s*(?:and\s+)?|\s+and\s+", raw, flags=re.I) if n.strip()
        ]
        for raw_name in names:
            name = _name(raw_name)
            configured_sites = getattr(settings, "preferred_websites", {})
            alias = (
                name
                if name.lower() in configured_sites
                else re.sub(r"^(?:the official|the)\s+", "", name, flags=re.I)
            )
            alias = re.sub(r"\s+(?:website|site)$", "", alias, flags=re.I)
            lowered = alias.lower()
            if lowered.startswith("my ") and lowered[3:] in APP_ALIASES:
                lowered = lowered[3:]
                alias = alias[3:]
            sites = {**KNOWN_WEBSITES, **getattr(settings, "preferred_websites", {})}
            explicit_site = bool(re.search(r"\b(?:website|site)\s*$", name, flags=re.I))
            website = (
                (lowered in sites and (lowered not in APP_ALIASES or explicit_site))
                or lowered.startswith("https://")
                or (
                    not re.search(r"\s", lowered)
                    and "." in lowered
                    and not lowered.endswith(".exe")
                )
            )
            if website and verb in {"open", "launch", "start"}:
                steps.append(
                    {
                        "tool": "open_website",
                        "arguments": {"target": alias, "browser": selected_browser},
                        "label": "Open website",
                    }
                )
                continue
            app = APP_ALIASES.get(lowered, alias)
            if lowered in {"browser", "web browser"}:
                app = selected_browser
                if app == "default":
                    return ActionPlan(
                        answer="Choose Chrome, Edge or Firefox in Application Library first; I cannot infer which Windows browser executable you mean."
                    )
            if app in BROWSERS:
                selected_browser = app
                last_browser_step = len(steps)
            steps.append(
                {
                    "tool": "focus_app" if verb in {"switch to", "focus"} else "open_app",
                    "arguments": {"app": app},
                    "label": f"{verb.title()} {alias}",
                }
            )
            if len(steps) > MAX_ACTIONS:
                return ActionPlan(answer=f"Use at most {MAX_ACTIONS} actions in one request.")
    if len(steps) > MAX_ACTIONS:
        return ActionPlan(answer=f"Use at most {MAX_ACTIONS} actions in one request.")
    return ActionPlan(steps) if steps else None

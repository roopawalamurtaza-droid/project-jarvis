"""Human-only routing for the first observed computer-use workflows.

Neither web content nor model prose is passed to this parser. Ambiguous goals
are clarified rather than reduced to an accidental partial launch command.
"""

from __future__ import annotations

import ctypes
import os
import re
from pathlib import Path

from .action_router import ActionPlan, command_text

OFFICIAL_SITES = {
    "python": "www.python.org",
    "nvidia": "www.nvidia.com",
    "flutter": "docs.flutter.dev",
    "github": "github.com",
}


def desktop_directory() -> Path:
    if os.name != "nt":
        raise RuntimeError("The Windows Desktop folder is unavailable on this system.")
    buffer = ctypes.create_unicode_buffer(32768)
    shell = ctypes.WinDLL("shell32")
    shell.SHGetFolderPathW.argtypes = [
        ctypes.c_void_p,
        ctypes.c_int,
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_wchar_p,
    ]
    shell.SHGetFolderPathW.restype = ctypes.c_long
    if shell.SHGetFolderPathW(None, 0x10, None, 0, buffer) != 0 or not buffer.value:
        raise RuntimeError("Windows could not identify the configured Desktop folder.")
    return Path(buffer.value)


def _step(tool, arguments, label):
    return ActionPlan([{"tool": tool, "arguments": arguments, "label": label}])


def spoken_filename(value):
    """Honor explicitly spoken punctuation; never invent a missing separator."""
    value = re.sub(r"\s+(?:hyphen|dash)\s+", "-", value, flags=re.I)
    value = re.sub(r"\s+underscore\s+", "_", value, flags=re.I)
    value = re.sub(r"\s+(?:dot|period)\s+(?:t\s*x\s*t|text)\b", ".txt", value, flags=re.I)
    return value


def parse_computer_actions(message, settings, *, context=None):
    text = command_text(message).strip()
    context = context or {}
    normalized = text.casefold().rstrip(".!? ")
    if normalized in {
        "let me solve the captcha",
        "let me solve the browser challenge",
        "pause browser for me",
    }:
        return _step(
            "browser_user_interaction",
            {"enabled": True},
            "Allow human browser challenge interaction",
        )
    if normalized in {"continue browsing", "resume browser automation"}:
        return _step(
            "browser_user_interaction", {"enabled": False}, "End human browser interaction"
        )
    sequence = re.split(
        r"\s+(?:and then|then)\s+(?=(?:open|launch) (?:notepad|chrome|edge)\b)", text, flags=re.I
    )
    if len(sequence) > 1:
        if len(sequence) > 3:
            return ActionPlan(
                answer="Use at most three computer workflows per request. No action ran."
            )
        steps = []
        for part in sequence:
            plan = parse_computer_actions(part, settings, context=context)
            if plan is None or plan.answer or plan.needs_model:
                return ActionPlan(
                    answer=plan.answer
                    if plan and plan.answer
                    else "I could not represent the whole computer workflow safely. No action ran."
                )
            for step in plan.steps:
                step = dict(step)
                step["depends_on"] = [len(steps) - 1] if steps else []
                steps.append(step)
        return ActionPlan(steps)
    # Quotes make literal document content distinct from the action instruction.
    note = re.fullmatch(
        r"(?:open|launch) notepad[,\s]+(?:and\s+)?write (?:a (?:short )?note saying\s+)?"
        r"(['\"‘’“”])(.+?)(['\"‘’“”])[,\s]+(?:and\s+)?save (?:it|the note) "
        r"(?:on my desktop as\s+(.+)|(?:to|as)\s+(.+))",
        text,
        re.I | re.S,
    )
    if note is None:
        # STT commonly omits quotation marks. The explicit 'note saying ... and
        # save it' grammar still separates literal content from the destination.
        spoken = re.fullmatch(
            r"(?:open|launch) notepad[,\s]+(?:and\s+)?write a (?:short )?note saying "
            r"(.+?)[,\s]+and save (?:it|the note) (?:on my desktop as\s+(.+)|(?:to|as)\s+(.+))",
            text,
            re.I | re.S,
        )
        if spoken:
            destination = (spoken[2] or spoken[3]).strip().rstrip(".!? ").strip("\"'“”‘’")
            if spoken[2]:
                destination = spoken_filename(destination)
            prefix = "on my Desktop as" if spoken[2] else "to"
            # Reuse exactly the same literal/destination policy as typed input.
            literal = spoken[1].strip().rstrip(", ")
            if any(c in literal for c in "\"'“”‘’"):
                return ActionPlan(
                    answer="The note text is ambiguous; type it in quotes for review. No action ran."
                )
            return parse_computer_actions(
                f"Open Notepad, write '{literal}', and save it {prefix} {destination}",
                settings,
                context=context,
            )
    if note:
        if not settings.computer_use_enabled:
            return ActionPlan(
                answer="Enable approved computer control in Settings first. No action ran."
            )
        body = note[2]
        destination = (note[4] or note[5]).strip().rstrip(".!? ").strip("\"'“”‘’")
        if note[4]:
            if any(c in destination for c in "/\\:") or destination in {".", ".."}:
                return ActionPlan(
                    answer="Choose a single .txt filename for the Desktop note. No action ran."
                )
            try:
                destination = str(desktop_directory() / destination)
            except RuntimeError as exc:
                return ActionPlan(answer=str(exc))
        return _step(
            "desktop_write_note",
            {"path": destination, "text": body},
            "Write and save a new Notepad note",
        )
    if re.match(r"^(?:open|launch) notepad.*\b(?:write|type|save)\b", text, re.I):
        return ActionPlan(
            answer="Give the literal note in quotes and an approved absolute .txt path, or say ‘on my Desktop as jarvis-test.txt’. I will preview it for approval before typing. No action ran."
        )

    search = re.fullmatch(
        r"(?:(?:open|launch) (chrome|(?:microsoft )?edge)[,\s]+(?:and\s+)?)?"
        r"search (?:google\s+)?for (.+?)[,\s]+(?:and\s+)?open (?:the |its )?(?:official )?result[.!?]*",
        text,
        re.I,
    )
    if search:
        if not settings.computer_use_enabled or not settings.browser_automation_enabled:
            return ActionPlan(
                answer="Enable approved computer control and the JARVIS browser session in Settings first. No action ran."
            )
        query = search[2].strip()
        candidates = [
            host
            for name, host in OFFICIAL_SITES.items()
            if re.search(rf"\b{re.escape(name)}\b", query, re.I)
        ]
        if len(candidates) != 1:
            return ActionPlan(
                answer="Which exact official website should I open? Name Python, NVIDIA, Flutter or GitHub, or provide a public HTTPS address. No action ran."
            )
        browser = (search[1] or settings.default_browser).casefold().removeprefix("microsoft ")
        if browser not in {"chrome", "edge"}:
            return ActionPlan(
                answer="Choose Chrome or Edge for the JARVIS browser session. No action ran."
            )
        return _step(
            "browser_search_open",
            {"query": query, "expected_host": candidates[0], "browser": browser},
            "Search and verify the official result",
        )

    if not context.get("computer_browser"):
        return None
    normalized = text.casefold().rstrip(".!? ")
    simple = {
        "go back": "browser_back",
        "back": "browser_back",
        "go forward": "browser_forward",
        "forward": "browser_forward",
        "read this page": "browser_read",
        "read the page": "browser_read",
        "show browser tabs": "browser_tabs",
        "list browser tabs": "browser_tabs",
        "close this tab": "browser_close_tab",
        "close that tab": "browser_close_tab",
    }
    if normalized in simple:
        return _step(simple[normalized], {}, normalized.title())
    scroll = re.fullmatch(r"scroll (down|up)", normalized)
    if scroll:
        return _step("browser_scroll", {"direction": scroll[1]}, "Scroll the observed page")
    tab = re.fullmatch(
        r"(?:open (?:a|another|a new|new) tab(?: (?:to|at))?|navigate to) (https://\S+)", text, re.I
    )
    if tab:
        return _step(
            "browser_new_tab" if "tab" in text.casefold() else "browser_navigate",
            {"url": tab[1].rstrip(".!?"), "browser": context.get("browser", "chrome")},
            "Navigate the JARVIS browser",
        )
    if re.fullmatch(
        r"(?:open|click) (?:that one|the \w+ result|next)|save it|download .+", normalized
    ):
        return ActionPlan(
            answer="I need an exact observed target and destination. Arbitrary form, download and visual actions are not enabled in this first release; no action ran."
        )
    return None

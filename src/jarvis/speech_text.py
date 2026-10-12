"""Prepare written assistant replies for speech without altering the written reply.

Sentence punctuation belongs to the synthesizer: dots, commas, questions, and
exclamation marks are retained. Formatting and machine output are handled here
because native Windows voices may read those symbols literally.
"""

from __future__ import annotations

import html
import json
import re
from collections.abc import Mapping
from datetime import date
from urllib.parse import urlsplit

_URL = re.compile(r"\b(?:https?://|www\.)[^\s<>]+", re.IGNORECASE)
_ISO_DATE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_MONTHS = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)
_ABBREVIATIONS = (
    (r"\be\.g\.(?=\s|$)", "for example"),
    (r"\bi\.e\.(?=\s|$)", "that is"),
    (r"\betc\.(?=\s|$)", "and so on"),
    (r"\bvs\.(?=\s|$)", "versus"),
    (r"\ba\.m\.(?=\s|$)", "A M"),
    (r"\bp\.m\.(?=\s|$)", "P M"),
)
_LOG_LINE = re.compile(
    r"^(?:\d{4}[-/]\d{2}[-/]\d{2}[T ]\d{2}:\d{2}:\d{2}\b|"
    r"\[?(?:DEBUG|INFO|WARNING|WARN|ERROR|CRITICAL|TRACE)\]?\s*[:|]|"
    r'Traceback \(most recent call last\):|File ".*", line \d+|'
    r"(?:Exception|[\w.]+Error):|/tool\s)",
    re.IGNORECASE,
)
_CODE_LINE = re.compile(
    r"^(?:import\s+[\w.]|from\s+[\w.]+\s+import\s|"
    r"(?:async\s+)?(?:def|class)\s+\w+|"
    r"(?:const|let|var)\s+\w+\s*=|return\s+|"
    r"[\w.]+\s*=(?!=)\s*|[{}\[\];]+$|"
    r"(?:if|for|while|try|except|else|elif)\b.*[:{]$)"
)


def _machine_json(value: str) -> bool:
    if not value.startswith(("{", "[")):
        return False
    try:
        return isinstance(json.loads(value), (dict, list))
    except (json.JSONDecodeError, ValueError):
        # Incomplete tool responses still must not become a spoken JSON stream.
        return bool(re.match(r'^\s*\{\s*"[^"\n]+"\s*:', value))


def _date_text(match: re.Match[str]) -> str:
    try:
        value = date(*(int(part) for part in match.groups()))
    except ValueError:
        return match.group(0)
    return f"{_MONTHS[value.month - 1]} {value.day}, {value.year}"


def _url_text(match: re.Match[str]) -> str:
    value = match.group(0)
    trailing = ""
    while value and value[-1] in ".,;:!?)]}":
        trailing = value[-1] + trailing
        value = value[:-1]
    parsed = urlsplit(value if "://" in value else "https://" + value)
    host = parsed.hostname or "the linked website"
    if host.startswith("www."):
        host = host[4:]
    # Domain identifies a link without reading tracking strings or credentials.
    host = host.replace(".", " dot ").replace("-", " dash ")
    return host + trailing


def _inline_code(match: re.Match[str]) -> str:
    content = match.group(1).strip()
    if not content or len(content) > 80 or re.search(r"[{}=;\\]|\w+\(", content):
        return ""
    if content.startswith(("/tool ", "http://", "https://", "www.")):
        return ""
    return content


def normalize_speech(text: str, replacements: Mapping[str, str] | None = None) -> str:
    """Return bounded prose for TTS, or empty text for machine-only responses.

    Pronunciation replacements are literal, case-insensitive, whole-token
    substitutions applied once. They affect speech only. Numbers are left to
    the installed voice; valid ISO dates and common ambiguous abbreviations are
    expanded so punctuation has the intended meaning.
    """
    if not isinstance(text, str):
        raise TypeError("Speech text must be a string.")
    value = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not value or _machine_json(value):
        return ""
    # Ignore fenced code (also incomplete fences) rather than narrating output.
    value = re.sub(r"(?ms)^\s*(`{3,}|~{3,})[^\n]*\n.*?(?:^\s*\1\s*$|\Z)", "", value)
    value = re.sub(r"!\[([^\]]*)\]\([^\n)]*\)", "", value)
    value = re.sub(r"\[([^\]]+)\]\((?:[^()]|\([^()]*\))*\)", r"\1", value)
    value = re.sub(r"\[([^\]]+)\]\[[^\]]*\]", r"\1", value)
    value = re.sub(r"(?m)^\s*\[[^\]]+\]:\s*\S+.*$", "", value)
    value = re.sub(r"`([^`\n]+)`", _inline_code, value)
    value = html.unescape(value)
    value = re.sub(r"</?(?:p|br|strong|em|b|i|span|div)(?:\s[^>]*|\s*)/?>", " ", value)
    lines: list[str] = []
    for line in value.splitlines():
        line = line.strip()
        if not line or _machine_json(line) or _LOG_LINE.match(line) or _CODE_LINE.match(line):
            continue
        if line.startswith("|") and line.endswith("|"):
            continue  # Markdown tables are written details rather than spoken rows.
        line = re.sub(r"^\s*(?:#{1,6}\s+|>\s*|[-+*]\s+|\d+[.)]\s+)", "", line)
        line = re.sub(r"^\[[ xX]\]\s*", "", line)
        for marker in (r"\*\*", "__", "~~", r"\*", "_"):
            line = re.sub(rf"(?<!\w){marker}(.+?){marker}(?!\w)", r"\1", line)
        if not re.search(r"\w", line):
            continue
        line = _URL.sub(_url_text, line)
        line = _ISO_DATE.sub(_date_text, line)
        for pattern, expanded in _ABBREVIATIONS:
            line = re.sub(pattern, expanded, line, flags=re.IGNORECASE)
        # Preserve terminal punctuation and insert a pause at a heading/list end.
        line = re.sub(r"\s+", " ", line).strip()
        if line and line[-1] not in '.!?:;"\u201d\u2019)':
            line += "."
        lines.append(line)
    value = " ".join(lines)
    if replacements:
        valid = {
            source.strip(): spoken.strip()
            for source, spoken in replacements.items()
            if isinstance(source, str)
            and isinstance(spoken, str)
            and source.strip()
            and spoken.strip()
        }
        if valid:
            pattern = (
                r"(?<!\w)(?:"
                + "|".join(re.escape(source) for source in sorted(valid, key=len, reverse=True))
                + r")(?!\w)"
            )
            by_case = {source.casefold(): spoken for source, spoken in valid.items()}
            value = re.sub(pattern, lambda m: by_case[m.group(0).casefold()], value, flags=re.I)
    return re.sub(r"\s+", " ", value).strip()

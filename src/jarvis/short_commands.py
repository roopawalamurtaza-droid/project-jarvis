"""Exact human command routing; model text never enters this module."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


def local_command(message: str, settings, store) -> tuple[str, dict] | str | None:
    text = re.sub(r"[.!?,]+$", "", message.strip().lower())
    text = re.sub(r"^(?:hey\s+)?jarvis[, ]+", "", text)
    text = re.sub(r"^(?:and\s+)?(?:please\s+)?", "", text)
    text = re.sub(r"\s+(?:please|as well)$", "", text)
    apps = {
        "chrome": "chrome",
        "google chrome": "chrome",
        "vs code": "vscode",
        "visual studio code": "vscode",
        "vscode": "vscode",
        "notepad": "notepad",
        "calculator": "calculator",
    }
    match = re.fullmatch(r"(?:open|launch|start) (.+)", text)
    if match:
        name = match[1].removeprefix("my ")
        if name in apps:
            return "open_app", {"app": apps[name]}
        if name in {"downloads", "downloads folder"}:
            return "open_folder", {"path": str(Path.home() / "Downloads")}
        if name in {"development environment", "flutter project"}:
            return "Which application or saved project would you like to open?"
        # Saved project paths remain subject to the same path checks and approvals.
        for item in store.memories():
            if item.get("category") == "project" and item.get("key", "").lower() == name:
                path = item.get("content", "").strip()
                if Path(path).is_absolute() and "\n" not in path:
                    return "open_folder", {"path": path}
                return (
                    "That project's memory has no single folder path. Save its full path in Memory."
                )
        return "That application or project is unavailable. I can open Chrome, VS Code, Notepad, Calculator, or a saved project folder."
    if text in {"what time is it", "what's the time", "what is the time", "current time"}:
        now = datetime.now(ZoneInfo(settings.timezone))
        return f"It's {now.strftime('%I:%M %p').lstrip('0')} in {settings.timezone}."
    if text.startswith(("remind me ", "set a reminder")):
        return "Scheduled reminders are not available yet. You can save the task in Memory; I cannot notify you later."
    if text in {"what's my next task", "what is my next task"}:
        tasks = [item for item in store.tasks() if item.get("state") == "awaiting_approval"]
        if tasks:
            return f"An action needs approval: {tasks[0].get('tool', 'local action').replace('_', ' ')}. Review Activity."
        memories = [item for item in store.memories() if item.get("category") == "task"]
        if memories:
            return f"Saved task: {memories[0]['key']}. {memories[0]['content'][:600]} No due-date order is configured."
        return (
            "There is no pending action or saved task to continue. What would you like to work on?"
        )
    if text in {
        "continue where we left off",
        "summarize what i'm working on",
        "summarise what i'm working on",
    }:
        memories = [
            item for item in store.memories() if item.get("category") in {"project", "task"}
        ]
        if not memories:
            return "I have no saved project or task context. Which project should we continue?"
        return "Your saved context: " + " ".join(
            f"{item['key']}: {item['content'][:400]}" for item in memories[:3]
        )
    if text in {"what's happening on my pc", "what is happening on my pc"}:
        return "Screen and system monitoring are unavailable. I can report saved tasks and actions in Activity."
    return None

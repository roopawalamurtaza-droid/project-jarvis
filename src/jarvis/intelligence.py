"""Structured human intent descriptions. Classification alone never authorizes execution."""

import re
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class Intent:
    category: str
    capability: str
    explicit_action: bool = False
    requires_context: bool = False

    def as_dict(self):
        return asdict(self)


def describe_intent(message: str) -> Intent:
    text = message.strip().lower()
    if text.startswith(("/routine ", "run routine ", "start routine ")) or text in {
        "prepare my development environment",
        "prepare my workspace",
        "start development mode",
    }:
        return Intent("multi_step_workflow", "Desktop", True, True)
    if text.startswith("/remember "):
        return Intent("memory_update", "Memory", True)
    if re.search(r"\b(remember|recall|saved|memory)\b", text):
        return Intent("memory_retrieval", "Memory")
    if text.startswith(("/tool ", "open ", "launch ", "start ", "and open ")):
        return Intent("application_operation", "Desktop", True, "project" in text)
    if re.search(r"\b(delete|remove|overwrite|transfer|purchase|send)\b", text):
        return Intent("sensitive_proposal", "Assistant", False)
    if re.search(r"\b(test|tests|build|debug|code|coding|flutter)\b", text):
        return Intent("coding_request", "Assistant", False, True)
    if re.search(r"\b(research|sources|look up|search web)\b", text):
        return Intent("research_request", "Assistant")
    if re.search(r"\b(remind|schedule|tomorrow)\b", text):
        return Intent("scheduled_task", "Assistant")
    if text.endswith("?") or re.match(r"^(what|why|how|when|where|who)\b", text):
        return Intent("information_request", "Assistant")
    return Intent("conversation", "Assistant")


SPEAKING_STYLES = {
    "concise": "Keep operational replies short. Use a few clear sentences unless asked for detail.",
    "professional": "Use polished, direct professional prose, with enough context for the decision.",
    "conversational": "Use natural, approachable prose and explain useful context without theatrics.",
    "technical": "Include relevant engineering details and evidence; distinguish assumptions from results.",
}

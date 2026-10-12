"""Behavioral regression checks for speech-only prose preparation."""

import pytest

from jarvis.speech_text import normalize_speech


@pytest.mark.parametrize(
    ("written", "spoken"),
    [
        ("Ready. Your task is complete.", "Ready. Your task is complete."),
        ("Wait, is this ready? Yes!", "Wait, is this ready? Yes!"),
        (
            "**Ready.**\n- Your task is complete.\n- Ask me for help.",
            "Ready. Your task is complete. Ask me for help.",
        ),
        ("# Status\n1. Open Chrome\n2. Check downloads", "Status. Open Chrome. Check downloads."),
        ("Use *brief* or __professional__ replies.", "Use brief or professional replies."),
        ("- [x] Saved\n- [ ] Review", "Saved. Review."),
        ("See [the guide](https://example.com/docs?q=private).", "See the guide."),
        ("See https://example.com/docs?q=private. Ready?", "See example dot com. Ready?"),
        ("See https://admin:secret@example.com/private#key!", "See example dot com!"),
        ("Scheduled for 2026-10-13 at 7:30 p.m.", "Scheduled for October 13, 2026 at 7:30 P M."),
        ("Invalid date: 2026-02-30.", "Invalid date: 2026-02-30."),
        ("Use e.g. Chrome, i.e. the browser.", "Use for example Chrome, that is the browser."),
        (
            "The price is 12.50 and there are 1,250 records.",
            "The price is 12.50 and there are 1,250 records.",
        ),
        ("Open `VS Code`.", "Open VS Code."),
        ("Status: ready.\n.\nAwaiting your command.", "Status: ready. Awaiting your command."),
    ],
)
def test_spoken_prose_preserves_meaning_and_prosody(written, spoken):
    original = written
    assert normalize_speech(written) == spoken
    assert written == original


@pytest.mark.parametrize(
    "written",
    [
        '{"id": "task-1", "state": "completed"}',
        '[{"result": "complete"}]',
        '{"state": "incomplete',
        "```python\nprint('Ready.')\n```",
        '```json\n{"id": "task-1"}',
        "INFO: task started\nERROR: network failed",
        "2026-10-13T10:22:30 DEBUG task complete",
        'Traceback (most recent call last):\nFile "app.py", line 2\nValueError: failed',
        "import sys\ndef task():\n    return 42",
        '/tool open_app {"app": "notepad"}',
        "| Key | Value |\n| --- | --- |\n| id | task-1 |",
    ],
)
def test_machine_output_is_not_spoken(written):
    assert normalize_speech(written) == ""


def test_prose_survives_embedded_machine_details():
    written = 'Your task completed.\n```json\n{"id": "123"}\n```\nAsk me for another task.'
    assert normalize_speech(written) == "Your task completed. Ask me for another task."


def test_pronunciation_dictionary_is_literal_case_insensitive_and_non_recursive():
    written = "JARVIS uses API tools. APIs remain written. C++ is supported."
    assert (
        normalize_speech(
            written, {"JARVIS": "Jarvis", "API": "A P I", "A P I": "wrong", "C++": "C plus plus"}
        )
        == "Jarvis uses A P I tools. APIs remain written. C plus plus is supported."
    )


def test_newlines_get_pauses_but_terminal_question_is_preserved():
    assert (
        normalize_speech("Would you like help?\nI am ready") == "Would you like help? I am ready."
    )


def test_speech_text_requires_string():
    with pytest.raises(TypeError):
        normalize_speech({"task": "completed"})

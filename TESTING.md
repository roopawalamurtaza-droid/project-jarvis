# Verification record — 2026-10-13

Tests were executed on Windows 11 with Python 3.12.14, using isolated temporary
data and mocked cloud requests. Real local model/audio checks were separate.

## Automated coverage

The integrated suite exercises provider parsing, credentials missing/rejected,
network failure, deadline/cancellation, response caps, cloud refusal, local/cloud
context isolation, memory recall, opt-in history, SQLite restart/deletion/export,
approval denial/replay/expiry/tampering, root revocation, emergency stop/restart,
invalid paths/schema, protected credentials, oversized files, corrupt/newer databases,
real Windows junctions, microphone errors/bounds, local-only speech model preflight,
Qt responsiveness, plain-text output, push-to-talk, audio absence, font rendering,
settings/history transition races and graceful shutdown.

Windows DPAPI was exercised with an artificial test credential; ciphertext did
not contain its plaintext and a new SecretStore could decrypt it. No real keys
were requested or used. Security review regressions use actual temporary Windows
junctions and complete-export records, not only path mocks.

Latest full-suite count and packaging outcome are recorded in NEXT_STEPS.md.
Ruff lint and formatting checks pass. The dependency audit after upgrading pytest
reported **no known vulnerabilities** in the installed package set. That reflects
the database result on this date, not a guarantee about future advisories.

```powershell
.\.venv\Scripts\python.exe -m pytest -q --tb=short
.\.venv\Scripts\python.exe -m ruff check src tests scripts
.\.venv\Scripts\python.exe -m ruff format --check src tests scripts
.\.venv\Scripts\python.exe -m pip_audit --skip-editable
```

The development sandbox blocked pytest temporary-directory creation and Windows
asyncio socketpair initialization. Approved execution outside the sandbox ran the
tests successfully; these restrictions were not treated as application failures.

## Real execution evidence

- Ollama `qwen3:8b` returned **I am JARVIS.** through the shared service.
- The desktop's actual Send worker displayed that response while its GUI timer
  continued firing. A warm run took 2.078 seconds with 19 UI timer callbacks.
  This is one measured check, not a general performance benchmark.
- The screenshot in `artifacts/JARVIS-desktop.png` is a grab of the real Qt window
  after a live model request. It was inspected visually; unreadable offscreen
  text was fixed by registering the installed Windows Segoe UI font.
- A real 0.26-second microphone capture produced 4,160 mono samples, then discarded
  them. No microphone recording was saved or uploaded.
- A locally generated 16 kHz test WAV was transcribed as **Jarvis voice system is ready.**
  CPU/int8 recognition took 2.439 seconds in that check.
- Qt's `winrt` speech engine found three installed voices. A short sentence played
  without a reported engine error; audibility/intelligibility still require human review.
- After recreating the service, the real local model recalled an explicitly saved
  test editor preference. Folder listing, text reading and approved directory
  creation succeeded against isolated test files. Read contents were absent from
  persisted task history.
- PyInstaller produced a Windows one-directory build. The first executable check
  exposed an incompatible ICU library collected from another tool. Sanitizing the
  build PATH corrected this; executable smoke details are in NEXT_STEPS.md.

Local machine verification files under `.local` contain diagnostics and artificial
test data, not credentials. The test scripts never claim model prose is an action
receipt; they check engine state and filesystem results.

```powershell
.\.venv\Scripts\python.exe scripts\verify_desktop.py --data-dir 'C:\Jarvis\.local' --live
.\.venv\Scripts\python.exe scripts\verify_integration.py
# Explicit microphone/playback checks; review flags before running:
.\.venv\Scripts\python.exe scripts\verify_voice.py --data-dir 'C:\Jarvis\.local' --wav 'C:\Jarvis\.local\voice-test.wav' --microphone --speak
```

## Human and fresh-machine checks still required

1. Launch Start JARVIS.cmd and confirm native display scaling, tray minimize/restore
   and compact view behave correctly on your screen.
2. Choose the HyperX microphone, hold to speak a phrase, release, review the actual
   recognized words, send them, and judge the spoken answer's audibility.
3. Open Notepad, Calculator and VS Code from Activity. Check window visibility;
   the tool currently verifies a process or accepted launch request, not the window.
4. Restart after saving a memory/history preference; inspect it and exercise deletion/export.
5. Test the executable's whole folder on a clean Windows 11 machine. Models and
   credentials are separate setup steps. Packaging smoke is not a clean-install test.
6. Configure an authorized OpenAI/Gemini account before paid live API verification.

Phase 1 is a verified development build with these acceptance limitations. It is
not a signed production release or a fully autonomous Windows operator.

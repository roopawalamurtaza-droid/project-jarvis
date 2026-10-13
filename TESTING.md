# Verification record — 2026-10-14

Phase 3 source verification: **444 passed in 90.79s** (baseline 295 passed in 39.29s).
Ruff check and all 60 format checks pass. Actual Qt workflows/approvals/filesystem,
memory persistence/relevance, permission/cancellation/UI draft/selection, measured
system status, exact business math and preserved voice/security regressions are
covered. A compact-window regression reproduces the former input-control overlap
and verifies separate controls at the repaired 430 × 530 minimum. Real native
renders passed at 100%, 150% and 200% Qt scaling; these are offscreen widget tests,
not human acceptance on displays at those DPI settings. The
150% live local qwen3:8b request completed in 9.125s with 203 UI timer ticks and a
0.235s maximum gap. This is not a human acoustic or fresh-machine acceptance test.
See PHASE3_RELEASE.md and final NEXT_STEPS.md for packaging/hardware limits.
The final 0.3.0 frozen GUI, Phase 3 and generated-speech/shutdown checks passed.
The user also confirmed the live wake/time, Chrome, VS Code follow-up and sleep
sequence works with spoken replies and without holding the microphone button.
This direct current-build acceptance is separate from the synthetic diagnostics;
broader room/noise/accent, soak and fresh-machine acceptance remain incomplete.
Two isolated 12-second offscreen idle UI samples measured 1.69% of one logical
core and 93.56 MiB working set with motion, then 0.91% and 93.57 MiB with reduced
motion and the core timer stopped. Microphone, STT and provider requests were
inactive; this is neither voice-engine CPU evidence nor a packaged long-idle soak.

An actual Windows development routine passed installed-app preflight and serially
completed Explorer `open_folder` and VS Code `open_app` against an isolated
generated project under the user's existing permitted root. Both returned verified
`process_running` evidence and the run completed at step index 2. This verifies
the launch path, not window visibility or project loading inside VS Code.

The following Phase 2 records are historical.

Phase 2 source verification: 280 tests passed in 41.81s before the last three
health/export regressions were added. Final count, packaged build outcome and
push/archive record are in NEXT_STEPS.md. Ruff passes; dependency audit found no
known vulnerabilities on this date. See UPDATE_REPAIR.md for per-feature evidence.

Synthetic PCM through actual Qt/VAD/offline STT/local Ollama/Windows playback
verified automatic requests, same-session follow-up, standalone wake/greeting,
compound sleep, mute closure, and authorized Chrome/VS Code launches. Launch
process evidence is not a window visibility assertion. The generated source
sample measured wake STT 0.578s after a 1.016s endpoint, provider response 6.797s,
TTS engine startup 0.031s on the follow-up, and 1769 UI timer ticks. Maximum
timer gap was 0.500s during synthetic fixture generation in the diagnostic;
it is not a production frame-latency benchmark. Human acoustic onset is unmeasured.

Actual five-second microphone and HyperX speaker checks are detailed in
docs/WAKE_ENGINES.md and docs/SPEECH_QUALITY.md. The user subsequently confirmed
the Phase 2 live sequence and 0.2.1 recognition recovery, as recorded below.
Broad room/noise/accent accuracy remains unmeasured, and current Phase 3 human
acceptance must be recorded separately; generated WAVs do not establish it.

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

Historical 0.2.1 recognition repair: **295 passed in 47.93s**, including twelve
completed/pending/cancelled-recognition regression cases. The first three cases
failed before the fix. Final packaged evidence is in NEXT_STEPS.md.

Earlier 0.2.0 record: **283 passed**, frozen GUI smoke and complete frozen voice
diagnostic both exit 0. The user confirmed an audible live wake/time reply and
the full Chrome/VS Code follow-up/sleep sequence after enabling Speak replies.
See NEXT_STEPS.md for exact build identity, timings, packaging fixes and limits.
Generated PCM measurements and user-reported live acceptance remain distinct.

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
3. Open Notepad, Calculator and VS Code from Mission Control. Check window visibility;
   the tool currently verifies a process or accepted launch request, not the window.
4. Restart after saving a memory/history preference; inspect it and exercise deletion/export.
5. Test the executable's whole folder on a clean Windows 11 machine. Models and
   credentials are separate setup steps. Packaging smoke is not a clean-install test.
6. Configure an authorized OpenAI/Gemini account before paid live API verification.

The current application is a development release with these acceptance limitations. It is
not a signed production release or a fully autonomous Windows operator.

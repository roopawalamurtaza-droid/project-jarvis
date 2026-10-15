# Verification record — 2026-10-16

## Phase 5 first gates — 0.5.0

Final source suite: **1,090 passed in 167.52s**; focused automation/UI suite
**136 passed** (overlapping). Frozen results are recorded in NEXT_STEPS.md after
execution. Filename routing separately passed 63 overlapping regressions. New fake-adapter tests
cover one-use live note approval, no persisted note/page body, consent revocation,
path/overwrite refusal, shared voice/text grammar, safe cancellation/pause,
observed browser targets/private DNS/redirect/method guards, challenge handling,
temporary manual grant/revocation and explicit Qt approval/status controls.

Actual shared-service Windows Notepad entry/Save As/content check passed, as did
separate Unicode/symbol and native Chrome page/scroll/tab/history/recreation
checks. These are actual executor checks, not fake-adapter tests. Google returned
CAPTCHA: actual search-and-open remains blocked/unverified until the human gate.
Final clean frozen runtime `4281e71f2668` repeated the actual Notepad save/byte
check and Chrome page/scroll/tab controls. Google remained CAPTCHA-blocked; the
diagnostic exited 2. Final native interface/local streaming/all 12 views passed.
The disappearing initial browser was intentionally stopped; no spontaneous crash
was established. New microphone, packaged human challenge, fresh-PC, localized/
legacy Notepad, physical locked/elevated desktop and broader autonomy are not
established by these tests. See PHASE5_RELEASE.md for commands and exact limits.

## Historical Phase 4.5 reference UI — 0.4.5

Baseline: **823 passed in 151.65s**. Final full source suite: **949 passed in
114.92s** at the first passing checkpoint. After the compact/shutdown ownership
repair, the final full suite passed **949 tests in 128.50s**; Ruff and all **87**
formatting checks passed. A later **12-test**
UI/identity check passed after the final small motion/tray refinements; these
overlap and are not added to the full count. The earlier full attempt had
943 passes and one stale 0.4.0 version assertion, corrected to actual identity.

Real native Windows UI captures were compared across multiple iterations;
all 11 existing/new destinations selected correctly. Actual local qwen3:8b
answer deltas and final Markdown were displayed. A final short native sample
recorded a 0.062s maximum timer gap. Native Qt scaling-factor captures at 1.25
and 1.5 passed, without changing Windows display settings. Scalar playback
metering produced 172 exact-own-process samples, 143 positive, peak 0.53837,
and unavailable after stop. Disk/network readings are native measured values;
CPU temperature remains unavailable. See PHASE45_RELEASE.md and NEXT_STEPS.md
for current packaging/deployment and separate human acceptance evidence.

The final frozen build `af909466f48c` passed smoke, native reference UI with real
local streaming/all 11 destinations, preserved memory/workflows, actual Windows
app/browser actions and generated PCM voice/action/shutdown diagnostics, each
with exit code 0. Current UI diagnostic maximum timer gap was 0.032s; the full
synthetic voice run's maximum gap was 0.922s, so these short samples are not a
universal latency guarantee. A native compact→restore→close regression exited
naturally in 0.469s after the repaired parentless helper-label issue.
The normal executable was launched and user data preservation verified.
**Human 0.4.5 acceptance passed on 15 October 2026:** the user confirmed the
live wake/Notepad → combined Chrome/Python tutorial search → VS Code follow-up
→ sleep sequence and shared Mini. Spoken replies, visible app/search results,
follow-up without another wake phrase and return to wake listening worked without
holding a button. This is direct user observation of the rebuilt application;
it does not establish browser-adapter page inspection, quantified acoustic
accuracy, latency, visual similarity or fresh-machine acceptance.

## Historical Phase 4 verification — 2026-10-14

Final Phase 4 source suite: **823 passed in 137.20s**; Ruff and all 73 formatting
checks passed. A reproducible Qt overlay/worker lifetime issue found during
repeat runs was repaired and covered by forced background-GC regressions.
Frozen GUI, Windows action and memory/workflow checks passed separately. Read
NEXT_STEPS.md for exact runtime identity, voice, human acceptance and limitations.

The user separately confirmed the current 0.4.0 live Notepad → combined Chrome
and Python tutorial search → VS Code follow-up → sleep sequence worked, including
visible Google results, spoken replies and hands-free operation without terminal
instructions. This is human observation, not browser-adapter page inspection or
synthetic speech. Wider acoustic and fresh-machine acceptance remain incomplete.

## Phase 4 action-engine checkpoint

Current source version is 0.4.0 on `codex/phase4-actions`. The retained Phase 3
baseline passed **444 tests in 94.16s** before the Phase 4 changes. A later selected
Phase 4 module suite passed **354 tests** covering local catalog/aliases/grants,
strict URL/search construction, native adapter receipt semantics, bounded plans,
approval/restart/partial failure/cancellation and provider function-call parsing.
Launch/focus/browser OS calls in that selected suite use fakes. Selected suites
overlap; they are not additive and do not replace the final integrated suite.
NEXT_STEPS.md records subsequent full-suite, lint, audit, frozen and hardware
results with the actual executable identity. No final release result is inferred
from this checkpoint.

Actual local discovery after the bounded binary Start Menu parser repair resolved
canonical Notepad in **0.046s** and returned **90 catalog entries in 0.204s** in one
run. This is discovery evidence, not a launch or foreground-focus assertion.
The catalog includes disabled discovery hints, not only authorized launch targets.
No blocking ShellLink COM scan, argument-bearing/environment-expanded/elevated/
installer/network shortcuts or arbitrary shell dispatch is used. Fixed supported
Store activation still uses the intended native Windows COM API.

Cloud function-call tests use mocked transport unless a later live result is
explicitly recorded. AI proposals are disabled by default, receive only the
explicit current request and fixed schemas, and require individual approval.
Plaintext model success is never evidence. Browser launch tests cannot establish
loaded pages, active tabs, redirects, new-window behavior or completed research.
The user-confirmed 0.3.0 microphone sequence below is historical, not 0.4.0 proof.

```powershell
.\.venv\Scripts\python.exe -m pytest -q --basetemp .local/pytest-check
.\.venv\Scripts\python.exe -m ruff check src tests scripts
.\.venv\Scripts\python.exe -m ruff format --check src tests scripts
.\.venv\Scripts\python.exe -m pip_audit --skip-editable
.\.venv\Scripts\python.exe scripts\verify_phase4.py --data-dir .local --actions
.\dist\JARVIS\JARVIS.exe --data-dir C:\Jarvis\.local --smoke-test
.\dist\JARVIS\JARVIS.exe --data-dir C:\Jarvis\.local --verify-phase4 --verification-actions
.\dist\JARVIS\JARVIS.exe --data-dir C:\Jarvis\.local --verify-voice-update --verification-actions
```

The Phase 4 action flags explicitly launch diagnostic apps and browser requests
under local permissions. Without them, the diagnostic only checks discovery/UI.
The voice diagnostic uses generated speech and Windows playback without capturing
the microphone. Its action flag adds authorized app launch checks. The basic
current-build sequence has the separate human confirmation above; fresh-machine
testing and broader room/noise/accent/soak coverage remain open. See
PHASE4_RELEASE.md for scope and safeguards.

## Historical Phase 3 verification

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

## Additional human and fresh-machine checks still required

The basic current 0.4.5 hands-free sequence and shared Mini passed as recorded
above. The following broader checks remain separate.

1. Launch Start JARVIS.cmd and confirm native display scaling, tray minimize/restore
   and compact view behave correctly on your screen.
2. Exercise the separate hold-to-talk path and additional microphone/speaker
   devices: release, review the recognized words, send and judge audibility.
3. Open Notepad, Calculator and VS Code, and review their actual receipts in
   Mission Control. Phase 4 distinguishes matching visible windows, foreground
   focus and accepted launch evidence. Verify focus refusal is reported honestly.
   Browser launch receipts still do not prove a page loaded or a new tab appeared.
4. Restart after saving a memory/history preference; inspect it and exercise deletion/export.
5. Test the executable's whole folder on a clean Windows 11 machine. Models and
   credentials are separate setup steps. Packaging smoke is not a clean-install test.
6. Configure an authorized OpenAI/Gemini account before paid live API verification.

The current application is a development release with these acceptance limitations. It is
not a signed production release or a fully autonomous Windows operator.

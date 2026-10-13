# Phase 3 command center development release

14 October2026. Version0.3.0 extends repaired0.2.1 on **codex/phase3-ultron**.
Private remote: https://github.com/roopawalamurtaza-droid/project-jarvis .
NEXT_STEPS.md records final packaged identity and push results. The minimum
working Phase3 foundation is implemented; the broader protocol is incomplete.

## Delivered

- Original native PySide6 charcoal/navy/cyan command center, vector core,
  compact mode, optional always-on-top, background activation overlay, Ctrl+K
  command palette and reduced motion. No imitated character artwork or voices.
- Core reads actual controller/worker/approval states; listening requires capture.
  Mic RMS comes from real frames. Speaking explicitly shows playback state with
  no PCM level: synthesized amplitude is unavailable from this Windows engine.
  Idle motion is8fps; animation stops hidden/reduced and static critical states.
- Mission Control exposes tasks, exact arguments, one-use approvals, results,
  cancellation and active workers. Workflow Replay shows actual serial steps,
  dependencies and task evidence, never fabricated progress percentages.
- Saved routines/projects in permitted roots: create/edit/disable/delete, preview,
  explicit enable/run, full-plan validation, installed-app preflight, per-step
  normal TaskEngine permissions, stop on failure/approval, interrupt between
  steps, restart cancellation without replay. New/edited routines are disabled.
- Development routine opens project folder in Explorer and launches VS Code.
  Visibility and project loading within VS Code are not verified or claimed.
  No arbitrary shell or project test runner exists.
- Structured selected-project and previous task/workflow context supports exact
  human routine and project follow-ups. Ambiguity asks which project/routine.
  Casual statements, provider output and saved references cannot execute tools.
  Deterministic intent descriptions are metadata, not an autonomous LLM planner.
- Local AI receives bounded untrusted references. Cloud receives no implicit
  local context, memory, tool output or business records. Response styles:
  concise/professional/conversational/technical.
- Memory Explorer searches/corrects/deletes/exports explicit memories with source
  metadata. Added summary/application/routine/instructions categories. Retrieval
  ranks token matches then recency across bounded SQL matches, including older
  memories beyond the latest500. Retention deletion requires explicit preview;
  normal startup does not delete saved memories. No embeddings or invented graph.
- Worker-based real Windows CPU/physical RAM and supported NVIDIA metrics. First
  CPU sample is unavailable until the second. Foreground app/title/PID require a
  separate opt-in, remain local/ephemeral/outside providers, and clear on revocation.
- Business starts with labelled ephemeral samples. Explicitly open local ledger
  to enter inventory/orders and record payment/fulfillment. Integer minor-unit
  arithmetic, reservations, losses and per-currency summaries are tested. Manual
  provenance is explicit; externally_verified is always false. Fulfillment is
  bookkeeping, not inventory delivery. Official messaging contracts cannot send.
  No financial imports, purchases, transfers, private-account automation or messages.
- Diagnostics: actual version/commit/build/path, voice/capture/wake, AI health,
  reported tokens, measured last-response latency, dated startup errors. API cost
  is unavailable rather than invented. Existing Phase2 wake/VAD/offline STT/
  follow-up/sleep/half-duplex/normalization/privacy/emergency-stop remain.

## Architecture and safeguards

`ui_components.py`: tokens/core. `intelligence.py`: descriptions only.
`workflows.py`: one engine shared by service/UI, additive workflow_projects,
workflow_routines, workflow_runs tables in existing SQLite. `awareness.py`:
worker snapshots with consent. `business.py`: opt-in separate business.sqlite3,
never provider context. Export includes loaded ledger and workflow definitions/
history. No new dependency; uv.lock changes only project version.

Preserve canonical roots, credential/metadata/network/device/ADS/symlink/junction
restrictions, cloud isolation, DPAPI keys, mic opt-in and bounded queues/context/
outputs. Settings writes block new action/workflow starts. Approvals stay scoped,
one-use and expired on restart. Cancellation stops between bounded operations;
already accepted launches cannot be undone. Do not widen roots for demos.

## Evidence and boundaries

Baseline295 passed in39.29s. Final443 passed in91.94s: actual Qt workflow
approval/resume, scoped filesystem results, cancellation/settings/draft/selection
regressions, relevance/source/cloud privacy, accounting, consent revocation and
voice/security regression tests. Actual native rendering passed at Qt factors
1,1.5,2. At150% live Ollama/qwen3:8b responded in9.125s,203 UI ticks, max gap0.235s.
The installed Ollama service was stopped initially; starting its loopback server
resolved the live connection failure. Real CPU/RAM/RTX5070 samples succeeded.
Foreground consent stayed off; permission handling uses mocked tests.

Screenshots come from the actual application with generated diagnostic data.
Canva returned no completed artifact/job ID before interruption; native vectors
are delivered. See docs/DESIGN_SYSTEM.md. Frozen package checks and current-PC
launch are recorded in NEXT_STEPS.md. Prior human acoustic acceptance belongs to
0.2.1; it is not silently relabelled as0.3.0. Samples are not latency/accuracy SLAs.

Incomplete: streaming, dedicated keyword model, full duplex/AEC, synthesized PCM
waveform, screenshots/clipboard understanding, project test/build execution,
free-form model planning, embeddings/graphs, durable schedules/briefings, external
monitoring, independent LLM agents, research adapters, bank/payment verification,
customer integrations, live messaging, returns/partial refunds, signed installer,
updater and fresh-PC acceptance. Existing task-event proactive speech remains
opt-in with quiet hours and frequency controls; no invented event sources.

## Reproducible commands

PowerShell in C:\Jarvis:

```powershell
.\scripts\setup.ps1
.\scripts\start.ps1 -DataDir C:\Jarvis\.local
.\.venv\Scripts\python.exe -m pytest -q --basetemp .local/pytest-check
.\.venv\Scripts\python.exe -m ruff check src tests scripts
.\.venv\Scripts\python.exe -m ruff format --check src tests scripts
.\.venv\Scripts\python.exe scripts/verify_phase3.py --data-dir .local --live
.\scripts\package.ps1
.\dist\JARVIS\JARVIS.exe --data-dir C:\Jarvis\.local --smoke-test
.\dist\JARVIS\JARVIS.exe --data-dir C:\Jarvis\.local --verify-phase3
.\dist\JARVIS\JARVIS.exe --data-dir C:\Jarvis\.local --verify-voice-update
.\.venv\Scripts\python.exe scripts/export_windows.py
.\.venv\Scripts\python.exe scripts/export_handoff.py
```

Tests require ordinary Windows permissions for junction/DPAPI fixtures when an
agent sandbox restricts them. Phase3 diagnostic uses isolated generated data,
no microphone or OS application launches; --live is local Ollama only. Voice
diagnostic plays synthetic speech, runs local STT/AI, and never captures the mic.
Keep full dist\JARVIS folder and `.local` intact during replacement. Inspect
Diagnostics; clone/restore **codex/phase3-ultron**. Keys/live data/models are
excluded from Git/archives. New machines must install models/re-enter keys/opt in.

Human acceptance: Hey Jarvis, time question, Open Chrome, And open VS Code,
Thanks Jarvis go to sleep. Confirm hearing speech/follow-up without Hold to talk,
return to wake, truthful core/capture, pause/mute and reduced motion. Record real
failures; generated-speech tests do not establish human acoustic accuracy.

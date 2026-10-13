# Project JARVIS

**Current development release: 0.3.0 · Phase 3 command center.** Continue branch
`codex/phase3-ultron` in the private repository. New native core, compact/background
modes, Mission Control, inspected routines, project context, Memory Explorer,
Windows measurements and an opt-in local business ledger extend repaired 0.2.1.
See [Phase 3 delivery and limits](PHASE3_RELEASE.md) and NEXT_STEPS.md for actual
build/verification/push records. Diagnostics identifies the running build.

Routines start disabled: inspect, enable, then Run. Ctrl+K opens commands.
Reduced motion, compact always-on-top, response styles and foreground-title
permission are in Settings. Business starts with labelled sample data; payments
are manual bookkeeping. The older repair record below is engineering history.

A native Windows assistant with real local AI conversation, opt-in hands-free voice,
Windows speech, local memory, and narrowly scoped desktop actions.

The application uses PySide6, a shared Python service, SQLite and an
optional authenticated FastAPI interface. Ollama is the default. OpenAI and Gemini
adapters are available after the user configures a key, model and cloud consent.
No cloud fallback occurs. Passive microphone capture requires saved opt-in.

## Start on this computer

Dependencies and the offline `base.en` speech model are installed in the project.
An existing `qwen3:8b` model was used for real conversation verification.

Double-click **Start JARVIS.cmd** to launch the packaged executable with this
computer's local configuration. Keep the `dist\JARVIS` folder intact. The source
launcher below uses the same configuration.

```powershell
cd C:\Jarvis
.\scripts\start.ps1 -DataDir 'C:\Jarvis\.local'
```

Ollama must be running. In Settings, select your model, permitted folders,
microphone and Windows voice. Hold **Hold to talk**, release to transcribe, review
the text, and press **Send**. Turn on **Speak replies** to hear answers.

For hands-free use, check **Speak replies** on the **Assistant** screen beside
**Hold to talk**. Open **Settings**, refresh audio devices, choose a microphone
and speaker, check **Allow hands-free microphone listening on this PC**, then
save. Say **Hey Jarvis**, wait for the acknowledgment,
and speak. Follow-ups work for 20 seconds by default. Pause and Mute close capture.
See [the voice guide](docs/HANDS_FREE.md) for tuning and verification limits.

Settings shows version, Git commit, build time, executable path, and live startup
health. Source edits require rebuilding: the launcher runs `dist\JARVIS\JARVIS.exe`.

The Phase 2 recognition repair was **0.2.1**, runtime source commit `d1f0fe0622a4`.
Completed wake misses and empty results now return to listening instead of leaving
Recognizing speech on screen; genuine pending work remains visibly pending.
All **295 tests passed** at that checkpoint. Current Phase 3 has **444 passing
tests**. See NEXT_STEPS.md for the current packaged identity and transfer
artifacts, and RECOGNITION_REPAIR.md for the reproduced Phase 2 failure and fix.
The earlier 0.2.0 build passed the user's live Chrome/VS Code follow-up/sleep
demonstration; that does not erase the subsequently reported recognition bug.

## What works

- Real text responses from an installed local model; bounded requests and interruption.
- Offline Whisper transcription and selectable Windows speech voices.
- Local wake phrase + WebRTC VAD, automatic requests, follow-up sessions, timezone
  greetings, normalized speech, speaker/rate controls and optional login startup.
- Explicit saved memory with search, editing, deletion and export.
- Conversation history saved only when enabled, with retention and deletion controls.
- Five tools: list a folder, read UTF-8 text, open Explorer, launch a supported app,
  and create a directory after approval.
- Task state, approval/rejection/cancellation, audit history and emergency stop.
- Current-user Windows DPAPI credential protection.
- Native desktop, compact floating view and system tray controls.
- Native state-driven core, command palette, reduced motion and background activation overlay.
- Inspected multi-step routines, selected-project context and evidence-based workflow replay.
- Memory Explorer, measured Windows resources and separately authorized foreground title context.
- Opt-in local inventory/order ledger with explicit manual payment and fulfillment records.
- Optional bearer-authenticated API on `127.0.0.1`; disabled unless started explicitly.

Actions use **Mission Control** or exact commands such as:

```text
/tool open_app {"app":"vscode"}
/remember preferences editor VS Code
```

Exact human requests such as **Open Chrome**, **And open VS Code**, or **Open my
downloads folder** route through the existing permission engine. Downloads must
be in a permitted folder; saved projects can contain a single absolute folder path.
Model output never executes itself. Approvals are reviewed in Mission Control. Read
results remain local and are not added to cloud chat.

## Development

```powershell
.\scripts\setup.ps1
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check src tests scripts
.\.venv\Scripts\python.exe -m jarvis --doctor
.\scripts\package.ps1
```

See [SETUP.md](SETUP.md), [SECURITY.md](SECURITY.md), [TESTING.md](TESTING.md),
[ARCHITECTURE.md](ARCHITECTURE.md), and [NEXT_STEPS.md](NEXT_STEPS.md).
Read [PROJECT_HANDOFF.md](PROJECT_HANDOFF.md) first when continuing development.
Private repository: https://github.com/roopawalamurtaza-droid/project-jarvis,
branch `codex/phase3-ultron`. The handoff records actual transfer/build status.
`uv.lock` pins the complete dependency graph. No real credentials, recordings,
local databases, downloaded model files, or build output are committed.

This is a development release. Screen vision, browser control, project test/build
execution, durable scheduling, external business integrations and remote access
remain incomplete. The local ledger does not verify or move money. Cloud
providers still require live credential-based verification.


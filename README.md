# Project JARVIS

**Current development release: 0.4.5 · Reference UI.** Continue
branch `codex/phase4-5-reference-ui` in the now-public repository. The native Qt
interface recreates the supplied widescreen composition: cyan energy core,
seven-item navigation, message cards, live intelligence dashboard and movable
mini assistant. Existing voice, memory, Windows actions and permissions remain.
Ordinary Ollama conversation streams real answer text; other providers retain
final responses. Spoken animation reads this process's real playback peak.
Read [Phase 4.5 delivery and limits](PHASE45_RELEASE.md) and
[NEXT_STEPS.md](NEXT_STEPS.md) for actual executable identity and verification.
Diagnostics identifies the executable you are running; source edits require a rebuild.

The historical 0.4.0 suite passed **823 tests**. On 14 October 2026, the user confirmed the
live hands-free Notepad, Chrome/Python tutorial search, VS Code follow-up and
sleep sequence, including visible search results and spoken replies.

Open **Application Library** and refresh discovered apps. Inspect a disabled app's
exact target before choosing **Review & enable**. Add an alias or favorite there;
configure your browser and search engine in Settings. Say or type **Open Notepad**,
**Open Chrome, VS Code and Spotify**, **Open YouTube**, **Switch to VS Code**, or
**Search Google for Python tutorials**. Missing apps and refused actions are
reported. Routine application requests do not require terminal instructions.

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

In 0.4.5, right-click the input microphone and choose **Show voice controls** to
display Hold to talk and Speak replies; the same speech preference is in Settings.
The input microphone mutes or resumes the shared hands-free controller. Choose
**Mini** at the bottom of the sidebar for the movable assistant. Ctrl+K reaches
every existing view, including System, Diagnostics, Timeline and Business.

Settings shows version, Git commit, build time, executable path, and live startup
health. Source edits require rebuilding: the launcher runs `dist\JARVIS\JARVIS.exe`.

The Phase 2 recognition repair was **0.2.1**, runtime source commit `d1f0fe0622a4`.
Completed wake misses and empty results now return to listening instead of leaving
Recognizing speech on screen; genuine pending work remains visibly pending.
All **295 tests passed** at that checkpoint. The completed Phase 3 checkpoint had
**444 passing tests**, and the user confirmed its live voice sequence. Current
Phase 4 results are recorded separately in [TESTING.md](TESTING.md). See
NEXT_STEPS.md for the current packaged identity and transfer
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
- Local application discovery, exact aliases, favorites, portable-app registration,
  scoped target permissions, launch and verified foreground focus.
- Website/search launches in a configured browser with safely encoded queries.
  Browser pages are not inspected, and search results are not completed research.
- Ten fixed tools covering app/focus/browser/search/library/system status and
  scoped folder listing/reading/opening/approved directory creation.
- Bounded multi-command plans, serial dependencies, partial failure receipts and
  cancellation, with optional AI action proposals that require step-by-step approval.
- Task state, approval/rejection/cancellation, audit history and emergency stop.
- Current-user Windows DPAPI credential protection.
- Native desktop, compact floating view and system tray controls.
- Native state-driven core, command palette, reduced motion and background activation overlay.
- Inspected multi-step routines, selected-project context and evidence-based workflow replay.
- Memory Explorer, measured Windows resources and separately authorized foreground title context.
- Opt-in local inventory/order ledger with explicit manual payment and fulfillment records.
- Optional bearer-authenticated API on `127.0.0.1`; disabled unless started explicitly.

Use natural requests in **Assistant**, and review pending approvals, actual
results, errors and cancellation in **Mission Control**. **And open VS Code**
uses the same engine as a typed command. **Open my Downloads folder** still needs
that folder in your permitted roots; saved projects use a single absolute path.

Manual mode asks before state changes. Unknown website hosts also need approval.
AI action proposals are off by default; enabling them still requires approval of
every exact step. Model prose never executes itself. Receipts distinguish an
accepted launch, a visible app window and verified focus. Browser page loading,
active tabs and requested new-window behavior are not verified. Local file/tool
results and the app catalog are not uploaded to cloud chat.

## Development

```powershell
.\scripts\setup.ps1
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check src tests scripts
.\.venv\Scripts\python.exe -m ruff format --check src tests scripts
.\.venv\Scripts\python.exe -m jarvis --doctor
.\.venv\Scripts\python.exe scripts\verify_phase4.py --data-dir .local --actions
.\scripts\package.ps1
```

See [SETUP.md](SETUP.md), [SECURITY.md](SECURITY.md), [TESTING.md](TESTING.md),
[ARCHITECTURE.md](ARCHITECTURE.md), and [NEXT_STEPS.md](NEXT_STEPS.md).
Read [PROJECT_HANDOFF.md](PROJECT_HANDOFF.md) first when continuing development.
Public repository: https://github.com/roopawalamurtaza-droid/project-jarvis,
branch `codex/phase4-5-reference-ui`. The handoff records actual transfer/build status.
`uv.lock` pins the complete dependency graph. No real credentials, recordings,
local databases, downloaded model files, or build output are committed.

This is a development release. Advanced browser reading/clicking/form automation,
live research, screen vision, project test/build execution, arbitrary file finding,
media/system power controls, durable scheduling, external business integrations
and remote access remain incomplete. The local ledger does not verify or move
money. Cloud providers still require live credential-based verification. The
Phase 4 diagnostic action flag launches test apps and browser requests; omit it
for discovery/UI-only checks.


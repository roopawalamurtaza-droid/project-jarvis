# Project JARVIS

A native Windows assistant with real local AI conversation, opt-in hands-free voice,
Windows speech, local memory, and narrowly scoped desktop actions.

The first development build uses PySide6, a shared Python service, SQLite and an
optional authenticated FastAPI interface. Ollama is the default. OpenAI and Gemini
adapters are available after the user configures a key, model and cloud consent.
No cloud fallback occurs. Passive microphone capture requires saved opt-in.

## Start on this computer

Dependencies and the offline `base.en` speech model are installed in the project.
An existing `qwen3:8b` model was used for real conversation verification.

Double-click **Start JARVIS.cmd** to launch the verified executable with this
computer's local configuration. Keep the `dist\JARVIS` folder intact. The source
launcher below uses the same configuration.

```powershell
cd C:\Jarvis
.\scripts\start.ps1 -DataDir 'C:\Jarvis\.local'
```

Ollama must be running. In Settings, select your model, permitted folders,
microphone and Windows voice. Hold **Hold to talk**, release to transcribe, review
the text, and press **Send**. Turn on **Speak replies** to hear answers.

For hands-free use, open **Settings**, refresh audio devices, choose a microphone
and speaker, check **Allow hands-free microphone listening on this PC**, enable
**Speak replies**, then save. Say **Hey Jarvis**, wait for the acknowledgment,
and speak. Follow-ups work for 20 seconds by default. Pause and Mute close capture.
See [the voice guide](docs/HANDS_FREE.md) for tuning and verification limits.

Settings shows version, Git commit, build time, executable path, and live startup
health. Source edits require rebuilding: the launcher runs `dist\JARVIS\JARVIS.exe`.

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
- Optional bearer-authenticated API on `127.0.0.1`; disabled unless started explicitly.

Actions use the **Activity** form or exact commands such as:

```text
/tool open_app {"app":"vscode"}
/remember preferences editor VS Code
```

Exact human requests such as **Open Chrome**, **And open VS Code**, or **Open my
downloads folder** route through the existing permission engine. Downloads must
be in a permitted folder; saved projects can contain a single absolute folder path.
Model output never executes itself. Approvals are reviewed in Activity. Read
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
branch `feature/handsfree-voice`. The handoff records actual transfer/build status.
`uv.lock` pins the complete dependency graph. No real credentials, recordings,
local databases, downloaded model files, or build output are committed.

This is an initial engineering build. Screen vision, browser control, arbitrary
developer commands, scheduling, business workflows and remote access are future
milestones. Cloud providers still require live credential-based verification.


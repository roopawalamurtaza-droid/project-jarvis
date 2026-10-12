# Project JARVIS engineering handoff

Prepared 13 October 2026. Continue this repository; do not start a new scaffold.
Read NEXT_STEPS.md for the final verification/transfer record and UPDATE_REPAIR.md
for the user's report of an old executable appearing unchanged.
The subsequent completed-recognition bug and 0.2.1 repair are documented in
RECOGNITION_REPAIR.md. Use the latest record in NEXT_STEPS.md, not the earlier
0.2.0 build identity when choosing the executable.

## Objective and milestone

A Windows desktop companion with local-first conversation, explicit memory,
opt-in hands-free voice, and narrow permission-controlled actions. Calm concise
wording, honest execution evidence and user control take precedence over fictional
capability claims. Phase 1 works; Phase 2 voice is implemented, packaged and tested.
The user confirmed the repaired live hands-free demonstration on this Windows PC.
Broader acoustic accuracy and fresh-machine distribution acceptance remain open.

## Repository and actual state

Private repository: https://github.com/roopawalamurtaza-droid/project-jarvis

Working branch: `feature/handsfree-voice`. `main` preserves the Phase 1 checkpoint
`b3f3c37`. The repository was created private during this handoff. No secrets or
live user data belong in it. The runtime build commit is recorded in packaged
`build_info.json`; the final handoff-only commit is Git HEAD and export MANIFEST.json.
Runtime sources are unchanged by that documentation checkpoint. NEXT_STEPS.md states
whether pushes actually succeeded; repository creation alone is not a push.

There was only one committed Phase 1 snapshot when the user reported the update
unchanged. Phase 2 changes were uncommitted and the launch file still selected
the earlier executable. Saved speech was off and wake permission defaulted off.
No JARVIS process or matching desktop/Start Menu shortcut was found at that audit.
Source edits cannot update a PyInstaller executable without a rebuild.

## Architecture and decisions

Python 3.12 (supported >=3.12,<3.14), src layout, uv lock, PySide6 native GUI,
SQLite storage, httpx providers, optional loopback FastAPI/uvicorn, sounddevice/
PortAudio capture, faster-whisper/CTranslate2 offline STT, WebRTC VAD and Windows
Qt speech. PyInstaller produces a one-directory Windows app, with separate DLLs.
This extends the working code and uses existing installed voices/models.

| Module | Responsibility |
| --- | --- |
| config.py | Validated nonsecret settings; atomic JSON persistence |
| desktop.py | Assistant, Activity, Memory, Audit, Settings; tracked Qt workers |
| voice_controller.py | UI-thread state/input/playback coordination, epochs, bounded events |
| conversation.py | Ten deterministic voice states, exact local voice controls, greetings/proactive policy |
| handsfree.py | Bounded capture frames/segments, WebRTC+RMS, single offline STT worker, local wake phrase |
| voice.py / speech_text.py | Push-to-talk/offline model preflight; installed TTS, speech-only normalization |
| service.py / providers.py | Bounded conversation/context/cancellation and selected AI adapters |
| short_commands.py | Exact human app/project/time/context intents; never model-generated actions |
| tools.py / tasks.py | Fixed tool schemas, path checks, approvals, execution evidence, emergency stop |
| storage.py / secrets.py | Memory/history/task/audit persistence; Windows current-user DPAPI keys |
| api.py | Optional bearer-authenticated loopback API, bounded body, no public bind |
| health.py / diagnostics.py | Build/source identity and read-only startup/package health |
| startup.py | Opt-in current-user Windows login entry |

Desktop and backend service live in the same application process. The optional
HTTP API is separate only when explicitly launched; there is no stale remote
frontend/backend server to reconnect in normal desktop use. Provider requests
and STT run off the GUI thread. Qt speech and widgets stay on the GUI thread.
Callbacks are generation/epoch guarded to discard cancelled or stale results.
Native STT cannot safely be killed; bounded shutdown discards late output.

## Implemented functionality

- Local Ollama conversation; OpenAI Responses and Gemini adapters behind explicit
  cloud consent/key/model selection. No cloud fallback. Actual cloud credentials
  have not been exercised; adapters use mocked transport tests.
- Session continuity, provider/model-separated bounded context, request/output
  caps, cancellation, optional saved history and deletion/retention.
- Explicit saved memory categories/search/edit/delete/export. Local Ollama gets
  bounded untrusted saved references; cloud never receives implicit local memory,
  hydrated local history, or tool file output.
- Five fixed tools: list/read/open folder, create directory, launch allowlisted
  Notepad/Calculator/VS Code/Chrome. Human exact natural commands reuse the same
  engine. Saved project folder paths and Downloads still require allowed roots.
- Task states/approval/rejection/cancellation, expiry and one-use approvals,
  startup recovery, audit trail, emergency stop. Launch evidence is process or
  accepted launcher status, not asserted window visibility/project loading.
- Push-to-talk fallback and optional wake listening. Offline Whisper checks the
  initial wake phrase on WebRTC-segmented audio. Same-utterance command is kept.
  Wake recognition is separate from VAD; silence is not transcribed/uploaded.
- IDLE, WAKE_WORD_LISTENING, ACTIVATED, USER_SPEAKING, PROCESSING,
  ASSISTANT_SPEAKING, FOLLOW_UP_LISTENING, SLEEPING, MUTED, ERROR states.
  Configurable activation/end-silence/utterance/follow-up timeouts (20s follow-up).
- Auto transcription/request/reply; exact ending/mute/stop phrases; varied
  timezone-aware brief/friendly/professional/silent greetings.
- Independent spoken normalization for Markdown/URLs/ISO dates/abbreviations,
  punctuation/prosody retained; machine code/logs/JSON suppressed from speech;
  pronunciation replacements, voice/speaker/rate selection. Written reply intact.
- Normal half-duplex playback gate and 350ms tail; Interrupt stops playback.
  Experimental headset-only exact voice stop recognition; no echo cancellation.
- Native tray/compact window, pause/resume/mute/status/exit, optional current-user
  Windows startup/minimize-to-tray and actual-event proactive task speech with
  quiet hours/frequency limits. All default passive/proactive permissions are off.
- Settings build version/Git/date/path, microphone/wake/speech/backend health and
  last reported startup error; packaged source SHA256 manifest.

## Important limitations and known issues

- Dedicated keyword model is not integrated. Whisper phrase checking invokes
  local STT for unrelated speech and waits for endpoint silence; this is slower
  than openWakeWord. Official Windows ONNX/Hey Jarvis availability was researched,
  but pretrained model CC BY-NC-SA terms preclude silently bundling it as a
  permissive default. Porcupine requires AccessKey/account terms. See WAKE_ENGINES.md.
- Exact reported spoken "full stop" was not reproduced with either tested voice.
  Raw Markdown asterisks and URL punctuation were reproduced and normalized.
  Do not declare every voice-specific punctuation problem solved without audio.
- No human wake/room-noise/far-field/accent benchmark, long soak, acoustic echo
  test, or human-audible latency measurement. Headset stop takes endpoint+STT time,
  is off by default, and is not reliable full duplex. Normal gate prevents input
  during speech. Microphone indicator distinguishes gating from physical closure.
- Time-aware greeting does not invent mood/activity. Scheduled reminders, calendar
  integrations, screen/window observation, arbitrary shell/code tools, autonomous
  planning, business workflows, runtime agent orchestration and remote access are absent.
- Context for unresolved project requests uses actual saved project/task memory;
  missing context returns an honest question. Natural app matching is a small exact
  grammar, not an LLM action planner. UI Activity remains the approval surface.
- Continuous history/memory user data and DPAPI secrets must stay local. DPAPI
  encrypted files do not migrate usefully to another Windows user; re-enter keys.
- CUDA speech not tested, SAPI explicit output selection not supported (WinRT
  constructor supports audioDevice). Invalid saved speakers fail visibly.
- No signed installer/updater, no automatic old-instance shutdown, no single-
  instance guard, and no fresh-PC frozen acceptance. Do not overwrite a running app.
- Older startup ImportErrors came from bundled ICU DLL contamination during the
  first Phase 1 packaging attempt. Package script sanitizes PATH; preserve this fix.
- Phase 2 packaging also needed the project-local WebRTC hook: import module
  `webrtcvad` belongs to distribution `webrtcvad-wheels`. Preserve that metadata fix.

## Testing evidence (Windows 11)

Tests distinguish fakes, synthetic speech, and real hardware. See TESTING.md,
docs/SPEECH_QUALITY.md, docs/WAKE_ENGINES.md and final NEXT_STEPS.md.

- Latest full suite: 295 passed in 47.93s; final focused health/export checks also
  passed. Security/path/junction/DPAPI/storage,
  mocked providers/API, offscreen GUI, audio framing/state/permission regressions.
- Actual local qwen3:8b response through the GUI, same-session follow-up, no Hold
  button, and Windows playback verified using generated PCM. A measured sample
  had 938 UI timer ticks and 0.141s maximum timer gap; provider turn 5.078s.
- Actual WebRTC/offline base.en synthetic positive wake/command, unrelated
  rejection, follow-up, stop phrase and gated-input discard passed. Wake result
  was 1.562s after last speech including a 1s endpoint; STT 0.562s.
- Real microphone 5s health sample: 248 frames, zero drops/errors/segments/STT,
  discarded audio. Isolated process idle CPU 0.625% of one core (0.052% on 12
  logical cores), working set 211.4MiB. This is not whole desktop or long-idle data.
- Native WinRT/SAPI synthesized fixtures were transcribed offline. HyperX output
  selection and actual Qt start/stop/completion passed, exactly two callbacks.
  First Speaking event 0.078s; scheduled stop at 0.700s completed at 0.719s.
  Engine state is not human acoustic onset/audibility evidence.
- Frozen GUI and voice diagnostics passed. The user confirmed hearing the live
  wake/time reply and completing Chrome/VS Code follow-up and compound sleep.
  This user report is distinct from agent measurements or a recorded acoustic test.
  Further room/noise/device/fresh-machine coverage remains open.
- The later stuck-recognition report was reproduced as completed wake-miss/empty
  results retaining the old status. Twelve 0.2.1 regression cases cover recovery,
  continued valid requests, honest pending work, playback and late cancellation.
  Native Whisper inference cannot be forcibly terminated; an actual native hang
  remains a distinct limit. Lifecycle logs omit recognized words/audio.
  Frozen recovery/voice checks passed, and the user confirmed a live 0.2.1
  wake/time answer returns to listening on the actual microphone.

## Dependencies and environment

`pyproject.toml` declares ranges; `uv.lock` pins full packages/hashes. Python base
3.12.14 was used, PySide6 6.12.0, faster-whisper 1.2.1, CTranslate2 4.8.2,
sounddevice 0.5.6, NumPy 2.5.4, webrtcvad-wheels 2.0.14.post1, tzdata 2026.5.
External Ollama service/model and Windows installed voices are prerequisites;
Whisper download is explicit and offline-only at runtime. Do not commit models.
Python alias from Windows Store did not work here; use `.venv\Scripts\python.exe`.

Environment variable names only: `JARVIS_DATA_DIR`, `OPENAI_API_KEY`,
`GEMINI_API_KEY`, `GOOGLE_API_KEY`, `JARVIS_API_TOKEN`; standard Windows path
variables `LOCALAPPDATA`, `ProgramFiles`, `ProgramFiles(x86)`, `SystemRoot`.
`QT_QPA_PLATFORM` is used only for offscreen tests/diagnostics. No secret is required
for local Ollama/voice. Do not put variable values, tokens or keys in this document.

## Exact commands

PowerShell, in the checkout (examples assume C:\Jarvis):

```powershell
git clone -b feature/handsfree-voice https://github.com/roopawalamurtaza-droid/project-jarvis.git C:\Jarvis
cd C:\Jarvis
.\scripts\setup.ps1
.\.venv\Scripts\python.exe -m jarvis --data-dir .local --doctor
.\.venv\Scripts\python.exe -m jarvis --data-dir .local --download-speech-model
.\scripts\start.ps1 -DataDir 'C:\Jarvis\.local'
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check src tests scripts
.\.venv\Scripts\python.exe -m ruff format --check src tests scripts
.\.venv\Scripts\python.exe -m pip_audit --skip-editable
.\scripts\package.ps1
.\dist\JARVIS\JARVIS.exe --data-dir C:\Jarvis\.local --smoke-test
.\.venv\Scripts\python.exe scripts\verify_handsfree.py --data-dir .local
.\.venv\Scripts\python.exe scripts\verify_voice_desktop.py --data-dir .local --actions
.\dist\JARVIS\JARVIS.exe --data-dir C:\Jarvis\.local --verify-voice-update --verification-actions
.\.venv\Scripts\python.exe scripts\export_handoff.py
```

Run the clone command only on a new machine/empty destination. The GitHub default
branch remains Phase 1 main; always choose feature/handsfree-voice to continue
this implementation. Authentication/access for another account must be granted
by the repository owner; private source is not publicly downloadable.

Install `uv` from its official vendor if absent; setup uses `uv sync --frozen`
voice/dev/package extras. For local AI, install official Ollama, start `ollama
serve` (or its Windows app), and explicitly install/select `qwen3:8b` or another
appropriate installed model. Test never assumes a download already exists.
Do not use the much larger 27B model on memory-constrained machines.

Audio diagnostics explicitly play synthetic speech and the microphone health
script samples/discards live input. `--actions` also launches apps under current
permissions; omit it if launch is not desired. `--smoke-test` never records even
when saved wake permission is on. Package the full dist\JARVIS folder, not exe alone.

## Security invariants

No unrestricted shell, no execution of model text, no implicit uploads. Canonical
absolute allowed roots, protected credential/metadata paths, device/ADS/network
path rejection and Windows symlink/junction rejection are enforced before action
and rechecked at execution. Manual mode requires state-change approval; folder
creation always asks. Advanced remains conservative. Approvals are scoped, one-use,
expire, and are cancelled across restart/stop. Never widen roots to make a demo pass.
Cloud consent/model isolation and untrusted memory/user references must remain.
Audio queues/durations and context/output/file/body limits must remain bounded.
API listens only on loopback with bearer token, no CORS/docs/public exposure.

## Transfer and preservation

Safe export `transfer/PROJECT_JARVIS_HANDOFF.zip` contains committed source,
assets, templates, tests/docs, all local Git refs/history as project-jarvis.bundle,
and per-file SHA256 MANIFEST. The archive's SHA256 is alongside it. Export refuses
uncommitted/untracked nonignored changes. Restore with:

```powershell
Expand-Archive -LiteralPath .\PROJECT_JARVIS_HANDOFF.zip -DestinationPath .\handoff
git clone -b feature/handsfree-voice .\handoff\project-jarvis.bundle .\Jarvis
cd .\Jarvis
git status --short
.\scripts\setup.ps1
```

Live `.local` settings/SQLite/secrets, models, audio fixtures/logs, venv and dist
are excluded. They are preserved on the current machine, not transferred to the
repository/new account. Any user-requested memory migration must be reviewed and
transferred privately, separately. Never silently include it in a handoff zip.
New developers use config/settings.example.json and reauthorize microphone/cloud/
startup. A complete build folder can be delivered separately; source is rebuildable.

## Priority-ordered continuation

1. Read final verification and build metadata; verify checkout/package commit and
   actual launch path. Keep data/settings/secrets intact. Confirm clean Git and
   successful private pushes; use archive if remote access fails.
2. On the user's actual microphone, test wake alone, wake+command, pause/noise,
   Chrome/VS Code approved follow-ups, compound sleep, timeout, mute/device errors
   and speech quality. Record failures/audio only with separate user consent.
3. Compare a licensed dedicated Windows keyword detector with the baseline;
   measure human false accepts/rejects and long-idle CPU/RAM, then decide.
4. Keep default half duplex. Add acoustic echo suppression only with real speaker
   testing; avoid unsupported reliability claims for stop/barge-in.
5. Verify fresh Windows packaging, startup opt-in, uninstall/update/single-instance
   behavior; signing/installer before distribution. Run meaningful regressions.
6. Implement durable reminders/calendar/screen context only as new authorized work;
   the latest instruction says no new features until update repair is verified.

No engineering depends on access to this chat. All source contracts/tests/docs
are in the repository; local diagnostic reports are summarized without private data.

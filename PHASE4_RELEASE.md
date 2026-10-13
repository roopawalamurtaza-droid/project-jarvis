# Phase 4 Windows action engine development release

14 October 2026. Version **0.4.0** continues the existing application on
**codex/phase4-actions** in the private repository:
https://github.com/roopawalamurtaza-droid/project-jarvis.
Read NEXT_STEPS.md for the tested executable identity, final suite, actual Windows
results, push status and transfer artifacts. Source implementation is distinct
from packaged and human hardware acceptance. The broader autonomy protocol is
not complete.

## Root cause

The 0.3.0 application already had a real local TaskEngine and Windows launcher.
Exact requests for Chrome, VS Code, Notepad and Calculator, plus approved folder
commands, used it. Voice and text already shared the same service; the user
confirmed the 0.3.0 wake/time, Chrome, VS Code follow-up and sleep demonstration.
There was no separate voice-only permission failure in that working sequence.

Its natural command grammar was limited to those four apps and a small set of
phrases. A different verb or combined request could fall through to ordinary
chat. The provider adapters were text-only: no function schemas were registered,
no structured calls were parsed, and the conversation prompt correctly denied
the model direct execution. Thus a generated explanation or terminal suggestion
could never become a real action. Other exact app names returned unavailable.
There was no application discovery library, app focus verifier, browser launcher
or encoded search action. These were integration and capability gaps, rather
than evidence that every launch command or the microphone was broken.

Phase 4 connects explicit requests to a local executor and returns measured
receipts. Changing the chat prompt alone would not fix those missing layers.
No claim that an old executable is currently running follows from the reported
symptom; use Diagnostics and the final build record to verify it.

## Implemented functionality

- A local ApplicationRegistry combines supported known locations, Windows App
  Paths, fixed supported Microsoft Store identities and bounded Start Menu link
  metadata. Per-user installations and reviewed portable EXEs are supported.
  The catalog is cached locally and can be refreshed in Application Library.
- Application Library searches the catalog, shows source/target/permission,
  registers a portable app, creates/removes aliases, marks favorites and enables
  or disables an exact target. Arbitrary discovered and custom entries begin
  disabled. Supported known locations and fixed supported package identities
  retain explicit-command availability. Review a disabled target before enabling.
- Exact names/IDs/aliases resolve without speculative fuzzy launches. Ambiguous
  aliases require a specific choice; a missing application reports not found.
  Grants bind to the exact target and kind, and cannot transfer silently to a
  changed installation. Argument-bearing or unsupported shortcuts are skipped.
- WindowsActionService launches an absolute validated EXE with `shell=False`,
  or activates a fixed supported Store identity through Windows COM. It first
  tries an existing matching visible window. Focus is verified against the real
  foreground window; Windows may refuse an explicit focus request, which is
  reported as a failure. An ordinary open request can still complete when an
  exact matching visible window is already present, with focus explicitly false.
  A refused focus does not justify silently creating a duplicate window.
- Launch receipts distinguish a matching visible window from a running process
  or accepted launcher/Store activation. Only observed windows support “is open.”
  Accepted requests without a matching window say visibility was not verified.
- Browser actions open known or validated external HTTPS destinations, or encoded
  Google/Bing/DuckDuckGo/YouTube searches in the default browser or configured
  Chrome/Edge/Firefox. Settings includes browser, search engine, requested new
  window behavior and preferred website aliases. Unknown exact hosts require
  approval even when saved as an alias. Aliases do not broaden host trust.
- One deterministic ActionRouter handles explicit natural requests, including
  “Open Chrome, VS Code and Spotify,” “Open Chrome and search for Flutter
  documentation,” “Switch to VS Code,” and browser searches. Plans contain at
  most six validated actions. Named browser context supports subsequent searches;
  it records the requested browser, not an invented active tab.
- ActionDispatcher runs validated steps serially through the existing TaskEngine,
  persists per-step receipts, and reports completed, failed, partial and cancelled
  runs. Independent steps can continue after a failure; dependent steps are
  skipped when their prerequisite did not complete. Approval pauses the plan.
  Restart cancels unfinished work rather than replaying it.
- Mission Control shows action-plan/task state, arguments, measured duration,
  verification, errors and cancellation. Interrupt and emergency stop prevent
  further work at the next safe boundary. Already accepted OS actions cannot be
  undone. Diagnostics exposes actual executor/library/browser health and the
  last receipt; readiness is not proof of a live page or desktop interaction.
- Typed and transcribed requests enter the same service and dispatcher. Full
  and compact modes share this path. The background activation overlay remains
  a status surface, not a separate automation engine.
- Optional reviewed AI action proposals are **off by default**. When enabled,
  an explicit unresolved action request can use strict Ollama, OpenAI Responses
  or Gemini function-call adapters. Every model-interpreted step requires its own
  one-use human approval. Plain model prose and invented success do not execute.
  Receipts produce the user reply locally; action results are not sent back to
  a provider for narration.
- Existing inspected routines use the fixed ToolRegistry; browser steps extend
  that registry. Folder/project operations retain allowed-root checks. Existing
  wake/VAD/offline transcription, follow-up conversation, half-duplex playback,
  memory, business bookkeeping, native UI and cloud consent remain in place.

## Evidence semantics and limits

| Receipt field or outcome | Meaning |
| --- | --- |
| `window_verified` | A visible window matched the exact executable/package identity |
| `focus_verified` | That matching window became the real foreground window |
| `process_running` / `launcher_accepted` | Process or accepted-launch evidence; window presence is separate |
| `packaged_activation_accepted` | Windows accepted the supported Store activation |
| `navigation_verified: false` | The browser page/tab was not inspected |
| `new_window_verified: false` | New-window behavior was requested, not observed |
| `research_completed: false` | Opening search results did not read or compare sources |
| `application_not_found` | No exact catalog target could be resolved |
| `permission_denied` | Configuration, target grant or validation refused execution |
| `unable_to_verify` | The requested result lacked sufficient evidence, including refused focus |
| `partial` | At least one action completed and another did not |

The ordinary browser retains its profiles, sessions and protections. JARVIS does
not attach to tabs, enable debugging, inspect pages, click, type into forms,
download files or bypass authentication. It cannot confirm page load, search
results, active-tab position or the final redirect destination. “Open another
tab and search…” uses a supported browser launch fallback; it does not prove a
new tab. URL validation rejects credentials, non-HTTPS schemes, unusual ports,
IP literals, local/reserved names and ambiguous encoding, but does not resolve
DNS or certify a site's trustworthiness.

Live research, arbitrary file finding/open-file actions, script/project command
execution, application-content automation, closing arbitrary apps, media/volume
control, audio device switching, shutdown/restart/logout, privileged installers,
messages, payments and purchases are not implemented by this release. CPU/RAM
status and supported app launching are implemented; a launch-history answer is
not a running-process inventory. Existing safe folder listing/reading/creation
does not grant filesystem-wide access. A custom executable runs with the user's
Windows account permissions after review; it is not an application sandbox.

## Architecture and engineering decisions

The native desktop and executor run in the same local Windows process. Cloud AI
is optional interpretation only and cannot operate a remote session as though it
were the user's PC. No separate remote desktop agent or public desktop API was
introduced.

| Module | Responsibility |
| --- | --- |
| `applications.py` | Bounded local discovery, exact alias resolution, cache and scoped target grants |
| `windows_actions.py` | Validated native EXE/Store/browser launch, exact window identity and focus evidence |
| `browser_actions.py` | HTTPS destination validation, fixed site mappings and encoded search URLs |
| `action_router.py` | Explicit human request grammar, bounded multi-action/dependency plan and session browser context |
| `action_dispatcher.py` | Persistent serial plan state, task receipts, partial failure and cancellation/recovery |
| `tools.py` / `tasks.py` | Ten fixed strict schemas, permission evaluation, revalidation and one-use approvals |
| `service.py` / `providers.py` | Shared voice/text dispatch; optional strict function-call proposals and provider isolation |
| `desktop.py` | Application Library, action history/progress, scoped approval and diagnostics |

Built-in ctypes/Win32/COM and existing dependencies are used; no new automation
library was added. This avoids opening a remote-debugging browser or mutating
authenticated profiles for basic launches. Advanced browser automation remains
a separate implementation and acceptance gate.

The existing SQLite database gains an additive `action_runs` table, capped at 256
receipts. Local app overrides/custom aliases/favorites/grants are in
`applications.json` under the data directory. Discovery cache and live browser
context are in memory; restart never restores active-tab assumptions. Original
memory/history/task tables and `.local` settings, keys and models are preserved.
No app catalog, foreground title, memory, history, file output or business ledger
is included in an AI action proposal. Only the current explicit request and
registered tool schemas cross that boundary. Cloud still requires prior consent.

## Permissions and security requirements

- `desktop_actions_enabled` and `browser_enabled` default true for explicit user
  commands. They do not permit autonomous background or model actions. Disable
  either in Settings to block that category. Manual mode asks before state
  changes; balanced/advanced use the existing conservative predefined policy.
- `model_action_planning` defaults false. If enabled, all interpreted steps still
  require one-use human approval, expire after ten minutes, and cancel on restart
  or emergency stop. Unknown website hosts also require approval. Approval does
  not waive path, target, mode, browser or emergency-stop checks.
- Reject arbitrary command strings, script runners, shell/admin tools, network
  executables, device/ADS/ambiguous paths and reparse-point targets. No elevation
  request is added. Revalidate the exact app target immediately before execution.
- Preserve canonical allowed roots and credential/private-metadata protections
  for file operations. Do not widen roots or silently enable a discovered app to
  make a demonstration pass.
- Preserve microphone opt-in, half-duplex gating, bounded audio/context/output,
  generation cancellation, DPAPI keys and no cloud fallback. Provider plaintext,
  saved memories and website content are untrusted and cannot authorize actions.
- Keep live `.local`, application overrides, databases, keys, logs and models out
  of Git and transfer archives. Exports contain committed source/history only;
  distribution contains the complete frozen folder without user data.

Settings names added: `desktop_actions_enabled`, `browser_enabled`,
`default_browser`, `default_search_engine`, `browser_new_window`,
`preferred_websites`, `model_action_planning`. These are JSON settings, not secret
environment variables. No new required environment variable or API key was added.
Existing optional names are documented in PROJECT_HANDOFF.md.

## Testing and release status

The retained Phase 3 baseline passed **444 tests in 94.16s** at this Phase 4 start.
A later Phase 4 module checkpoint passed **354 tests**, using fake OS adapters
for launch/focus/browser verification. These selected suites overlap with other
checks; do not add them to infer the final suite count. They do not establish
current-build hardware acceptance. TESTING.md and NEXT_STEPS.md record subsequent
final checks and any failures.

The complete final source suite passed **823 tests in 137.20s**, including the
reproduced Qt overlay/signal lifetime repair and GUI-thread deletion regressions.
Ruff and all 73 formatting checks pass. Actual source Windows action checks and
a real local structured-function proposal passed separately; final frozen and
human results are recorded in NEXT_STEPS.md.

Actual discovery after replacing blocking ShellLink COM reads with a bounded
binary MS-SHLLINK parser resolved canonical Notepad in 0.046s and listed 90 local
entries in 0.204s in one measured run. Shortcuts with arguments, network targets,
installers, elevation or environment expansion are skipped. This timing is one
local measurement, not a performance guarantee or launch/window acceptance.

The earlier 0.3.0 human voice acceptance is historical. Current 0.4.0 app discovery,
visible-window launches/focus, encoded search/browser launch, cancellation,
frozen packaging and live voice checks must be recorded against the actual build.
The final 0.4.0 package passed GUI startup, actual Windows actions, preserved
memory/workflows and generated-speech voice/action/shutdown checks. Its normal
window was launched and the preserved settings verified. Human acceptance and
the exact runtime/transfer identity are recorded separately in NEXT_STEPS.md.
Cloud function-call parsing uses mocked transport tests unless a separate live
credential-based result is explicitly recorded. No synthetic speech fixture or
mocked browser establishes human microphone reliability or page navigation.

## Install, run, build and transfer

For normal use, double-click **Start JARVIS.cmd**, open Application Library,
refresh the catalog, inspect permissions, and configure your browser/search
engine in Settings. Say or type “Open Notepad” or “Search Google for Python
tutorials.” Approve any pending step in Mission Control; routine app commands
do not require entering terminal instructions.

For a new developer, clone the explicit current branch into an empty destination:

```powershell
git clone -b codex/phase4-actions https://github.com/roopawalamurtaza-droid/project-jarvis.git C:\Jarvis
cd C:\Jarvis
.\scripts\setup.ps1
.\.venv\Scripts\python.exe -m jarvis --data-dir .local --doctor
.\.venv\Scripts\python.exe -m jarvis --data-dir .local --download-speech-model
.\scripts\start.ps1 -DataDir C:\Jarvis\.local
.\.venv\Scripts\python.exe -m pytest -q --basetemp .local/pytest-check
.\.venv\Scripts\python.exe -m ruff check src tests scripts
.\.venv\Scripts\python.exe -m ruff format --check src tests scripts
.\.venv\Scripts\python.exe -m pip_audit --skip-editable
.\.venv\Scripts\python.exe scripts\verify_phase4.py --data-dir .local --actions
.\scripts\package.ps1
.\dist\JARVIS\JARVIS.exe --data-dir C:\Jarvis\.local --smoke-test
.\dist\JARVIS\JARVIS.exe --data-dir C:\Jarvis\.local --verify-phase4 --verification-actions
.\dist\JARVIS\JARVIS.exe --data-dir C:\Jarvis\.local --verify-voice-update
.\.venv\Scripts\python.exe scripts\export_windows.py
.\.venv\Scripts\python.exe scripts\export_handoff.py
```

Use an installed official Ollama service/model for local AI. Speech-model download
is explicit; normal listening never downloads. `verify_phase4.py --actions` and
frozen `--verify-phase4 --verification-actions` explicitly launch their diagnostic
apps and browser requests; without those action flags, they exercise discovery/UI
only and do not establish execution acceptance. The synthetic voice diagnostic
plays speech and uses local STT/AI, without microphone capture. Review diagnostic
action details in NEXT_STEPS.md before running them. Stop the old JARVIS
process before replacing its build, preserve `.local`, and keep the entire
`dist\JARVIS` folder together. There is no signed installer or automatic updater.
Another GitHub account needs private repository access; otherwise use the complete
handoff archive and bundle instructions in PROJECT_HANDOFF.md.

## Next developer

Read PROJECT_HANDOFF.md, NEXT_STEPS.md, TESTING.md and the fixed schemas before
changing action routing. Reproduce failures with the current executable and
report actual receipts. Retain existing voice and security tests. First finish
the current release's Windows/package/human checks; then prioritize deterministic
browser observation and narrowly scoped controls without converting a launch
receipt into a page, research, financial or application-content claim. Broader
autonomy is unfinished work, not permission to add unrestricted OS execution.

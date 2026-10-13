# Current development and transfer state — 14 October 2026

## Phase 4 Windows action engine — 0.4.0

Current branch **codex/phase4-actions**, extending the committed 0.3.0 checkpoint.
Read PHASE4_RELEASE.md for architecture, exact commands, permissions and limits.
The current work adds application discovery/aliases/target grants, native launch
and focus verification, known HTTPS websites and encoded browser searches,
bounded shared voice/text action plans, partial failure and one-use approvals,
Application Library and action receipts. Optional model-interpreted proposals
require explicit opt-in and per-step approval; ordinary explicit app/search
commands use deterministic dispatch without a model or terminal instructions.

Verified during source integration:

- Phase 3 baseline: **444 passed in 94.16s**. First complete Phase 4 suite:
  **819 passed in 124.27s**. Final suite **823 passed in 137.20s**; Ruff lint
  and all 73 formatting checks pass. Selected suites overlap; do not add counts.
- Repeated full runs exposed a Qt cleanup abort. A forced worker-GC regression
  reproduced the parentless ambient overlay being collected outside the GUI
  thread. The overlay and worker signal objects now have GUI ownership; finished
  signals and native test widgets complete GUI-thread deferred deletion. The
  formerly crashing regression, hidden-main-window overlay behavior, 50 focused
  desktop/hands-free tests, then the complete 823-case suite passed afterward.
  The hands-free recognition algorithm was not rewritten to conceal this issue.
- Actual Windows metadata discovery: 90 entries, canonical Notepad resolution
  0.046s, complete catalog 0.204s. Replaced blocking native shortcut inspection
  with bounded binary parsing; unsupported links fail closed.
- Actual native input/worker/action execution passed Notepad, Calculator, Chrome,
  VS Code, Explorer and Store Spotify with matching visible-window evidence.
  Combined Chrome/search, Google/YouTube search, official Python/GitHub websites,
  and supported new-tab launch fallback completed. These URL tasks verify
  browser launch requests, not page contents, active tabs or completed research.
- Missing-app requests reported failure; a three-app request with a missing
  middle app reported partial success and completed both independent apps.
  Explicit Chrome focus was refused by Windows and reported truthfully; an
  already visible app still satisfies an ordinary open request without spawning
  a duplicate. Downloads remained denied outside current allowed roots.
- Native action check: 566 GUI ticks, maximum gap 0.141s in one source run;
  not a general performance guarantee. Source check uses generated isolated
  task data and no microphone, cloud or real financial data.
- Real local qwen3:8b returned a structured `open_app` proposal for Notepad
  with registered schemas. This request executed nothing. Cloud adapters use
  mocked transport tests; current AI action planning preference stays off.

The old JARVIS 0.3.0 window was closed gracefully for replacement and speech
diagnostics; its complete folder is preserved at `transfer/phase3-build-0.3.0`.
Other user apps were not closed. Final build identity and transfer evidence:

- Runtime **0.4.0**, clean source commit
  `bb766495eccc1701ece3932a3ba8dc02bd50bcba`, `codex/phase4-actions`.
  This source was successfully pushed and its remote identifier verified.
- Embedded UTC build date `2026-10-13T23:00:53+00:00` (14 October in India).
  Executable `C:\Jarvis\dist\JARVIS\JARVIS.exe`, 14,727,047 bytes,
  timestamp `2026-10-13T23:02:19+00:00`. SHA256
  `cd97401b88bb4f047aa303388bdb820bfd0e010892ef5264a32066ef3a8a5cfb`.
  All **30** embedded source hashes match current runtime files. Later
  documentation-only commits do not change this tested executable.
- Final frozen GUI smoke, actual Phase 4 Windows action check and Phase 3
  memory/workflow regression all exit **0**. Fifteen action requests exercised
  visible-window launch evidence, known website/browser searches, independent
  partial failure, missing-app errors and actual OS focus refusal. No microphone
  or cloud was used in these diagnostics. The frozen action check measured a
  0.062s maximum GUI event gap in one run; it is not a performance guarantee.
- Full Windows archive `transfer/JARVIS-Windows-0.4.0.zip`: **154,593,744 bytes**,
  **1,113 files** individually hash-verified, with BUILD_MANIFEST.json and
  INSTALL.txt. SHA256
  `1c9cd3c1a6a7daf6ae62d929c518253d3647e7aeafa3f6907a04173da0f3b90c`.
  This unsigned binary archive is staged locally, not a GitHub release.
- Settings hash, memory count and credential-file presence/hash match the
  pre-update snapshot. Existing microphone/speech opt-ins, AI provider and
  allowed folders are retained. Downloads was not added to permitted roots.
- Use `Start JARVIS.cmd`, which still selects this exact executable and `.local`.
  Models, user configuration, aliases, credentials, logs and databases remain
  excluded from Git and transferable build/source archives. Never zip the whole
  `transfer` directory, which also contains private local backups.

- Final frozen generated-speech voice/action check and clean shutdown exit **0**:
  real Qt, WebRTC VAD, offline base.en, local qwen3:8b and Windows speech handled
  unrelated speech recovery, wake/time, same-session AI, Notepad/Chrome/VS Code,
  combined Chrome + encoded Python tutorial search, standalone wake, compound
  sleep and mute closure. No microphone was opened by this diagnostic; no page
  was inspected or claimed loaded by its browser adapter.
- The normal replacement application **was launched and verified** on this PC:
  PID 41768, title `JARVIS · Command Center`, nonzero window handle, responsive,
  exact process path `C:\Jarvis\dist\JARVIS\JARVIS.exe` with `.local` data.
  Saved settings, memory count and credential file still matched after launch.
- **Human 0.4.0 acceptance passed on 14 October 2026:** the user confirmed
  “Hey Jarvis, open Notepad” → “Now open Chrome and search for Python tutorials”
  → “Open VS Code too” → “Thanks Jarvis, go to sleep.” Apps opened, Google's
  Python tutorial search results appeared, spoken responses/follow-up/sleep
  worked hands-free, and no terminal instructions were required. This is a
  direct user report about the current build, separate from generated speech
  and prior 0.3.0 acceptance. The browser adapter still does not inspect pages;
  its `navigation_verified` field remains false. Broader acoustic/fresh-PC
  acceptance is not implied.
- Current source/history handoff is `transfer/PROJECT_JARVIS_HANDOFF.zip`; its
  MANIFEST and adjacent SHA256 identify the final documentation checkpoint.
  The bundle preserves all Git branches/history and is checked by restoration.
  Source/docs are pushed privately; full Windows distribution remains local.

Remaining: wider room/noise/accent and long-idle tests, fresh-machine/signed
distribution, reliable page observation and scoped page controls. Arbitrary
scripts, message/payment submission, destructive actions, unrestricted browsing,
media controls and filesystem-wide access remain unimplemented. Windows can
refuse focus, and native OS activation cannot be hard-aborted mid-call; stop
prevents subsequent actions at the next safe boundary.

The historical Phase 3 and Phase 2 records below remain distinct.

## Phase 3 command center — 0.3.0

Current branch: **codex/phase3-ultron**. Read PHASE3_RELEASE.md. Baseline 295
passed; integrated **444 passed in 90.79s**. Real native rendering at 100/150/200% Qt
scaling, local AI and two-step approved filesystem workflow passed. The final
frozen identity and transfer evidence are recorded below.
The broader protocol remains incomplete as explicitly documented.

Compact input controls were found to overlap at the smallest window size;
the layout was repaired and a geometry regression now verifies separate controls.
The minimum is 430 × 530 logical pixels. Normal and reduced-motion isolated
12-second Qt samples used 1.69% and 0.91% of one logical core respectively,
about 93.6 MiB working set, with audio and AI disabled. This is not a long soak
or active voice-resource benchmark.

Next: broader acoustic coverage, compact/background/reduced-motion human
review, long-idle measurements and fresh-Windows distribution. Preserve local
data, keys, model isolation, mic consent and bounded execution.

### Final packaged identity and transfer

- Runtime **0.3.0**, clean build commit
  `985471500901249bde51d1e3621df3510b431765`, on `codex/phase3-ultron`.
- Embedded build date `2026-10-13T20:56:31+00:00` (14 October in India).
  Executable `C:\Jarvis\dist\JARVIS\JARVIS.exe`, 14,638,289 bytes,
  file timestamp `2026-10-13T20:57:56+00:00`.
- Executable SHA256
  `2d575e177eea096c720a9e6fcd223da3e9fd711203a83a9ba7a93aab995fdb1a`.
  All **25** packaged source hashes match current runtime files. Later
  documentation/screenshot commits do not alter this runtime.
- Final frozen GUI smoke and isolated Phase 3 verification both exit **0**.
  Offline STT/VAD/audio packages, speech model, Windows speech and selected local
  Ollama model are ready. Phase 3 verification uses generated isolated data:
  real approved create/list filesystem routine, memory restart, sample-ledger
  privacy, microphone-off truthfulness, reduced motion and actual resource samples.
  Its model response is deliberately fake; the separate live local AI check is
  documented in TESTING.md. No microphone is opened by these two checks.
- Final frozen generated-speech voice regression and application shutdown exit
  **0**. Actual Qt, WebRTC VAD, offline base.en, local qwen3:8b and Windows
  playback passed unrelated-speech recovery, wake/time, same-session AI follow-up,
  standalone wake acknowledgment, compound sleep and mute/capture closure.
  A separate generated-speech actions run completed verified Chrome and VS Code
  launch tasks. Reports record process evidence, not observed app contents.
  The actions run measured wake endpoint 1.000s + STT 0.359s, playback-engine
  start 1.531s after speech end; provider follow-up response 3.703s, playback
  start 5.156s after speech end. No microphone was opened by these diagnostics.
  The 0.844s maximum GUI timer gap includes synthetic fixture generation and
  is not a steady-state latency or human acoustic benchmark.
- Normal visible application **was launched and verified** on this Windows PC:
  title `JARVIS · Command Center`, nonzero window handle, responsive,
  actual process path `C:\Jarvis\dist\JARVIS\JARVIS.exe`, data `.local`.
  The standalone process view was checked with normal Windows permissions;
  the agent sandbox cannot enumerate this external desktop process.
  The latest process check also confirmed the same path and responsive window.
- **Human 0.3.0 acceptance passed:** the user confirmed the full live sequence
  “Hey Jarvis, what time is it?” → “Open Chrome” → “And open VS Code” →
  “Thanks Jarvis, go to sleep.” Spoken replies, follow-up without a second wake
  phrase and return to wake listening worked without holding the microphone
  button. This is direct user confirmation on the current build, separate from
  synthetic diagnostics and earlier 0.2.x acceptance. No room/noise/accuracy
  benchmark or fresh-PC acceptance is implied.
- The retained last error is `ProviderError` at `2026-10-13T20:32:43+00:00`
  from the first live Phase 3 check while Ollama was stopped. Starting the
  installed loopback service resolved it; subsequent live AI, frozen startup
  and normal launch passed. It is a dated record, not a new startup failure.
- Runtime source was successfully pushed to the private repository and remote
  identifier verified. The final handoff documentation commit is Git HEAD and
  the source archive MANIFEST; compare `git ls-remote` rather than guessing.
- Full Windows artifact `transfer/JARVIS-Windows-0.3.0.zip`: **154,502,253 bytes**,
  **1,112 files** individually hash-verified, plus INSTALL.txt and BUILD_MANIFEST.
  SHA256 `4707868150d99b39f42b738ad956e0f5f4c9e17b623baad798b3ab424d1dd473`.
  The unsigned binary archive is local, not published as a GitHub release.
- The previous complete 0.2.1 folder is retained at `transfer/phase2-build-0.2.1`.
  `Start JARVIS.cmd` targets the new executable and existing `C:\Jarvis\.local`.
  No matching desktop or user Start Menu shortcut was found during this check.
  Saved settings and memory counts matched the pre-update snapshot; microphone
  and speech opt-ins are retained. No secrets file was present or replaced.

## Historical Phase2 repair/transfer record

Continue this checkout. Read PROJECT_HANDOFF.md and UPDATE_REPAIR.md first.

## Latest repair: 0.2.1 recognition completion

The user subsequently reported Recognizing speech stuck while Voice remained in
Wake Word Listening. Reproduced completed wake-miss/empty-result paths failed
three initial regressions. Version 0.2.1 explicitly completes those paths, shows
actual pending recognition, clears pause/mute/playback status and preserves
cancellation and listening boundaries. See RECOGNITION_REPAIR.md.

- Full final suite: **295 passed in 47.93s**, including twelve new regressions;
  Ruff lint and all 46 format checks passed. Dependency versions are unchanged;
  only the project package version changed in uv.lock.
- Tested runtime build: **0.2.1**, commit
  `d1f0fe0622a4e429749773d09f5d7b13109a5f30`, clean at packaging.
- Embedded build date: `2026-10-12T22:16:02+00:00`; executable file timestamp
  `2026-10-12 22:17:21 UTC`, length 14,554,465 bytes. Same launcher/path/data folder.
- Executable SHA256:
  `ab0dfcf9294df1c449683c336f126dd76e39bf68dc457a65bf5da8a09f000641`.
- Final frozen GUI smoke and extended voice diagnostic both exit **0**. Generated
  unrelated speech completed as ignored and returned to `Listening for "hey jarvis"`
  with no chat request. The next valid wake/time request, real local AI follow-up,
  Windows speech, standalone wake, sleep and mute all passed. No microphone was
  opened by that diagnostic; this is generated-speech integration evidence.
- All 20 embedded source hashes match the current runtime code. Further commits
  containing only documents/screenshots do not alter this tested runtime.
- Runtime repair source was successfully pushed on `feature/handsfree-voice`.
  User settings/memory/keys were retained. Old 0.2.0 folder is backed up at
  `transfer/phase2-build-0.2.0`; 0.2.1 was relaunched with the existing saved opt-ins.
- Current Windows artifact: `transfer/JARVIS-Windows-0.2.1.zip`, 154,414,447 bytes,
  1,111 verified files, full folder plus INSTALL.txt and BUILD_MANIFEST.json.
  SHA256: `90d66045da449ac55c00d4f5b82517c843da6346eb04a92634c90d91c87b90e7`.
  Current source/history archive remains `transfer/PROJECT_JARVIS_HANDOFF.zip`;
  its MANIFEST and adjacent SHA256 identify the final handoff checkpoint.
- The user confirmed on the actual microphone that **0.2.1 answers the wake/time
  request and returns to listening**. This new live acceptance is distinct from
  the earlier user-confirmed 0.2.0 sequence below. Native inference cannot be forcibly killed;
  this fix does not silently mark genuinely unfinished transcription as complete.

The following sections retain the **earlier 0.2.0 record**, not the current build.

## Earlier 0.2.0 build and launch

- Branch: `feature/handsfree-voice`.
- Private repository: https://github.com/roopawalamurtaza-droid/project-jarvis.git.
- `main` and the GitHub default branch preserve Phase 1 `b3f3c37`. Clone the
  feature branch explicitly. A default-branch change was rejected by automatic
  approval review and was cancelled; repository access/privacy was unchanged.
- Tested runtime build: version **0.2.0**, commit
  `6170121a85af83ee7ee1d4101913dd0c0c1594c3`, clean at packaging.
- Embedded UTC build date: `2026-10-12T21:53:26+00:00`.
- Executable: `C:\Jarvis\dist\JARVIS\JARVIS.exe`; file timestamp
  `2026-10-12 21:54:49 UTC`, length 14,552,892 bytes.
- Executable SHA256:
  `38c87976c556d3d552e4c40d0af8360da973c3a83089f17061ffc92652e8ab3d`.
- All 20 embedded Python source hashes match the working code. Later handoff
  documentation/screenshot commits do not change runtime sources or packaging.
- Normal replacement window launched, visible window handle/title present,
  responsive, and process path confirmed. `Start JARVIS.cmd` selects this path.
- Old build: `transfer/phase1-build`. User-data backup:
  `transfer/repair-backup`. Live settings, memory and credential storage remain
  in `.local`; no user-data directory was replaced.

## Tests and acceptance

- Full automated suite: **283 passed in 39.96s**. Final packaging/health/export
  regressions: 3 passed in 1.10s. Ruff lint and all 45 Python format checks passed.
- Dependency audit: no known vulnerabilities reported; this is not a guarantee
  against future advisories or every possible security defect.
- Final frozen GUI smoke exit **0**. Offline STT, VAD, audio packages, installed
  Windows voices, speech model and selected local Ollama model were ready.
- Final frozen voice diagnostic exit **0**: actual VAD/offline STT/local qwen3:8b,
  Windows playback, same-session follow-up, Chrome/VS Code completed launch tasks,
  standalone wake, compound sleep and mute. Generated PCM; no microphone opened
  by that diagnostic. Process evidence alone does not establish window visibility.
- Frozen wake/time result: endpoint 0.984s + STT 0.688s; playback engine started
  1.859s after speech end. Provider follow-up: STT 0.390s, provider 6.750s,
  playback engine start 8.203s after speech end. These are one-run measurements,
  not acoustic onset or general performance guarantees.
- GUI timer fired 1,846 times. Maximum gap 0.937s includes diagnostic fixture
  generation on the GUI thread; it is not a representative idle benchmark.
- Separate real HyperX capture: 248 frames in 5s, no drops/errors, samples
  discarded. Native speech device/start/stop checks passed.
- **User-confirmed live acceptance:** recognized words initially appeared without
  speech; saved Speak replies was off. After enabling the Assistant-screen
  checkbox, the user heard the wake/time response and confirmed the full
  Hey Jarvis → Open Chrome → And open VS Code → Thanks Jarvis, go to sleep sequence
  worked. This is direct user confirmation, not an agent acoustic recording.
- Speech is saved on; wake permission is saved on following the user's opt-in.
  Other current settings were retained. Both can be disabled from the app.
- The last startup error record is historical: the earlier diagnostic packaging
  omission caused ModuleNotFoundError at `2026-10-12T21:51:53 UTC`. The repaired
  diagnostic and normal startup passed afterward; the record was retained.

## Transfer artifacts

Runtime source through `6170121` was successfully pushed privately. The final
handoff-only commit is identified by Git HEAD and the source export MANIFEST.
Check `git status --short` and `git ls-remote origin refs/heads/feature/handsfree-voice`
to compare it with the remote; do not infer push success from repository creation.

- `transfer/PROJECT_JARVIS_HANDOFF.zip`: committed source/assets/templates/tests/
  documents plus all local Git history in `project-jarvis.bundle`. Per-file hashes
  and exact export commit are in MANIFEST.json; archive SHA256 is alongside it.
- `transfer/JARVIS-Windows-0.2.0.zip`: full tested one-directory build, INSTALL.txt,
  embedded identity and per-file hashes. 154,412,609 bytes, 1,111 verified files.
  SHA256: `8b382625f6f461a9dd7d53c0f385049ddf7a4d5ab1c2bbb41e61b02e2a3b5150`.
- Models, live settings/SQLite, keys, recordings, logs and venv are excluded from
  both deliverable archives and Git. Local data/backups remain on this machine.
  Do not zip the entire transfer directory: it also contains private local backups.
- The unsigned Windows build is staged locally, not uploaded as a GitHub release.
  No installer/updater or fresh-machine acceptance is claimed.

## Remaining acceptance boundaries

Human false-wake rates, accents/noise/far-field, long-idle CPU/RAM, acoustic echo,
experimental voice interruption, hardware disconnection and fresh Windows installs
need broader testing. The exact reported “full stop” incident was not reproduced;
raw markup/URL speech was reproduced and normalized. Live cloud/CUDA are untested.
Dedicated keyword detection, durable reminders/calendar, screen vision, arbitrary
coding tools, autonomous planning and signed distribution remain incomplete.

Exact install/run/build/test/restore commands and priority-ordered continuation
are in PROJECT_HANDOFF.md. The update repair is complete for the tested local
build and user-confirmed sequence; do not infer production release acceptance.

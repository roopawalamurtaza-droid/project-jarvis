# Phase 4.5 reference command-center development release

**15 October 2026 · version 0.4.5 · branch `codex/phase4-5-reference-ui`.**
Repository: [roopawalamurtaza-droid/project-jarvis](https://github.com/roopawalamurtaza-droid/project-jarvis),
now public at the user's request. Continue the existing application; do not
restart development. Read [PROJECT_HANDOFF.md](PROJECT_HANDOFF.md),
[NEXT_STEPS.md](NEXT_STEPS.md) and [TESTING.md](TESTING.md) for final source/build
identity, tests, package, push and transfer records.

## What changed

The user-supplied futuristic screenshot is the primary visual specification.
This phase replaces the presentation of the existing native application with a
working reference command center: custom rounded window/header, luminous
two-line navigation, layered energy core, greeting/context/capability lists,
message cards, a compact illuminated composer, five quick actions, five live
intelligence cards and a movable shared mini assistant. The screenshot is not
used as the whole application's background.

The existing PySide6/Python service, SQLite memory/history, hands-free recognition,
voice conversation state machine, Windows launcher/browser tools, scoped file
tools, routines, one-use approval and emergency-stop controls remain the
application's execution path. There is no new framework, second microphone,
second backend or new third-party dependency. Explicit action receipts retain
their evidence semantics: browser dispatch still does not verify navigation,
inspect pages or complete research.

| Component | Delivered behavior |
| --- | --- |
| Header | Actual version/provider/model; shared voice state; measured CPU/RAM/network; native minimize/maximize/restore/close |
| Navigation | Reference Assistant/Mission Control/Memory/Automations/Workspaces/Browser/Settings entries; all 11 retained views remain reachable |
| Core | Cached original layered QPainter globe, concentric circuits, translucent rings, cyan energy, triangular identity and state-driven light |
| Chat | Native rounded cards, timestamp/avatar, safe Markdown/code blocks, copy/replay, bounded scrollable history and real Ollama streaming |
| Composer | Enter/Shift+Enter, permitted local text preview, shared mic control, measured waveform, interrupt/send |
| Quick actions | Configured browser, existing development request, reviewed study routine, browser search interface and routines view |
| Dashboard | Actual active plans/tasks, measured system charts, configured AI/reported usage, tool duration/error records and exact pending approvals |
| Mini | Shared core/state/levels, native controls, dragging, dismissal and optional always-on-top; no capture of its own |
| Decoration | Original line icons and small original Canva sidebar scenery, packaged locally |

The right dashboard shows indeterminate progress when no percentage can be
measured. CPU/RAM/disk charts keep at most 60 real samples, including unavailable
gaps. Disk is the Windows system volume; network is measured physical RX + TX
through 64-bit native counters. No supported CPU-temperature source is installed,
so temperature remains unavailable. No Alex, GPT-4o, demo tasks, fake resource
numbers or invented completion percentages are copied from the image.

## Visual implementation and comparison

[The visual specification](docs/PHASE45_VISUAL_SPEC.md) records approximate reference
bounds. [The design system](docs/DESIGN_SYSTEM.md) records geometry, tokens,
component contracts, honest measurements and accessibility/motion rules.

The target window is 1440 × 840 logical pixels, with about 242px sidebar and
382px dashboard. Custom QPainter geometry preserves the current controller and
avoids the cost/risk of migrating to QML, Flutter or a browser renderer. Static
orb detail is cached; dynamic motion is bounded. Layered gradients/strokes create
depth without claiming compositor blur or a GPU shader implementation. Original
native icons replace glyphs that rendered as missing characters during the
first actual comparison.

Actual capture iterations:

| Artifact | What it proves |
| --- | --- |
| [phase45-first-render.png](artifacts/phase45-first-render.png) | Initial actual offscreen Qt source render, not a frozen executable |
| [phase45-second-native.png](artifacts/phase45-second-native.png) | Revised source window rendered by the normal Windows Qt platform |
| [phase45-final-native.png](artifacts/phase45-final-native.png) | Refined native source UI with a real local model reply |
| [phase45-final-native-mini.png](artifacts/phase45-final-native-mini.png) | Separate actual mini-widget capture; not pasted into the main screenshot |

The **95% similarity target remains unmeasured**. Comparisons assessed region
proportions, core size/position, navigation hierarchy, title bar, composer, quick
cards, card borders and lighting. The renderer uses original stylized vector orb
lighting rather than the reference's image-like material. Real configured model,
actual empty tasks/approvals and a scrollable transcript legitimately differ from
illustrative screenshot content. Native window rendering does not prove physical
125%/150% scaling or accessibility across other machines.

The original Canva scenery asset ID is **`MAHYBcOJP24`**. Its small derivative at
`src/jarvis/assets/sidebar-canva.jpg` enriches only the decorative footer and is
packaged with the application. Original vector terrain/icons/core remain native.
No copyrighted character/provider logos, whole-reference wallpaper or runtime
Canva connection are required.

## Actual verification recorded so far

- **Baseline: 823 tests passed in 151.65 seconds** before UI changes. The restricted
  execution environment's loopback/socketpair restriction required the normal
  local testing context; the timeout was not treated as a passing test.
- Dashboard/awareness focused verification passed **61 tests**, including exact
  approval IDs, website targets/effects, missing-model/cloud-health labels,
  unavailable values, measured intervals, bounded graphs, literal external text,
  native icons and narrow-column geometry. These overlap the final suite and
  must not be added to its count.
- The normal Windows source UI returned a real **Ollama `qwen3:8b` streamed
  response**, selected all **11 retained views**, and recorded a **0.062-second
  maximum UI timer gap** in the final short sample. Its report identifies
  `frozen: false`, isolated data, no microphone request and no cloud call.
  This verification launched no external apps or websites.
- A separate actual Windows WinRT speech check supplied **172 own-process peak
  samples**, **143 positive**, maximum **0.538369596**. The inactive meter returned
  unavailable. This verifies the process-specific scalar playback path, not PCM
  capture, another application's audio or human hearing.
- Native worker CPU/RAM/system-volume/network measurement succeeded on the
  current Windows machine. CPU temperature was explicitly unavailable.

**Final full-suite result:** **949 passed in 128.50s** after the compact/shutdown
ownership repair; Ruff and all **87** formatting checks passed. An earlier
passing checkpoint ran 949 tests in 114.92s. A 12-test UI/identity check covered
the motion/tray refinements. The first complete attempt passed 943 tests and found a historical
hardcoded version assertion, which was corrected to check the actual release.
Native application captures also passed at Qt scaling factors 1.25 and 1.5;
this does not change or certify Windows display settings on other monitors.

Two isolated six-second native idle samples after a four-second warmup measured
**0.304%** of the 12-logical-CPU machine's capacity with motion and **0.022%**
with reduced motion (3.646% and 0.260% of one logical CPU). Working sets were
187.5/187.7 MiB. The core timer measured 8 Hz and zero ticks respectively.
Microphone, speech, cloud and foreground context were disabled. This is a short
idle sample, not a GPU, leak, voice-load or long-soak benchmark.

**Final packaging and deployment passed:** runtime commit `af909466f48c`,
version 0.4.5, clean build, 36 matching source hashes and both asset hashes.
The frozen smoke, reference UI/local streaming, memory/workflows, actual Windows
actions and generated-speech voice/action/shutdown checks each exited 0.
The compact regression exposed three parentless compatibility labels that could
leave an extra native window and prevent shutdown. Parenting them to the page
repaired natural compact→restore→close; no forced-quit workaround was added.
The final normal window was launched from `C:\Jarvis\dist\JARVIS\JARVIS.exe`
through `Start JARVIS.cmd`; settings, memory count and credential-file hashes
were preserved. Actual identity, successful pushes and verified transfer archives
are in NEXT_STEPS.md. The current 0.4.5 human microphone/mini check is requested
and pending; historical acceptance and synthetic speech are separate evidence.

## Reproduce installation, launch and checks

Use the repository's existing locked setup on Windows with Python 3.12/3.13 and
`uv` installed. Ollama and an installed selected model are required only for
local AI calls. The offline Whisper model remains a separate explicit setup
step. Keys are optional for cloud adapters and must never enter source/docs.

```powershell
cd C:\Jarvis
.\scripts\setup.ps1
.\.venv\Scripts\python.exe -m jarvis --data-dir C:\Jarvis\.local --download-speech-model
.\scripts\start.ps1 -DataDir C:\Jarvis\.local
```

The start script runs source. `Start JARVIS.cmd` runs the existing packaged
`dist\JARVIS\JARVIS.exe`; it does not rebuild source changes. Keep the whole
PyInstaller application folder intact and preserve the existing local data.

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check src tests scripts
.\.venv\Scripts\python.exe -m ruff format --check src tests scripts
.\scripts\package.ps1
```

Capture the actual source UI with isolated data and no microphone/cloud/apps:

```powershell
.\.venv\Scripts\python.exe scripts\verify_phase45.py --native --output artifacts\phase45-local.png --data-dir build\phase45-local-data
```

Add `--settings-from C:\Jarvis\.local --live` only when intentionally checking the
configured local Ollama model. The script still overrides wake/speech/history/
foreground-context permissions to off for this capture. It creates an image,
separate mini image and JSON evidence record. Omitting `--native` uses the Qt
offscreen renderer and must be described accordingly.

After a successful rebuild, the equivalent frozen UI diagnostic is:

```powershell
.\dist\JARVIS\JARVIS.exe --data-dir C:\Jarvis\.local --verify-reference-ui
```

Append `--verification-live` for the explicit local-model check. The output is
stored beneath that data directory; inspect the report's build identity and
`frozen` field. Diagnostics flags do not substitute for normal launch or human
voice acceptance. Existing action/voice checks remain available; their action
and speaker-output flags cause real OS actions/playback and must be identified.

## Controls, privacy and remaining gates

The default composer is trimmed to match the reference. Right-click its microphone
control and choose **Show voice controls** or **Voice settings**. The revealed row
provides **Hold to talk**, **Speak replies**, pause/resume and mute. Hands-free microphone
capture still requires the saved permission and selected device. The sidebar
**Mini** control pins the shared floating assistant; normal tray/background
activation also shares the same voice state. Always-on-top uses the existing
compact setting. Reduced motion affects core, hover and indeterminate progress.

Local Ollama replies stream through the actual provider; OpenAI/Gemini currently
return final replies. Screen vision, page research/summarization, general browser
content control and arbitrary shell execution remain unavailable. Attachments
preview permitted local UTF-8 text through the existing scoped reader; they are
not automatically uploaded. Markdown never fetches embedded media or reads local
files. A clicked link is validated and dispatched through the same HTTPS tool and
approvals as other commands. Approval cards do not bypass exact-target grants,
one-use authorization, cancellation or emergency stop.

Remaining verification includes the human hands-free wake/app/search/follow-up/
sleep sequence, natural spoken punctuation, tray/mini acoustic behavior, diverse
physical 125%/150% display scaling and
longer idle/voice resource checks. These must be reported as actual checks when
completed, with wider acoustic, fresh-PC, screen-reader and signed-distribution
acceptance kept separate. Preserve settings, memory and protected credentials
when replacing the build; never include local data or API keys in the public repo.

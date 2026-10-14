# JARVIS reference command-center design system

Phase **4.5 / 0.4.5** recreates the user-supplied futuristic screenshot inside the
existing native PySide6 application. The reference determines composition,
proportions, hierarchy and lighting. It is not shipped as a wallpaper with hidden
controls. The backend, memory, conversation session, Windows actions and one-use
permissions remain the existing application. The requested **95% similarity is
an objective, not a measured result**.

The approximate reference measurements and comparison procedure are recorded in
[PHASE45_VISUAL_SPEC.md](PHASE45_VISUAL_SPEC.md). Actual delivery evidence and
remaining Windows acceptance gates belong to [PHASE45_RELEASE.md](../PHASE45_RELEASE.md)
and [TESTING.md](../TESTING.md).

## Implementation ownership

| Source | Responsibility |
| --- | --- |
| `src/jarvis/ui_components.py` | Palette, shared styles, cached painted energy core, measured waveform |
| `src/jarvis/ui_shell.py` | Original vector icons, two-line navigation, quick cards, title bar, atmospheric footer |
| `src/jarvis/ui_layout_style.py` | Reference glass panels, chat surfaces, greeting and composer styles |
| `src/jarvis/ui_dashboard.py` | Five local-data intelligence cards, sparklines and exact task-ID signals |
| `src/jarvis/ui_chat.py` | Native message cards, safe Markdown, copying and speech replay |
| `src/jarvis/ui_mini.py` | Movable miniature view sharing the existing controller |
| `src/jarvis/desktop.py` | Real data, security checks, navigation, window behavior and action wiring |
| `src/jarvis/awareness.py` | Worker-side read-only CPU, RAM, disk, network and supported GPU measurements |
| `src/jarvis/audio_meter.py` | Optional Windows peak values for this exact process's playback sessions |

PySide6/QPainter was retained to avoid a framework rewrite, a second backend or
duplicate audio capture. Static core detail is cached by geometry, palette and
display scale; bounded dynamic rings and glow are painted over it. No QML,
WebEngine, OpenGL requirement or new third-party dependency was introduced.
Native QPainter rendering is not a claim of a GPU shader pipeline or compositor
blur. Glass depth comes from gradients, translucent strokes, borders and lighting.

## Composition and geometry

The command center opens at **1440 × 840 logical pixels** with a **760 × 560**
minimum. Its custom rounded shell contains a roughly 56px header, a 242px sidebar,
a flexible central canvas and a 382px intelligence dashboard, separated by 12px
gutters. The center keeps greeting/context/core/capabilities above the transcript,
then the illuminated composer and 78–84px quick cards. Preferred core geometry is
350 × 350 logical pixels; the hero area is 342px high at the target size.

At smaller widths, optional telemetry and supporting capability text collapse;
the dashboard is hidden below 1260px and its information remains accessible in
Mission Control, System and Diagnostics. Sidebar width drops to 186px below
1150px. Navigation scrolls when the available height is short. A shorter window
reduces the hero to 260px. Controls and actual text remain native widgets.

The retained compact command center opens around 460 × 550 with a 430 × 530
minimum. It hides the reference header/sidebar/dashboard/quick cards, keeps the
last response and input controls, and limits the core to 110px height. Expanding
restores the new reference constraints and saved normal geometry. This compact
window is distinct from the separate 204 × 214 miniature tool window.

Frameless window controls invoke native minimize, maximize/restore and close.
Title-bar dragging and edge resizing use Qt's system-move/resize calls. High-DPI
icon variants and logical geometry support Qt scaling; physical 125%/150% display
acceptance must be recorded separately from rendering tests.

## Color, typography and imagery

| Token | Value | Role |
| --- | --- | --- |
| background | `#030c14` | Near-black midnight canvas |
| surface | `#071724` | Dark glass panels |
| raised | `#0c2132` | Inset controls |
| border | `#173b51` | Quiet cyan-blue boundaries |
| text | `#dceaf6` | Main text |
| muted | `#8296ae` | Supporting information |
| accent | `#20c9ff` | Current selection, core and primary actions |
| blue | `#468dff` | Processing and execution detail |
| warning | `#efb864` | Approval state |
| error | `#ed737e` | Actual failure or muted warning detail |
| spacing | `4, 8, 12, 16, 24, 32` | Shared logical-pixel spacing scale |

Segoe UI provides actual text, with approximately 13px body text, 10–12px captions,
24px greeting text and a spaced 23px JARVIS wordmark. Large surfaces use 11–16px
corners, small cards 8–11px and the composer about 22px. Borders are normally one
logical pixel. Bounded gradients and translucent strokes provide glow without
heavy blur on each widget. Native keyboard focus and text labels remain visible.

All identity and control icons are original scalable vector geometry, including
dashboard symbols and chat avatars. They do not depend on optional Unicode icon
fonts, provider trademarks or movie artwork. A browser globe represents the
configured browser rather than copying Chrome's logo.

An original Canva scenery asset, **`MAHYBcOJP24`**, was created for this phase.
Its small packaged derivative is `src/jarvis/assets/sidebar-canva.jpg`, used only
inside the decorative sidebar footer. Vector terrain, lighting and identity
complete that area. Canva is not contacted at runtime. This successful Phase 4.5
asset supersedes the earlier Phase 3 generation attempt that produced no asset;
no completed Phase 3 moodboard is retroactively claimed.

## Truthful data contracts

The reference's Alex, GPT-4o, chat, running tasks, token count and resource values
are illustrative. None becomes live application data. The greeting uses the
configured timezone; no incidental personal name is inserted. The top bar and
AI card show the configured provider/model, reported usage and measured latency.
An untested health check says **Not checked**, a missing model says **Model
missing**, and configured cloud credentials remain **Unverified** until tested.
Full health detail remains available in the tooltip/diagnostics.

Context and capability lists distinguish local memory, system access, permitted
tools, scoped file reading, browser search and enabled routines. Screen vision
and real-time page research are explicitly unavailable. Browser search means an
authorized browser launch, not observed page reading or completed research.

The dashboard accepts `update_activity(jobs, tasks, action_runs, workflow_runs,
stopped=False)`, `update_system(system)` and `update_ai(provider, model, health,
latency=None, usage=None)`. It performs no I/O or execution itself. Unknown
progress remains indeterminate; completed plan steps may produce a real fraction.
Rows and charts are bounded, and absent samples remain gaps rather than zero.
System history retains at most 60 samples per chart. Refresh reads execute on
workers, not the GUI thread.

Disk means caller-available usage of the Windows system volume, including quota
effects. Network means connected physical-interface RX + TX byte deltas, not
packet content or a network speed estimate. The first interval and counter/
adapter changes remain unavailable. CPU temperature has no supported source on
the current implementation and displays an em dash. Native adapter identity is
ephemeral inside the metrics provider and is not sent to the UI or persisted.

Approval cards show the actual target, a concise one-use effect and a Details
control. Approve/Deny emit the **exact task ID**, never a truncated identifier or
an automatic authorization. Existing TaskEngine controls revalidate permission
and target. External labels are literal text and bounded/elided. Markdown blocks
may format assistant text, but embedded media cannot read local files or fetch
remote resources; clicking a URL passes through the existing public-HTTPS
validator and authorized website tool.

## Voice and core states

`CoreWidget` receives `set_state(name)`, `set_level(value)`, `clear_level()` and
`set_reduce_motion(enabled)`. `WaveformWidget` receives the same state/level
updates with a bounded measured history. The main core, title/composer waveforms
and mini view consume the shared controller state. They never start an additional
microphone or model request.

| State | Actual meaning | Treatment |
| --- | --- | --- |
| idle | No active request | Restrained breathing and layered energy rings |
| wake | Authorized wake capture is active | Subtle readiness motion and real mic RMS when available |
| activated | Wake acknowledgment | Brief energy pulse |
| listening | Command/follow-up capture | Measured mic RMS drives light and waveform |
| thinking | Model generation/transcription | Controlled ring motion |
| tool | Task or routine is executing | Execution ring emphasis |
| speaking | Windows speech playback | Own-process measured peak when available; otherwise named state |
| approval | Exact pending action awaits a decision | Amber state and explicit decision card |
| error | Actual voice/operation failure | Restrained red warning |
| muted | Voice/microphone muted | Dim core and explicit muted state |

Microphone RMS and playback peak are different scalar measurements. Windows
`IAudioMeterInformation` may provide playback peaks only after an active,
non-system session reports this exact JARVIS PID. This does not capture PCM,
activate endpoint-wide metering, monitor another application's sound, change
volume or bypass microphone permission. Unavailable meters remain unavailable;
ornamental rotation is never an audio sample or proof of successful recognition.

The trimmed main composer uses an input microphone control. Right-click it and
choose **Show voice controls** or **Voice settings**. The revealed control row
provides pause/resume and mute, with the retained **Hold to talk** path and
**Speak replies** setting. Hands-free
capture still requires saved opt-in. The **Mini** sidebar control pins the shared
miniature view. Tray/background activation uses the same engine. Optional
always-on-top follows the existing compact setting; close/dismiss hides the mini
without creating another backend.

## Motion, accessibility and validation

The core timer is capped at about 60 FPS during visible active animation, 12 FPS
for wake readiness and 8 FPS idle. Hidden/minimized widgets stop ornamental
timers. Muted/error/approval states remain static. Reduced motion stops the core
timer, hover transitions and busy progress animation while real state/text
updates continue. Waveforms have no random-motion timer; only measured samples
change their history.

Enter sends; Shift+Enter inserts a line. Ctrl+K opens the command palette. Native
focus, copy, speech replay, scrolling, resize and navigation remain functional.
Streaming text is received from Ollama's real NDJSON response; cloud adapters
currently deliver a final response. A streaming view is not fabricated typing.

The inspected source captures include an offscreen first render, normal Windows
second/final captures and a separately captured mini widget. They validate the
actual source UI and were compared with the supplied image for geometry, hierarchy,
color and depth. They do not establish a numerical similarity, frozen-build
delivery or human voice acceptance. Remaining differences include stylized vector
orb lighting, real provider/empty data, original icons and the scrollable transcript.
Read the release record for current test results and remaining gates. Older Phase
3 scaling and idle-resource samples remain historical evidence, not measurements
of the new renderer. Diverse physical DPI, screen-reader and long-soak checks
remain separate acceptance work; no tested light theme is implemented.

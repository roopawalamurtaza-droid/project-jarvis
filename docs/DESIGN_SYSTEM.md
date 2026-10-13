# JARVIS Ambient Intelligence design system

The Phase 3 interface continues the existing native PySide6 application. Its visual identity is original: restrained charcoal and midnight navy surfaces, cyan emphasis, silver text, amber approvals and red errors. ULTRON is an engineering codename, not a character, logo or voice. No Marvel artwork or copied screen design is used.

## Source of truth

`src/jarvis/ui_components.py` owns the reusable color tokens, Qt stylesheet and painted `CoreWidget`. `src/jarvis/desktop.py` supplies actual controller and job states. These are shipped application components; a concept board is not proof of functional integration.

Canva design generation was attempted with an original, non-sensitive concept brief. The service call did not return a job identifier or completed artifact before interruption. No Canva moodboard is included or claimed as completed. Canva and Figma capabilities were discoverable, but no Figma design was required for the native implementation. Native vector painting is the delivered workflow and needs no remote design service at runtime.

## Visual language

- Backgrounds: charcoal canvas, navy panels, slightly brighter inset controls.
- Accent: cyan for selected navigation, the primary action and active assistant states; soft blue for informational detail.
- Text: readable light foreground with muted secondary information. Essential state is conveyed in words as well as color.
- Warning: amber for required approval; error: red for an actual failed operation. Muted microphone is subdued and explicitly named.
- Geometry: rounded cards, thin quiet borders, consistent spacing and generous breathing room. No decorative random telemetry.
- Type: native Windows Segoe UI; headings, body text and captions have a clear hierarchy. Text remains native Qt text rather than an image.
- Spacing: use multiples of four logical pixels, with larger gaps between workflow groups. Compact mode reduces surrounding panels rather than shrinking readable controls.
- Icons: original rings and the native application mark; text remains present for critical actions. No copyrighted character or logo assets.

The stylesheet is the concrete palette and typography specification. Qt uses logical widget dimensions and native text rendering under Windows display scaling. The command center offers progressive disclosure through separate Assistant, Mission Control, Memory Explorer, Timeline, Workflows, System, Diagnostics, Business and Settings views. Compact mode and the background activation overlay share the core instead of introducing a different visual identity.

| Token | Value | Purpose |
| --- | --- | --- |
| background | `#0b1018` | Main canvas |
| surface | `#111b29` | Grouped panels |
| raised | `#172436` | Raised surfaces |
| border | `#293b50` | Quiet boundaries |
| text | `#e2edf7` | Primary text |
| muted | `#a2b3c7` | Supporting text |
| accent | `#78dce7` | Active state and primary actions |
| blue | `#95b9f7` | Processing and tool state |
| warning | `#efbf79` | Approval required |
| error | `#f19a9e` | Actual error state |
| spacing | `4, 8, 12, 16, 24, 32` | Logical-pixel spacing scale |

The current stylesheet uses 13 logical pixels for body text, 23 for headings and 25 for the wordmark. The vector core fits a preferred 190 by 200 logical-pixel area and a 110-pixel-high compact area; its auxiliary text is smaller and must be checked under actual display scaling.

## Core state contract

The widget receives `set_state(name)`, `set_level(value)`, `clear_level()` and `set_reduce_motion(enabled)`. Its state input comes from real microphone, speech, conversation, approval and worker activity. A ring animation represents the named state; it is not a confidence score or evidence that an operation succeeded.

| State | Meaning | Visual behavior |
| --- | --- | --- |
| idle | No request currently being processed | Quiet breathing |
| wake | Authorized wake listening is active | Restrained readiness motion |
| activated | Real wake activation was acknowledged | Brief acknowledgment |
| listening | Actual command capture is active | Measured microphone amplitude when supplied |
| thinking | A provider request is running | Controlled processing motion |
| tool | A tool or workflow operation is running | Distinct execution motion |
| speaking | Native speech playback is active | Playback-state motion; no invented PCM waveform |
| approval | A concrete action requires a decision | Amber state and explicit label |
| error | A real controller or operation error exists | Error text and red emphasis |
| muted | Microphone disabled or listening paused | Unambiguous muted appearance |

`set_level()` accepts only a measured input. Clear the level when audio is unavailable, capture is disabled, or playback has no PCM measurement. The current native speech backend does not expose output amplitude, so speaking is labeled as playback state rather than presenting a fabricated waveform. Measured microphone level is not a transcription-success claim.

## Motion and accessibility

Reduced motion disables the widget timer. Hidden widgets stop animating; bringing the widget back makes the timer depend on the current state and preference. Idle motion uses eight frames per second, wake listening twelve and active states twenty. Muted, error and approval states do not run an animation timer. State changes and text continue to work with animation disabled. The painted core fits the available rectangle in compact and full layouts.

Keyboard focus remains visible. Text entry, navigation, approvals, interrupt and emergency stop remain native accessible controls. `Ctrl+K` opens the command palette. A mouse or microphone is not required to use the command center. Warning and error states never depend on color alone.

The delivered palette is dark. A tested light theme is not implemented; changing application colors arbitrarily is not a supported light rendering mode. Additional scaling, contrast, screen-reader and reduced-motion acceptance on diverse Windows displays must be recorded as actual tests, not inferred from Qt support.

## Honest presence and privacy

Opening a window does not authorize microphone capture, clipboard access, screen capture or foreground-window context. The presence follows existing opt-in settings. Returning to the tray keeps only explicitly authorized background listening; the overlay displays actual activation and can be dismissed. System metrics are retrieved values, with unavailable information identified. No random graphs, fabricated progress or simulated speech activity is shown.

Future changes must preserve this boundary: state feedback explains a real operation, and measured visualization requires a real source. If a source is unavailable, show its absence plainly.

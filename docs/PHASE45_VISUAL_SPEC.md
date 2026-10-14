# Phase 4.5 reference visual specification

The supplied 1600 × 900 screenshot is the visual source of truth. The application
is recreated with actual native PySide6 widgets, custom Qt vector painting and
the established backend. The screenshot itself is not shipped as a background.
The requested 95% similarity is a design objective; no measured percentage is
claimed without a defined perceptual metric and comparable application renders.

## Measured composition

Measurements are approximate image pixels at the supplied reference resolution.
Qt uses logical pixels; compare the content area after excluding the desktop
wallpaper, taskbar and any native window frame.

| Region | Reference bounds | Target interpretation |
| --- | --- | --- |
| Application | x80–1521, y20–842 | About 1440 × 822, widescreen, 16px rounded corners |
| Header | y21–79 | 56–60px height, one horizontal live-state band |
| Sidebar | x85–330, y80–834 | 245px outer width, rounded glass surface |
| Center | x342–1104, y80–834 | About 762px width, strongest visual emphasis |
| Intelligence dashboard | x1117–1508 | About 391px width, five stacked cards |
| Horizontal gutters | 12–13px | Consistent 12px separation |
| Navigation item | x94–318, first y101–160 | 224 × 60px, icon then two lines of text |
| Core envelope | Approximately x562–939, y115–439 | 350–375px sphere with layered rings |
| Greeting | x365, y120 | 27px primary text, 20px supporting line |
| Context list | x368, y222 onward | 10px tracked heading, 12px item text |
| Capability list | x953, y222 onward | Narrow list, icon plus real availability |
| Chat | x363–1065, y442–644 | Dark rounded message cards, avatar and timestamp |
| Composer | x360–1090, y661–724 | About 63px high, illuminated outline |
| Quick cards | x364 onward, y739–820 | 81–84px high, 10px gaps |
| Floating assistant | x1406–1579, y662–844 | Separate 173 × 182px tool window |

The center is roughly twice the dashboard width; the sidebar remains narrower
than either. The hero, conversation, composer and quick cards retain this vertical
order. Smaller windows may hide supporting text or collapse optional telemetry;
they must keep native controls, readable labels and all navigation accessible.

## Surfaces, typography and lighting

The composition uses midnight blue and near-black surfaces rather than flat
gray. Use `#040c14` for the canvas, `#07131e` for primary panels, `#0b1b2b` for
raised areas and `#123447` for quiet boundaries. Electric cyan `#31bde9` and pale
cyan `#8feaff` emphasize real active states. Primary text is `#d5dfeb`, secondary
text `#7a8ea8`, available-state green `#18bc9f` and approval amber `#e3b361`.
Actual painted gradients may vary slightly to preserve readable contrast.

Panel borders are usually one logical pixel. Glows are layered translucent
strokes or bounded gradients rather than expensive blur on every control. Corner
radii are 10–14px for large panels, 8–11px for buttons and 20–26px for the composer.
Segoe UI is the installed Windows font. Body text is around 12–14px; secondary
labels are around 10–11px. The wordmark uses increased letter spacing. Long actual
model names and application names must elide or wrap rather than overlapping.

## Component contracts

`src/jarvis/ui_shell.py` owns the original line icons, native navigation buttons,
quick cards, header and atmospheric sidebar footer. Native QPushButton semantics
provide mouse, keyboard, focus, enabled-state and accessibility behavior.

- `make_icon(name, color, size)` supplies original QPainter geometry in multiple
  device-pixel-ratio variants. No proprietary provider or application logos are
  copied; a globe stands for the configured browser.
- `NavButton(title, subtitle, iconname)` retains `clicked` and `setChecked`.
- `QuickActionCard(title, subtitle, iconname)` retains `clicked`; the controller
  supplies the actual action. Preferred height is 84px.
- `HeaderBar(version, window_controls=False)` exposes plain-text state, model,
  provider, CPU, RAM and network labels. Metrics start unavailable. A waveform
  may be placed in `waveform_host` only when supplied by measured audio.
- Custom-frame controls emit minimize, maximize/restore and close requests.
  Dragging uses Qt's native system-move API. The controller handles native edge
  resizing and connects all requests. Native-frame mode omits duplicate controls.
- `SidebarAtmosphere` paints an original deterministic landscape, atmospheric
  dome, city lights and identity. Optional packaged Canva art enriches scenery.
  No network loading, simulation of status, or continuous footer timer is used.

The central core and waveform live in `ui_components.py`; the dashboard belongs
to `ui_dashboard.py`. `desktop.py` supplies actual voice, jobs, provider, security
and conversation data. Component presence alone never establishes capability.

## Data and motion rules

Do not copy the screenshot's personal name, chat, example tasks, completion
percentages, GPT-4o choice or resource values into live state. The local greeting
uses the configured name only when present. Unknown latency, token usage,
temperature, progress or output amplitude remain explicitly unavailable.

Microphone waveforms require actual measured microphone amplitude. Playback
without PCM exposure receives a speaking-state treatment, not invented amplitude.
Decorative orb rotations represent the named application state only. Hide timers
when components are hidden or minimized; reduced motion disables ornamental
animation. Hover animation lasts about 140ms and never delays action dispatch.

Availability lists must name disabled or limited capabilities. Browser dispatch
does not become page inspection because the interface has a Browser destination.
Approvals use the existing permission system; no cosmetic acceptance may execute
an operation. The floating assistant shares the existing voice engine and backend.

## Screenshot comparison and refinement

Capture the real application after layout and state updates have settled. Store
the current build identity, logical geometry, Qt scale and actual rendering method
with each capture. Reference comparisons use the application crop, with no desktop
or incidental example data requirement. Check at least the target widescreen
geometry and a smaller supported geometry, then Qt scale factors 1, 1.25 and 1.5.
Offscreen native renders test layout; they do not prove physical display or voice
acceptance. A normal Windows window capture must be identified separately.

For each iteration compare sidebar/center/dashboard widths, header height, core
diameter and center, hero/chat/composer/quick-card positions, type sizes, borders,
color hierarchy and atmospheric depth. Record visible differences, correct the
largest geometry mismatch first, and repeat. Never call a generated mockup an
application screenshot. Contrast, resizing, native controls, navigation, approvals
and real voice operation remain acceptance gates alongside visual comparison.

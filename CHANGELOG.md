# Changelog

## 0.2.0 — 2026-10-13

- Opt-in local wake phrase + WebRTC VAD, bounded offline transcription, automatic
  requests, deterministic states, follow-ups, time-aware greetings and end commands.
- Separate speech normalization, speaker selection, rate/pronunciations and
  completion/stop callbacks. Ordinary sentence punctuation is preserved.
- Exact human app/project commands use existing approvals and path restrictions;
  Chrome added to fixed application allowlist.
- Persistent voice/login/tray controls and optional actual-event proactive speech.
- Fixed empty transcription, stale capture, replacement playback, muted Save and
  cancellation races, with executable integration regressions.
- Repair: launcher still used Phase 1 binary while new source was uncommitted.
  Added embedded version/commit/date/source hashes and startup health in Settings.
- Handoff/export documentation. Literal "full stop" remains unreproduced;
  spoken raw Markdown was reproduced and fixed. Human acoustic accuracy is unverified.

## 0.1.0 — 2026-10-13

- Initial local-first Windows desktop/service architecture and locked environment.
- Ollama/OpenAI/Gemini adapters, bounded conversation, cancellation and privacy gates.
- Push-to-talk offline Whisper and installed Windows speech voices.
- SQLite memory/conversation/task/audit storage and current-user DPAPI credentials.
- Strict file/app tools, concrete approvals, restart recovery and emergency stop.
- Native chat/activity/memory/audit/settings views, floating mode and system tray.
- Installation, packaging, automated tests and live verification procedures.


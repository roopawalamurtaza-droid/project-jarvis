# Update verification and repair — 13 October 2026

## Root cause confirmed

`Start JARVIS.cmd` selected `C:\Jarvis\dist\JARVIS\JARVIS.exe`, the Phase 1
executable last written **2026-10-12 20:50:00 UTC**. The hands-free source files
were newer and uncommitted. The frozen executable had not been rebuilt after
those changes. Source-only success did not update the launched application.

Saved speech output was false; `wake_enabled` was absent and defaulted false.
Thus even new source must receive explicit microphone opt-in in Settings.
No JARVIS process was running at the audit, and no matching JARVIS shortcut was
found under the checked current/public Desktop and current-user Start Menu.
No matching current-user LocalAppData installation directory was found. This is
a scoped inspection, not a claim that every disk/location was searched.

Logs contained historical Phase 1 packaging ImportErrors followed by successful
launches. The cause was earlier Qt ICU DLL contamination; the package script's
sanitized PATH fix is preserved. Source hands-free initialization, offline model,
actual audio capture and service integration passed subsequent diagnostics.
The desktop uses its backend service in-process, not a separate web frontend.

## Actual repairs

The first Phase 2 rebuild found an actual packaging error: PyInstaller's generic
WebRTC hook requested distribution metadata named `webrtcvad`, but the Windows
binary wheel is distributed as `webrtcvad-wheels`. A project-local hook now
collects the correct metadata/native module. Final frozen checks, not source
test success, determine whether this repair passes.

- Rebuild includes handsfree.py, conversation.py, voice_controller.py,
  speech_text.py, modified desktop/settings/provider command integration, Qt
  Multimedia, WebRTC binary VAD, timezone data, and offline STT dependencies.
- Embedded version/commit/branch/build UTC date/source hashes distinguish the
  frozen artifact from a dirty checkout. Settings displays actual executable,
  speech/wake/microphone/backend status and last reported startup/voice error.
- Automatic read-only startup check queries local Ollama readiness and offline
  speech model/package availability; it records or speaks nothing. Smoke checks
  override wake permission to avoid passive recording during diagnosis.
- Exact compound **Thanks, Jarvis. Go to sleep.** now ends the session.
- Source review fixed cancellation/no-speech recovery, stale audio, playback-tail
  and replacement callback races, and Settings Save reopening a muted microphone.
- Packaging does not alter `.local` settings, SQLite memory or DPAPI credentials.
  Old build/data backup and final artifact details appear in NEXT_STEPS.md.

## Feature evidence

| Feature | Status | Verification boundary |
| --- | --- | --- |
| Hey Jarvis detection | IMPLEMENTED AND VERIFIED | Generated PCM through actual offline STT; human accent/room acceptance pending |
| Automatic microphone listening | IMPLEMENTED AND VERIFIED | Explicit opt-in; actual 5s device capture, discarded samples |
| VAD | IMPLEMENTED AND VERIFIED | Installed WebRTC 20ms framing and generated speech/silence |
| Hands-free transcription | IMPLEMENTED AND VERIFIED | Actual offline base.en, no Hold button |
| Automatic AI request | IMPLEMENTED AND VERIFIED | Actual local qwen3:8b from automatic voice turn |
| Spoken automatic replies | IMPLEMENTED AND VERIFIED | Windows engine startup/completion and output-device test; not human audibility |
| Natural follow-ups | IMPLEMENTED AND VERIFIED | Same session second question, generated Chrome/VS Code utterances, timeout unit tests |
| Time-aware greetings | IMPLEMENTED AND VERIFIED | Fake-clock timezone tests; actual standalone synthetic wake and Windows playback |
| Speech formatting/punctuation | IMPLEMENTED AND VERIFIED | Reproduced raw asterisks/URLs fixed; normal dots retained. Exact reported full-stop incident not reproduced |
| Timeout / return to wake | IMPLEMENTED AND VERIFIED | Deterministic clock tests, compound sleep and resumed wake in actual desktop |

The above does not claim an actual person spoke the complete demonstration.
Synthetic PCM tests exercised the pipeline, real Windows app launch requests and
local provider; real microphone was tested independently. Full duplex/room echo,
far-field and accents are not verified. Optional headset voice stop is off by default.

## Demonstration performed and repeatable checks

Source diagnostic recognized wake+time, a second provider question, **Open
Chrome**, **And open VS Code**, compound sleep, then standalone wake/greeting.
Both application tasks completed with process_running evidence, through the
existing permission engine. Manual mode regressions still require approval.
Application window visibility and project loading are not inferred from a PID.

```powershell
.\.venv\Scripts\python.exe scripts\verify_voice_desktop.py --data-dir .local --actions
.\dist\JARVIS\JARVIS.exe --data-dir C:\Jarvis\.local --smoke-test
.\dist\JARVIS\JARVIS.exe --data-dir C:\Jarvis\.local --verify-voice-update --verification-actions
```

The last check runs embedded diagnostic files against frozen modules and the
actual packaged GUI/service/STT/TTS. It generates clearly labeled speech, opens
no microphone, and launches apps only when `--verification-actions` is supplied.
Reports are local ignored files. Final package outcome is recorded in NEXT_STEPS.md.

The first frozen GUI smoke passed, but its runpy-based voice diagnostic failed
because copied scripts did not cause PyInstaller to analyze imports such as
`wave`. Packaging now explicitly analyzes both diagnostic modules. This is a
packaging fix; source-only success was not accepted as packaged verification.

## Using the repaired application

Launch **Start JARVIS.cmd**. In Settings confirm version 0.2.0, runtime build commit
and path `C:\Jarvis\dist\JARVIS\JARVIS.exe`. Refresh/select devices; turn on
the hands-free microphone checkbox. On Assistant turn on **Speak replies** beside
**Hold to talk**, then return to Settings and Save. For a friendly
time-aware greeting choose friendly. Actual local time determines the wording.

Say Hey Jarvis, wait until playback ends and input is active, then Open Chrome,
And open VS Code, Thanks Jarvis go to sleep. Permission mode still applies.
Keep experimental voice interruption off with speakers. Pause/Mute closes capture.

If no input arrives, check Windows microphone permission and selected device;
if AI fails, start Ollama/select an installed model and rerun health. If an older
window remains, use its Exit before replacing the complete build folder. No old
instance was killed during this repair. No administrator installation is needed.

After the replacement launched, the user reported recognized words but no speech.
The saved speech flag remained false. The initial instructions placed Speak
replies in Settings, but its actual checkbox is on Assistant; this documentation
error was corrected. Enabling it produced an audible wake/time reply, and the
user then confirmed the entire requested Chrome/VS Code/follow-up/sleep sequence
works. The enabled speech preference was saved without replacing other settings.

Remaining verification: broader false wakes/natural pauses, punctuation with the
user's selected voice and a second Windows installation. The user's report is
live acceptance evidence, not an agent acoustic recording or broad accuracy study.

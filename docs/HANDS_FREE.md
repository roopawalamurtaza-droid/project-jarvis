# Enable and verify hands-free voice

Launch `C:\Jarvis\Start JARVIS.cmd`; it uses `dist\JARVIS\JARVIS.exe` and `.local`.
Source edits require rebuilding the executable with `scripts\package.ps1`.

1. On the Assistant screen, check **Speak replies** beside **Hold to talk**.
   This checkbox is not inside the Settings form.
2. In Settings, inspect version, Git commit, build time and executable path.
   Run startup health check. Ollama and the selected model should be ready.
3. Refresh audio devices; choose microphone, voice and speaker.
4. Check **Allow hands-free microphone listening on this
   PC**, and save. This authorizes listening now and after restart.
5. Say **Hey Jarvis**, wait for acknowledgment, then speak. Or say **Hey Jarvis,
   what time is it?** in one utterance. Follow-ups need no wake phrase for 20 seconds.
6. **Thanks, Jarvis. Go to sleep.** returns to passive wake detection. Thanks
   inside a continuing request does not end the conversation.

The indicator distinguishes active input, gated input with a stream still open,
off, and errors. Pause closes the microphone; Resume reopens it. Mute cancels
requests, stops speech and closes input. Push-to-talk remains available after pause.

Normal playback discards microphone input and waits 350 ms after speech to avoid
self activation. Interrupt stops playback. Optional voice stop recognition is
for headsets, recognizes complete Jarvis stop / Stop talking / Wait phrases,
needs endpoint/STT time, and has no acoustic echo cancellation. Keep it off with
speakers. Its synthetic checks are not real-room reliability evidence.

Offline Whisper checks speech segments for the configured wake phrase. WebRTC
VAD and an RMS floor detect speech separately. Unrelated audible speech invokes
local transcription before rejection; silence does not. No passive transcript
goes to cloud AI. Activated commands follow explicit provider/cloud settings.
This baseline is slower than a dedicated wake model.

Lower RMS/noise rejection for clipped quiet speech; raise them for false starts.
Lengthen the ending pause if natural pauses split commands. Settings persist
activation/utterance/follow-up timeouts, timezone, speech rate, greeting mode and
pronunciation dictionary. Speech preparation preserves ordinary punctuation and
keeps the original written response intact.

Install the missing speech model explicitly, as one command:

```powershell
.\.venv\Scripts\python.exe -m jarvis --data-dir .local --download-speech-model
```

A disconnected microphone enters Error. Refresh/select a valid device, save,
and resume. Check Windows Privacy & security > Microphone if access is denied.
Start with Windows uses the current user's Run entry. Minimize-to-tray is optional.
Proactive speech defaults off and reports actual task events, with quiet hours
and frequency limits. Scheduling, screen observation and autonomous planning are absent.

Complete a human spoken demonstration on your microphone before relying on
accent/noise/far-field accuracy. Automated synthetic tests validate implementation
and state transitions; they do not simulate a person speaking in your room.

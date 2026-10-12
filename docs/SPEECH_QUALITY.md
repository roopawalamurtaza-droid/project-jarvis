# Speech quality investigation and verification

The Phase 1 application sent the complete written model response directly to
`QTextToSpeech.say`. It had no speech-specific preparation. WinRT therefore saw
Markdown symbols, links, code, and machine output as ordinary input text.

On this Windows installation, a native WinRT/Microsoft George synthesis of
`**Ready.**` produced audio transcribed locally as “asterisk, asterisk, ready”
followed by more asterisks. A raw HTTPS link also produced garbled spoken protocol
and path punctuation. These are reproduced defects in the original pipeline.
The same normalized reply produces “Ready. Your task is complete. Ask me for
help.” with the written response preserved.

The exact reported phrase “full stop” was **not reproduced** by ordinary sentence
periods, numbered lists, an isolated period, spaced periods, dotted initials, or
a filename in either tested engine. We cannot assign an exact cause to that
specific incident without its original response and selected voice. The fix
addresses the demonstrated formatting path, preserves sentence periods and
pauses, and provides pronunciation substitutions for voice-specific cases. It
does not remove all punctuation or change the displayed answer.

## Speech preparation

`jarvis.speech_text.normalize_speech` produces a separate spoken string:

- Strip Markdown headings, emphasis, list markers, and link syntax while keeping
  their human-readable content and pauses.
- Keep sentence periods, commas, questions, exclamations, decimal numbers, and
  ordinary thousands separators. Let the installed voice pronounce numbers.
- Expand valid ISO dates and common ambiguous abbreviations such as `e.g.` and
  `p.m.`. Invalid dates remain unchanged.
- Speak bare web addresses by domain. Omit credentials, query strings, and
  fragments; labeled links use their label.
- Skip fenced code, raw JSON, log/trace lines, programming statements, and
  Markdown tables. Written details remain available in the chat.
- Apply the saved pronunciation dictionary as literal, case-insensitive,
  whole-token replacements once. For example, `API` can become `A P I`, or a
  preferred product name can receive a phonetic spelling.

The speech adapter has one active utterance. A new accepted utterance stops the
previous one. `speaking` covers synthesis startup as well as playback;
`on_finished(callback)` fires once when speech completes, stops, or errors.
`speak` returns `False` for machine-only content, allowing the conversation
controller to continue without waiting for playback that never started.
All speech controls and callbacks run on the desktop thread.

Speaker devices are persisted using the hexadecimal form of Qt's device ID.
The installed PySide6 6.12 constructor accepts the documented WinRT
`audioDevice` parameter. An unavailable selected device produces an actionable
error; an explicitly selected speaker is never silently ignored by the SAPI
fallback. Windows default remains supported with either engine.

## Evidence from this machine

`scripts/verify_speech_quality.py` generates synthetic WAV fixtures through native
Windows WinRT and SAPI, then transcribes them with the existing offline Whisper
model. Installed PySide6 does not expose Qt's C++ `synthesize` method, so the
WinRT fixture generator calls the same `SynthesizeTextToStreamAsync` backend
directly. It never records the microphone or uploads audio.

Tested voices: Microsoft George (WinRT) and Microsoft David Desktop (SAPI).
Original and normalized fixtures and JSON transcripts are separate under
`.local/speech-quality/raw` and `.local/speech-quality/normalized`.

Real Qt output through **Headphones (HyperX Cloud III)** also verified the device
constructor, completion, immediate stop, and replacement playback:

| Event | Time after test start |
| --- | ---: |
| First utterance entered Speaking | 0.078 seconds |
| First utterance stopped and completed | 0.719 seconds |
| Second utterance entered Speaking | 0.986 seconds |
| Second utterance completed | 2.149 seconds |

The stop was scheduled at 0.700 seconds. Exactly two completion callbacks fired;
speech was inactive afterward, with no playback error or timeout. These timings
measure engine state events, not acoustic onset or a person's hearing. Synthetic
transcripts can contain recognition errors and do not establish real-room
intelligibility, microphone echo rejection, or broad voice accuracy.

Reproduce the synthetic comparison:

```powershell
.\.venv\Scripts\python.exe scripts/verify_speech_quality.py --data-dir .local --synthesize
.\.venv\Scripts\python.exe scripts/verify_speech_quality.py --data-dir .local --synthesize --normalized
```

Append `--playback --select-first-speaker` to opt in to the actual speaker
completion/stop test. This can play audible synthetic speech. JSON reports stay
under the selected local data directory.

## Primary references

- [Qt speech engines and WinRT audioDevice parameter](https://doc.qt.io/qt-6/qttexttospeech-engines.html).
- [Qt speech states, stop semantics, and synthesis capability](https://doc.qt.io/qt-6/qtexttospeech.html).
- [Qt WinRT engine source](https://raw.githubusercontent.com/qt/qtspeech/dev/src/plugins/tts/winrt/qtexttospeech_winrt.cpp)
  calls `SynthesizeTextToStreamAsync` with plain text.
- [Windows SpeechSynthesizer](https://learn.microsoft.com/en-us/uwp/api/windows.media.speechsynthesis.speechsynthesizer)
  distinguishes plain text synthesis from SSML synthesis.

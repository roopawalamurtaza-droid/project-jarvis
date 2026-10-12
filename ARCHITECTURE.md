# Architecture

The native desktop and optional HTTP API share `JarvisService`. The desktop calls
blocking service operations through Qt workers, keeping the GUI responsive.
There is no desktop network listener in the normal application.

```text
PySide6 UI ───┐
             ├── JarvisService ─── HTTP provider adapter ─── Ollama / cloud opt-in
FastAPI ─────┘         │
                      ├── TaskEngine ─── ToolRegistry ─── scoped local actions
                      ├── Store ─── SQLite
                      └── SecretStore ─── current-user Windows DPAPI

Push-to-talk ─── sounddevice ─── offline faster-whisper ─── reviewed chat input
Replies ─── Qt TextToSpeech ─── installed Windows voice / default output device
```

## Phase 2 voice path

The original push-to-talk path remains available. Opt-in hands-free listening adds
`HandsFreeInput`: 16 kHz mono capture, bounded 20 ms frames, WebRTC VAD plus an RMS
floor, endpoint silence, then offline Whisper transcription. The wake baseline
matches the configured phrase in that local transcript; it is not a separate
keyword neural model. A single transcription worker discards stale generations.

`VoiceController` delivers bounded events to the Qt thread and drives the pure
`VoiceSession` state machine: wake listening, activation, command listening,
processing, speaking, follow-up listening, sleeping, muted, idle and error.
Natural commands use `JarvisService` and the existing permission engine. Follow-ups
retain the same session until timeout or a sleep command. Speech normalization
removes markup before Windows playback; a selected Qt output device is supported.

Default playback gates recognition and discards captured frames; mute/pause closes
the physical stream. This half-duplex boundary avoids self-wake but provides no
acoustic echo cancellation. Optional headset-only stop recognition remains
experimental. Saving settings never overrides a user's later mute or pause.

`health.py` reports package/model/backend readiness without capturing audio. Frozen
builds embed version, branch, full Git commit, UTC date and source hashes. Settings
shows that identity, executable path, live voice/device states and the last startup
error. Frontend and backend are the same packaged process.

## Module boundaries

`config.py` validates non-secret settings. `secrets.py` separates credentials.
`providers.py` normalizes text, token usage and errors; requests have a total
deadline, response-size limit and cooperative cancellation. `service.py` owns
bounded chat context, local commands and cloud consent. `tasks.py` owns serialized
execution and one-use approvals. `tools.py` validates arguments and file access.
`storage.py` owns persistence. `voice.py` owns bounded audio capture and local
transcription. `desktop.py` owns views and GUI worker lifecycles.

The optional API uses authenticated endpoints for chat, memories, sessions,
tasks, audit and emergency stop. It has no public docs, wildcard CORS, query-string
credentials, shell endpoint or external binding option.

## Persistence and privacy

SQLite schema version 1 uses structured message, memory, task and audit tables.
The initial migration is explicit `PRAGMA user_version`; newer databases fail
closed. Stdlib SQLite was selected to reduce the first build's dependency and
migration complexity. A future schema change must add a transaction-backed
version migration before opening existing data.

Chat persistence is opt-in. Explicit memories persist independently. Local
memory can inform local Ollama chat as bounded untrusted reference data. Cloud
sessions are isolated by provider/model and receive neither local tool results
nor automatically hydrated local memories/history. Context and responses have
size limits. Task history omits file contents. Retention prunes conversation,
task and audit records at startup; explicit memories remain until deleted.

Deletion removes active SQLite records; secure physical erasure is not promised.
The database is not encrypted. Use Windows disk encryption/account access controls
for personal data, and never save credentials as memories.

## Permission boundary

Only named tools with strict Pydantic arguments exist. Files must be within
user-configured absolute roots. Network shares, junctions, symbolic links,
Windows device paths, alternate streams, credential file types and sensitive
metadata paths are denied. Paths are checked before approval and again before
execution. Approvals expire after ten minutes, cannot be replayed and are
cancelled on restart. Filesystem races are reduced by revalidation, not eliminated;
this is not a hostile multi-user OS sandbox.

Manual mode asks before state changes. Balanced mode permits predefined app and
folder launches; directory creation always asks. Advanced currently retains the
balanced policy until explicit scoped grants are implemented. Emergency stop
cancels chat, prevents new actions and revokes pending approvals. A short action
already executing may finish; it cannot be safely rolled back.

## Design limits

Runtime multi-agent execution, tool calling from model plans, dollar spend
estimation, response streaming, autonomous scheduling and financial actions are
not implemented. Request-count, input/context and output-token limits are real;
they are not a monetary budget. No expensive services are provisioned.
Native Whisper inference cannot be safely killed mid-call; interrupt discards
the result, and graceful shutdown waits for active workers rather than destroying
them. UI Automation and window-level verification are later milestones; a launch
record proves a running process or accepted launcher request, not a visible app.

Provider integration references: [OpenAI text generation](https://developers.openai.com/api/docs/guides/text),
[Ollama chat](https://docs.ollama.com/api/chat), [Gemini text generation](https://ai.google.dev/gemini-api/docs/text-generation),
[faster-whisper](https://github.com/SYSTRAN/faster-whisper),
[Qt speech](https://doc.qt.io/qt-6/qtexttospeech.html).


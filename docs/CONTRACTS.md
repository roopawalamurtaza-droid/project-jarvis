# Phase 1 integration contracts

These original interfaces are retained below as historical context. Phase 2 adds
`HandsFreeInput` events to `VoiceController` and the pure `VoiceSession` state
machine. See ARCHITECTURE.md and PROJECT_HANDOFF.md for the current implementation.
`VoiceInput.prepare()` primes the offline model; `SpeechOutput.speak()` reports
acceptance and emits one completion callback per utterance, stop or error.
Natural human commands route through the existing task permission boundary;
the predefined app list now also includes Chrome. Hands-free and spoken replies
are separate explicit opt-ins, with microphone capture closed on mute/pause.

Python 3.12+, src layout. Desktop uses the service directly on worker threads;
optional FastAPI reuses that service, listens on 127.0.0.1 and requires a bearer token.
No shell tool, no cloud fallback, no implicit uploads. UI strings are plain text.

## Owned modules

Lead: config.py, secrets.py, storage.py, tools.py, tasks.py, __main__.py,
project manifests/scripts/docs and core tests.
Backend agent: providers.py, service.py, api.py and tests/test_providers.py,
tests/test_api.py, tests/test_service.py.
UI agent: desktop.py, tests/test_desktop.py.
Voice agent: voice.py, tests/test_voice.py.

## Shared interfaces (lead will implement)

`Settings` (jarvis.config, Pydantic model): data_dir: Path, provider: str
(ollama/openai/gemini), model: str, ollama_url: str, cloud_allowed: bool,
save_history: bool, mode: str (manual/balanced/advanced), allowed_roots: list[Path],
request_timeout: float, max_output_tokens: int, max_requests_per_session: int,
speech_enabled: bool, microphone_device: int | None, speech_model: str,
speech_device: str, speech_compute_type: str. Defaults: local Ollama, no cloud,
no saved conversation until opted in, CPU transcription, speech model downloaded
only by explicit user setup. `load_settings(data_dir=None)` / `save_settings(settings)`.

`SecretStore(data_dir)` (jarvis.secrets): `get(name)->str|None`, `set(name,value)`,
`delete(name)`. Windows DPAPI only for persistence; environment OPENAI_API_KEY,
GEMINI_API_KEY/JARVIS_API_TOKEN may be read as fallback. Never log values.

`Store(data_dir)` (jarvis.storage): `add_message(session_id,role,content)`;
`history(session_id,limit=20)->list[dict]` role/content; `sessions()->list[dict]`;
`delete_session(session_id)`; `memories(query='')->list[dict]`;
`save_memory(category,key,content,source='user')->dict`; `delete_memory(id)`;
`tasks()->list[dict]`; `get_task(id)->dict|None`; `put_task(dict)`;
`audit(event,details:dict)`; `audits(limit=100)->list[dict]`; `export()->dict`;
`close()`. All methods thread-safe; per-call database connections.

`TaskEngine(settings,store)` (jarvis.tasks): `submit(tool:str,arguments:dict)->dict`,
`approve(task_id)->dict`, `reject(task_id)->dict`, `cancel(task_id)->dict`,
`emergency_stop()->None`, `reset_stop()->None`. dict includes id/tool/arguments/
state/result/error. States queued, awaiting_approval, running, verifying,
completed, failed, cancelled. read-only tools execute immediately; state changes
always require approval in manual mode; create_directory always requires approval;
open_app/open_folder predefined low risk in balanced; advanced same conservative
policy until scoped grants exist. File read results never sent to cloud implicitly.

Tools: `list_directory {path}`, `read_file {path}`, `open_folder {path}`,
`open_app {app}` app=notepad/calculator/vscode, `create_directory {path}`.
Paths must resolve inside allowed roots. `tool_schemas()->list[dict]` from tools.py.
Tools return dict with verified boolean; launched PID is evidence of launch only.

## Backend interface (backend agent will implement)

`JarvisService(settings,store,engine,secret_store=None,provider=None)`;
`chat(message,session_id=None,cancel=None)->dict` includes text, session_id,
provider, model, usage, task_id optional. Session context in memory when persistence
disabled. `/tool NAME JSON` submits exact arguments through engine; model text is
never an execution record. `/remember CATEGORY KEY CONTENT` may be handled locally
or memories edited through UI. `provider` injection supports tests.

`create_app(service,token:str)` FastAPI factory. authenticated endpoints for chat,
memory CRUD, task submit/approve/reject/cancel, audit and emergency stop. Token
must be nonempty; no wildcard CORS; endpoints use threadpool for blocking work.

## Voice interface (voice agent will implement)

`VoiceInput(settings)`: `devices()->list[dict]` id/name; `start(device=None)`;
`stop()->numpy.ndarray`; `cancel()`; `transcribe(audio)->str`. Push-to-talk only,
bounded 30-second buffer. Lazy imports/Whisper model, local_files_only=True.
`SpeechOutput(parent=None)` Qt implementation: `speak(text)`, `stop()`,
`voices()->list[str]`, `set_voice(name)`; settings can disable output.

## Desktop interface (UI agent will implement)

`MainWindow(service,settings,store,engine)` and `run_desktop(service,settings,store,engine)`.
PySide6 chat, memory, tasks/approval, settings, microphone, interrupt, emergency stop,
tray and compact floating mode. Backend requests/transcription on workers. No blocking
calls on UI thread. Settings persistent via save_settings; keys via SecretStore.
Graceful exit waits for active workers with bounded provider timeout. Offscreen smoke
test must not record microphone or make external network calls.

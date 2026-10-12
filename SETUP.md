# Windows setup and usage

## Requirements

Windows 11, Python 3.12 or 3.13, Git and [uv](https://docs.astral.sh/uv/getting-started/installation/).
Ordinary user privileges suffice. No administrator components, services or startup
tasks are installed. Qt/PySide6 licensing is documented in THIRD_PARTY.md.

```powershell
cd C:\Jarvis
.\scripts\setup.ps1
```

Setup creates `.venv` with dependencies pinned in `uv.lock`. If Python 3.12+ is
missing, uv can download a compatible runtime; alternatively provide an installed
Python path to `uv venv --python PATH .venv`. Existing environments are not reused
outside this project. The normal data directory is `%LOCALAPPDATA%\ProjectJarvis`;
the verified development configuration is `C:\Jarvis\.local`.

## Local model

Install [Ollama for Windows](https://docs.ollama.com/windows) if absent. Start Ollama,
inspect `ollama list`, and choose an installed model in JARVIS Settings. The test
computer already had `qwen3:8b`; no chat model was downloaded for this build.
If you explicitly want that model on another computer, run `ollama pull qwen3:8b`.
Check the model's own licensing and size before downloading. The larger installed
27B model is not the default for this 12 GB GPU configuration.

```powershell
.\.venv\Scripts\python.exe -m jarvis --data-dir 'C:\Jarvis\.local' --model 'qwen3:8b' --chat 'Hello Jarvis'
.\scripts\start.ps1 -DataDir 'C:\Jarvis\.local'
```

## Offline voice

Install the voice extra during setup, then explicitly download the speech model:

```powershell
.\.venv\Scripts\python.exe -m jarvis --data-dir 'C:\Jarvis\.local' --download-speech-model
```

The default `base.en` speech model runs on CPU/int8. The first transcription loads
the model. Ordinary transcription uses only complete local model files and makes
no model download or audio upload. CUDA is optional and requires compatible
CTranslate2/CUDA/cuDNN libraries; CPU is the tested fallback. Changing the speech
model requires explicitly installing that model too.

In Settings click **Refresh audio devices**, select a microphone and an installed
Windows voice, then **Save settings**. Speech uses the Windows default output;
the **Windows sound settings** button lets you configure headphones/speakers.
Enable **Speak replies**. Hold the microphone button for up to 30 seconds, release,
review the transcription and send it. **Interrupt** stops playback/capture or
cancels a pending AI response. Captured samples are never saved automatically.

## Cloud providers and keys

OpenAI/Gemini are optional and may incur charges. Select the provider and exact
model offered by your account, enter its key in the password-masked Settings
field, and explicitly enable cloud chat. Save to encrypt the key with current-user
Windows DPAPI. Keys are never added to settings, logs or model prompts. A blank
key field preserves the stored key; use the remove-key control to revoke it.
Environment variables are optional alternatives; `.env.example` is documentation
and is not auto-loaded. Do not paste keys into chat or save them as memories.

Request and output-token limits are configurable. There is no hard currency
spending cap in this version; use provider account spending controls. Automatic
cloud fallback is disabled. Switching provider does not upload previous local
chat, stored memory or local tool output.

## Safe actions and memory

Allowed roots begin with the data directory's `workspace` folder. Create it yourself
or configure an existing folder explicitly in Settings. One absolute folder per
line grants that subtree; remove a root to revoke future access. Grant narrow
project folders. App actions are limited to Notepad, Calculator and standard
VS Code installation paths. VS Code project-opening arguments are a future feature.

The Activity form shows exact tool/path before submission. Read and list actions
stay local. Directory creation produces a pending task; select it, review its
arguments, and approve or reject. Emergency stop revokes pending approvals.
Resume does not restore an old approval; resubmit the objective.

Explicit memories can be added/searched/edited/deleted in Memory. Reusing a category
and key updates the existing record. Enable local conversation history only if you
want it retained; Audit provides prior session viewing/deletion. Export contains
personal memory/chat data, so choose its destination carefully.

## Optional HTTP API

```powershell
.\.venv\Scripts\python.exe -m jarvis --data-dir 'C:\Jarvis\.local' --serve --port 8765
```

Only loopback binding is supported. A secure bearer token is generated and stored
through DPAPI, unless `JARVIS_API_TOKEN` is configured. It is not printed. Authorized
local clients can obtain it via `SecretStore(data_dir).get('api_token')` in their own
process; do not put it in shell history. Every route requires `Authorization: Bearer TOKEN`.
The API can approve tasks, so the token is a desktop-control credential.

## Packaging and uninstallation

```powershell
.\scripts\package.ps1
```

Distribute the entire `dist\JARVIS` directory, not just the executable. Speech and
chat models remain separate user data; packaged applications do not silently
download them. Fresh machines still need an Ollama server/model or configured
cloud provider, plus Windows voices and microphone permission.

To uninstall, quit JARVIS and remove its application folder. To delete its user
data, remove the exact data directory you selected after backing up wanted memories.
No registry/startup entry or privileged service needs removing. Ollama and shared
Python/uv installations belong to the user and are not uninstalled with JARVIS.

## Troubleshooting

- Empty model: select a model listed by Ollama or supported by your cloud account.
- Provider unavailable: start Ollama, check its port, or check cloud consent/key/account.
- Transcription unavailable: explicitly install the speech model and select a working mic.
- Windows mic denied: allow desktop app microphone access in Windows privacy settings.
- Read denied: review roots, protected names, links, size and UTF-8 encoding.
- UI busy: interrupt and wait for cancellation; native transcription may finish first.
- Database error: quit, back up the data directory, and inspect the error before recovery.
  Do not overwrite/delete the database as a routine fix.


$ErrorActionPreference = 'Stop'
$jarvisRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $jarvisRoot
$jarvisSavedPath = $env:PATH
try {
    & '.\.venv\Scripts\python.exe' scripts/write_build_info.py
    if ($LASTEXITCODE -ne 0) { throw 'Build identification failed.' }
    # Keep unrelated DLLs from other installed tools out of dependency resolution.
    $env:PATH = "$jarvisRoot\.venv\Scripts;$env:SystemRoot\System32;$env:SystemRoot"
    & '.\.venv\Scripts\python.exe' -m PyInstaller --clean --noconfirm --onedir --windowed --name JARVIS --paths src --add-data "build/build_info.json;jarvis" --add-data "scripts/verify_voice_desktop.py;jarvis" --add-data "scripts/verify_handsfree.py;jarvis" --hidden-import jarvis.desktop --hidden-import jarvis.voice --hidden-import PySide6.QtTextToSpeech --hidden-import PySide6.QtMultimedia --hidden-import faster_whisper --hidden-import sounddevice --hidden-import webrtcvad --hidden-import _webrtcvad --collect-all tzdata --collect-all faster_whisper --collect-all ctranslate2 --collect-all _sounddevice_data --exclude-module PySide6.QtWebEngineCore --exclude-module PySide6.QtWebEngineWidgets --exclude-module PySide6.QtWebEngineQuick scripts/desktop_entry.py
    if ($LASTEXITCODE -ne 0) { throw 'Packaging failed.' }
} finally { $env:PATH = $jarvisSavedPath }
Write-Host 'Built dist\JARVIS\JARVIS.exe. Keep the whole JARVIS folder together.'



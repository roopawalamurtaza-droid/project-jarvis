$ErrorActionPreference = 'Stop'
$jarvisRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $jarvisRoot
$jarvisSavedPath = $env:PATH
try {
    & '.\.venv\Scripts\python.exe' scripts/write_build_info.py
    if ($LASTEXITCODE -ne 0) { throw 'Build identification failed.' }
    # Keep unrelated DLLs from other installed tools out of dependency resolution.
    $env:PATH = "$jarvisRoot\.venv\Scripts;$env:SystemRoot\System32;$env:SystemRoot"
    # Analyze diagnostic imports too: copied runpy scripts alone omit dependencies
    # such as stdlib wave from the frozen Python archive.
    & '.\.venv\Scripts\python.exe' -m PyInstaller --clean --noconfirm JARVIS.spec
    if ($LASTEXITCODE -ne 0) { throw 'Packaging failed.' }
} finally { $env:PATH = $jarvisSavedPath }
Write-Host 'Built dist\JARVIS\JARVIS.exe. Keep the whole JARVIS folder together.'




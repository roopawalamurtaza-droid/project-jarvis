param([switch]$Voice = $true)
$ErrorActionPreference = 'Stop'
$jarvisRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $jarvisRoot
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    throw 'Install uv from https://docs.astral.sh/uv/getting-started/installation/ then rerun setup.ps1.'
}
if ($Voice) { uv sync --frozen --extra voice --extra dev --extra package }
else { uv sync --frozen --extra dev --extra package }
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
& '.\.venv\Scripts\python.exe' -m jarvis --doctor
if ($LASTEXITCODE -ne 0) { throw 'Environment check failed.' }
Write-Host 'Ready. Start JARVIS with scripts\start.ps1. Speech models are an explicit setup step.'

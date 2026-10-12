param([string]$DataDir = '', [switch]$Console)
$ErrorActionPreference = 'Stop'
$jarvisRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $jarvisRoot
$jarvisPython = Join-Path $jarvisRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $jarvisPython)) { throw 'Run scripts\setup.ps1 first.' }
$jarvisArguments = @('-m', 'jarvis')
if ($DataDir) { $jarvisArguments += @('--data-dir', $DataDir) }
& $jarvisPython @jarvisArguments
exit $LASTEXITCODE

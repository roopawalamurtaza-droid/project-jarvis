@echo off
if not exist "%~dp0dist\JARVIS\JARVIS.exe" (
  echo Build JARVIS first with scripts\package.ps1.
  pause
  exit /b 1
)
start "" "%~dp0dist\JARVIS\JARVIS.exe" --data-dir "%~dp0.local"

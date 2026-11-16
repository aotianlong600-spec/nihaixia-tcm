@echo off
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" scripts\run_codex_browser_relay.py
) else (
  python scripts\run_codex_browser_relay.py
)
pause

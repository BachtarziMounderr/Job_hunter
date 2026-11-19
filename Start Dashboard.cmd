@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Prepare the project using docs\dashboard-fr.md first.
  pause
  exit /b 1
)
call npm --prefix frontend run build
if errorlevel 1 (
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m scripts.dashboard
pause

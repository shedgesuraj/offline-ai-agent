@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Virtual environment not found.
  echo Run: py -m venv .venv
  echo Then: .venv\Scripts\python.exe -m pip install -r requirements.txt
  pause
  exit /b 1
)
set "PATH=%LOCALAPPDATA%\Programs\Ollama;%PATH%"
set "OFFLINE_AGENT_SESSION_SECRET=change-this-to-a-long-random-secret"
call .venv\Scripts\python.exe verify_local_ai.py
if errorlevel 1 (
  echo.
  echo Local AI verification failed. Fix Ollama/model first.
  pause
  exit /b 2
)
echo.
echo Starting Offline AI Agent at http://127.0.0.1:8000
call .venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000

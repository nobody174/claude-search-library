@echo off
REM Double-click launcher for Claude Search Library's web server.
REM Starts the Flask server, opens the search UI in your browser, and
REM keeps this window open so you can see logs or Ctrl+C to stop it.

cd /d "%~dp0"

if not exist "venv\Scripts\python.exe" (
    echo Virtual environment not found at venv\Scripts\python.exe
    echo Run: python -m venv venv ^&^& venv\Scripts\pip install -r requirements.txt
    pause
    exit /b 1
)

echo Starting Claude Search Library on http://localhost:7654 ...
start "" http://localhost:7654
venv\Scripts\python.exe server.py --port 7654

pause

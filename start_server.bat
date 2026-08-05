@echo off
REM Double-click launcher for Claude Search Library's web server.
REM Starts the Flask server, opens the search UI in your browser, and
REM keeps this window open so you can see logs. Close this window or
REM press Ctrl+C in it to stop the server.

cd /d "%~dp0"

if not exist "venv\Scripts\python.exe" (
    echo Virtual environment not found at venv\Scripts\python.exe
    echo Run: python -m venv venv ^&^& venv\Scripts\pip install -r requirements.txt
    pause
    exit /b 1
)

REM Server defaults to HTTPS (self-signed cert) so the session cookie
REM doesn't cross the LAN in cleartext when a phone connects over WiFi.
REM Your browser will warn "connection isn't private" the first time -
REM that's expected for a self-signed cert (no public CA signed it, and
REM none is needed for a home-LAN tool). Click Advanced -> Proceed, it
REM won't ask again on that device.
echo Starting Claude Search Library on https://localhost:7654 ...
start "" https://localhost:7654
venv\Scripts\python.exe server.py --port 7654

pause

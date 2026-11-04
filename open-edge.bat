@echo off
rem Open the automation site in Microsoft Edge (starts the server and worker first if they are not running)
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1" -Background
start "" msedge "http://127.0.0.1:8765/"

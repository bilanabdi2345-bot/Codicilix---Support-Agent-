@echo off
rem Starts Second Brain on this computer only. Close this window to stop it.
cd /d "%~dp0"
python -B app.py %*
if errorlevel 1 pause

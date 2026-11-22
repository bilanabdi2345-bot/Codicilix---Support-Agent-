@echo off
rem Starts Codicilix on Windows. It opens in your browser and only talks to this laptop.
rem Close this window to stop it.
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel%==0 (
  py -3 -B -m secondbrain
) else (
  python -B -m secondbrain
)
if errorlevel 1 (
  echo.
  echo Codicilix stopped. If it says Python was not found, install Python 3 from python.org
  echo and tick "Add python.exe to PATH".
  pause
)

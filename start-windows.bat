@echo off
rem Starts Codicilix on Windows. It opens in your browser and only talks to this laptop.
cd /d "%~dp0"
where py >nul 2>nul && (py -3 -m secondbrain) || (python -m secondbrain)
pause

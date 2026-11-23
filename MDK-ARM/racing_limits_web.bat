@echo off
cd /d "%~dp0"
python racing_limits_web.py %*
if errorlevel 1 pause

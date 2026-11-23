@echo off
cd /d "%~dp0"
python wheel_gui.py
if errorlevel 1 pause

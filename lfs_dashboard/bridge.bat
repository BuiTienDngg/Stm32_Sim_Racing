@echo off
setlocal
cd /d "%~dp0"
title LFS to CYD bridge

python -c "import serial" >nul 2>&1
if errorlevel 1 (
    echo Missing pyserial. Install it with:
    echo python -m pip install -r requirements.txt
    pause
    exit /b 1
)

echo Available COM ports:
python -m serial.tools.list_ports
echo.

set "CYD_PORT=%~1"
if not defined CYD_PORT set /p "CYD_PORT=Enter the CYD COM port, for example COM5: "
if not defined CYD_PORT exit /b 1

echo Starting LFS bridge on %CYD_PORT%...
echo Close preview.py or other serial monitors before using this bridge.
python bridge.py --port "%CYD_PORT%"
if errorlevel 1 (
    echo.
    echo Bridge stopped with an error.
    pause
    exit /b 1
)

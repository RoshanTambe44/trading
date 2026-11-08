@echo off
title Groww Trading Terminal
cd /d "%~dp0"

echo ========================================================
echo         GROWW TRADING TERMINAL - PYTHON + FLASK
echo ========================================================
echo.

IF NOT EXIST "venv\Scripts\python.exe" (
    echo [!] Virtual environment not found. Setting up...
    python -m venv venv
    venv\Scripts\pip install -r requirements.txt
)

echo [*] Starting Flask Trading Server...
echo [*] Open your browser at: http://127.0.0.1:5000
echo.
venv\Scripts\python.exe app.py
pause

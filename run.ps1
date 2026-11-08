# Groww Trading Terminal Runner
Set-Location $PSScriptRoot

Write-Host "========================================================" -ForegroundColor Cyan
Write-Host "       GROWW TRADING TERMINAL - PYTHON + FLASK          " -ForegroundColor Green
Write-Host "========================================================" -ForegroundColor Cyan
Write-Host ""

if (-not (Test-Path "venv\Scripts\python.exe")) {
    Write-Host "[!] Virtual environment not found. Setting up..." -ForegroundColor Yellow
    python -m venv venv
    & "venv\Scripts\pip.exe" install -r requirements.txt
}

Write-Host "[*] Starting Flask Web Server..." -ForegroundColor Green
Write-Host "[*] Open your browser at: http://127.0.0.1:5000" -ForegroundColor Cyan
Write-Host ""

& "venv\Scripts\python.exe" app.py

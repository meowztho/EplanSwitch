@echo off
setlocal
cd /d "%~dp0"

if exist ".venv\Scripts\pythonw.exe" (
    start "" ".venv\Scripts\pythonw.exe" "power_plan_switcher.py"
) else (
    where py >nul 2>nul
    if errorlevel 1 (
        echo Python wurde nicht gefunden. Fuehre zuerst build.bat aus.
        pause
        exit /b 1
    )
    start "" pyw -3 "power_plan_switcher.py"
)

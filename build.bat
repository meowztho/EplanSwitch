@echo off
setlocal EnableExtensions
cd /d "%~dp0"

echo ============================================================
echo  Energieplan-Umschalter v1.3.0 - EXE Build
echo ============================================================

echo.
where py >nul 2>nul
if errorlevel 1 (
    echo FEHLER: Der Python Launcher "py" wurde nicht gefunden.
    echo Installiere Python fuer Windows und aktiviere den Python Launcher.
    pause
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo [1/5] Virtuelle Umgebung wird erstellt...
    py -3 -m venv .venv
    if errorlevel 1 goto :error
) else (
    echo [1/5] Virtuelle Umgebung ist bereits vorhanden.
)

echo [2/5] pip wird aktualisiert...
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto :error

echo [3/5] Abhaengigkeiten werden installiert...
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto :error

set "ICON_ARG="
if exist "logo.ico" (
    set "ICON_ARG=--icon=logo.ico"
    echo Icon: logo.ico
) else if exist "logo.png" (
    set "ICON_ARG=--icon=logo.png"
    echo Icon: logo.png ^(wird von PyInstaller mit Pillow umgewandelt^)
) else (
    echo Kein logo.ico oder logo.png gefunden. Es wird das Standard-EXE-Icon verwendet.
)

echo [4/5] Alte Build-Dateien werden entfernt...
if exist "build" rmdir /s /q "build"
if exist "dist" rmdir /s /q "dist"
if exist "Energieplan-Umschalter.spec" del /q "Energieplan-Umschalter.spec"

echo [5/5] EXE wird gebaut...
".venv\Scripts\python.exe" -m PyInstaller ^
    --noconfirm ^
    --clean ^
    --onefile ^
    --windowed ^
    --name "Energieplan-Umschalter" ^
    %ICON_ARG% ^
    "power_plan_switcher.py"
if errorlevel 1 goto :error

copy /y "config.json" "dist\config.json" >nul
if exist "logo.ico" copy /y "logo.ico" "dist\logo.ico" >nul
if exist "logo.png" copy /y "logo.png" "dist\logo.png" >nul
if exist "README.md" copy /y "README.md" "dist\README.md" >nul
if exist "VERSION.txt" copy /y "VERSION.txt" "dist\VERSION.txt" >nul

echo.
echo ============================================================
echo  FERTIG
echo  EXE: %CD%\dist\Energieplan-Umschalter.exe
echo  config.json bleibt neben der EXE frei editierbar.
echo ============================================================
start "" "%CD%\dist"
pause
exit /b 0

:error
echo.
echo ============================================================
echo  BUILD FEHLGESCHLAGEN
 echo  Pruefe die Fehlermeldung oberhalb.
echo ============================================================
pause
exit /b 1

@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"

set "EDITION=%~1"
if not defined EDITION set "EDITION=user"
if /I not "%EDITION%"=="user" if /I not "%EDITION%"=="maintainer" (
    echo [ERROR] Edition must be user or maintainer.
    pause
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] Build environment not found. Run setup_env.bat first.
    pause
    exit /b 1
)

".venv\Scripts\python.exe" -m pip install -r requirements-build.txt
if errorlevel 1 (
    echo [ERROR] Failed to install PyInstaller.
    pause
    exit /b 1
)

".venv\Scripts\python.exe" -B scripts\build_exe_release.py --edition "%EDITION%"
if errorlevel 1 (
    echo [ERROR] EXE build failed.
    pause
    exit /b 1
)

echo Build complete: %EDITION% edition. See the dist folder.
pause
endlocal

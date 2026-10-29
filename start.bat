@echo off
setlocal
set "RAGGG_PORTABLE_ROOT=%~dp0"
set "PYTHONPATH=%RAGGG_PORTABLE_ROOT%src"
set "PYTHONUTF8=1"
cd /d "%RAGGG_PORTABLE_ROOT%"
set "PYTHONW="

if exist "%RAGGG_PORTABLE_ROOT%runtime\python\pythonw.exe" (
    set "PYTHONW=%RAGGG_PORTABLE_ROOT%runtime\python\pythonw.exe"
)

if not defined PYTHONW if exist "%RAGGG_PORTABLE_ROOT%.venv\Scripts\pythonw.exe" (
    set "PYTHONW=%RAGGG_PORTABLE_ROOT%.venv\Scripts\pythonw.exe"
)

if defined PYTHONW (
    "%PYTHONW%" "%RAGGG_PORTABLE_ROOT%app\desktop_app.py"
) else (
    echo Local environment is not ready.
    echo Please double-click setup_env.bat first, then run start.bat again.
    pause
    exit /b 1
)
endlocal

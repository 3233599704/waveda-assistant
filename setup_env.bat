@echo off
setlocal EnableExtensions
chcp 65001 >nul

set "RAGGG_PORTABLE_ROOT=%~dp0"
set "PYTHONPATH=%RAGGG_PORTABLE_ROOT%src"
set "PYTHONUTF8=1"
set "TMP=%RAGGG_PORTABLE_ROOT%.tmp"
set "TEMP=%RAGGG_PORTABLE_ROOT%.tmp"

cd /d "%RAGGG_PORTABLE_ROOT%"
if not exist ".tmp" mkdir ".tmp"

echo.
echo [1/5] Checking Python runtime...
if exist "runtime\python\python.exe" (
    echo Using bundled portable Python runtime.
    set "PYTHON=%RAGGG_PORTABLE_ROOT%runtime\python\python.exe"
    set "USING_BUNDLED_PYTHON=1"
) else (
    where py >nul 2>nul
    if errorlevel 1 (
        echo ============================================
        echo   Python not found.
        echo.
        echo   Please install Python 3.11 or newer:
        echo   https://www.python.org/downloads/
        echo.
        echo   IMPORTANT: Check "Add Python to PATH"
        echo   during installation, then re-run setup_env.bat
        echo ============================================
        start https://www.python.org/downloads/
        pause
        exit /b 1
    )

    echo.
    echo [2/5] Creating local virtual environment...
    if not exist ".venv\Scripts\python.exe" (
        py -m venv .venv
        if errorlevel 1 (
            echo [ERROR] Failed to create .venv.
            pause
            exit /b 1
        )
    ) else (
        echo .venv already exists, skipping creation.
    )

    set "PYTHON=%RAGGG_PORTABLE_ROOT%.venv\Scripts\python.exe"
)

if defined USING_BUNDLED_PYTHON (
    echo.
    echo [2/5] Skipping virtual environment creation.
    echo.
    echo [3/5] Checking bundled Python dependencies...

    rem pypdf (PDF)
    "%PYTHON%" -B scripts\install_pdf_dependency.py
    if errorlevel 1 (
        echo [WARN] Failed to install optional PDF dependency pypdf.
    )

    rem python-pptx (PPT)
    "%PYTHON%" -c "import pptx" 2>nul
    if errorlevel 1 (
        echo Installing python-pptx for bundled Python...
        "%PYTHON%" -m pip install python-pptx --quiet
        if errorlevel 1 (
            echo [WARN] Failed to install python-pptx. PPT import will be unavailable.
        )
    )

    rem python-docx (Word)
    "%PYTHON%" -c "import docx" 2>nul
    if errorlevel 1 (
        echo Installing python-docx for bundled Python...
        "%PYTHON%" -m pip install python-docx --quiet
        if errorlevel 1 (
            echo [WARN] Failed to install python-docx. DOCX import will be unavailable.
        )
    )
) else (
    echo.
    echo [3/5] Installing Python dependencies...
    "%PYTHON%" -m ensurepip --upgrade --default-pip
    if errorlevel 1 (
        echo [ERROR] Failed to initialize pip.
        pause
        exit /b 1
    )

    "%PYTHON%" -m pip install -r requirements.txt
    if errorlevel 1 (
        echo Default pip source failed. Trying Tsinghua PyPI mirror...
        "%PYTHON%" -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
        if errorlevel 1 (
            echo [ERROR] Failed to install dependencies.
            pause
            exit /b 1
        )
    )
)

echo.
echo [4/5] Building local knowledge index...
"%PYTHON%" -B scripts\build_knowledge_base.py
if errorlevel 1 (
    echo [ERROR] Failed to build knowledge index.
    echo Please check whether the project files are complete, then run setup_env.bat again.
    pause
    exit /b 1
)

echo.
echo [5/5] Running smoke test...
"%PYTHON%" -B scripts\smoke_test.py
if errorlevel 1 (
    echo [ERROR] Smoke test failed. Please check the message above.
    pause
    exit /b 1
)

echo.
echo Setup complete.
echo You can now double-click start.bat to launch WavEDA Knowledge Workbench.
pause
endlocal

@echo off
REM ============================================================
REM  R6AX:/Learn install script (Windows)
REM
REM  What it does:
REM    1. Check Python 3.11+
REM    2. Create virtual environment .venv
REM    3. Install dependencies (including dev extras)
REM    4. Generate .env from .env.example (if missing)
REM    5. Initialize the database (creates data\r6ax.db)
REM    6. Compile i18n translation files
REM
REM  Usage:
REM    install.bat
REM
REM  After install, start the dev server manually:
REM    .venv\Scripts\activate
REM    uvicorn app.main:app --reload --port 8000
REM    Open http://localhost:8000
REM ============================================================

setlocal enabledelayedexpansion

set "REQUIRED_MAJOR=3"
set "REQUIRED_MINOR=11"

REM ---------- 1. Check Python version ----------
echo [install] Checking Python version (^>= %REQUIRED_MAJOR%.%REQUIRED_MINOR% required) ...
where python >nul 2>nul
if errorlevel 1 (
    echo [error] python not found. Install Python %REQUIRED_MAJOR%.%REQUIRED_MINOR%+ and add it to PATH, then retry.
    exit /b 1
)

for /f "delims=" %%v in ('python -c "import sys;print(sys.version_info[0])"') do set "PY_MAJOR=%%v"
for /f "delims=" %%v in ('python -c "import sys;print(sys.version_info[1])"') do set "PY_MINOR=%%v"
if not defined PY_MAJOR (
    echo [error] Could not detect the Python version. Is Python installed and on PATH?
    exit /b 1
)
echo [install] Detected Python %PY_MAJOR%.%PY_MINOR%

if %PY_MAJOR% LSS %REQUIRED_MAJOR% (
    echo [error] Python too old: %PY_MAJOR%.%PY_MINOR%, %REQUIRED_MAJOR%.%REQUIRED_MINOR%+ required
    exit /b 1
)
if %PY_MAJOR% EQU %REQUIRED_MAJOR% if %PY_MINOR% LSS %REQUIRED_MINOR% (
    echo [error] Python too old: %PY_MAJOR%.%PY_MINOR%, %REQUIRED_MAJOR%.%REQUIRED_MINOR%+ required
    exit /b 1
)

REM ---------- 2. Create virtual environment ----------
if not exist ".venv" (
    echo [install] Creating virtual environment .venv ...
    python -m venv .venv
    if errorlevel 1 (
        echo [error] Failed to create the virtual environment
        exit /b 1
    )
) else (
    echo [install] Virtual environment already exists, skipping creation.
)

call ".venv\Scripts\activate.bat"
if errorlevel 1 (
    echo [error] Failed to activate the virtual environment
    exit /b 1
)

echo [install] Upgrading pip / setuptools / wheel ...
python -m pip install --upgrade pip setuptools wheel
if errorlevel 1 (
    echo [error] Failed to upgrade pip
    exit /b 1
)

REM ---------- 3. Install dependencies ----------
echo [install] Installing project dependencies (including dev extras) ...
python -m pip install -e ".[dev]"
if errorlevel 1 (
    echo [error] Failed to install dependencies
    exit /b 1
)

REM ---------- 4. Generate .env ----------
if not exist ".env" (
    if exist ".env.example" (
        copy ".env.example" ".env" >nul
        echo [warn] Generated .env from .env.example
        echo [warn] Please edit .env and set DEEPSEEK_API_KEY ^(JWT_SECRET is handled by DB init below^)
    ) else (
        echo [warn] .env.example not found, skipping .env generation
    )
) else (
    echo [install] .env already exists, skipping generation
)

REM ---------- 5. Initialize database ----------
echo [install] Initializing database (data\r6ax.db) ...
python scripts\init_db.py
if errorlevel 1 (
    echo [warn] Database initialization failed
    echo [warn] Ensure .env has a valid JWT_SECRET ^(^>=32 random chars^), then run: python scripts\init_db.py
) else (
    echo [install] Database initialized: data\r6ax.db
)

REM ---------- 6. Compile i18n translation files ----------
python -c "import babel" >nul 2>nul
if not errorlevel 1 (
    echo [install] Compiling i18n translation files ...
    pybabel compile -d app\i18n\locales 2>nul
    if errorlevel 1 python -m babel.messages.frontend compile -d app\i18n\locales 2>nul
    if errorlevel 1 python scripts\compile_i18n.py 2>nul
    if errorlevel 1 echo [warn] i18n compilation skipped (run python scripts\compile_i18n.py later)
) else (
    echo [warn] babel not installed, skipping i18n compilation (run python scripts\compile_i18n.py later)
)

REM ---------- Done ----------
echo.
echo ============================================================
echo  Installation complete!
echo.
echo  Create a user account (required before first login):
echo    python scripts\admin.py create_user ^<username^> ^<password^>
echo.
echo  Start the dev server:
echo    .venv\Scripts\activate
echo    uvicorn app.main:app --reload --port 8000
echo.
echo  Open http://localhost:8000
echo ============================================================
echo.

exit /b 0

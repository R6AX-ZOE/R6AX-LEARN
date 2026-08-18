@echo off
REM ============================================================
REM  R6AX:/Learn bootstrap script (Windows)
REM
REM  Difference from install.bat: install.bat only sets up the
REM  environment; bootstrap.bat checks the environment, prepares
REM  the config and starts the server directly. It automatically
REM  runs install.bat if the setup is missing.
REM
REM  Usage:
REM    bootstrap.bat                     default port 8000 (or PORT from .env)
REM    set PORT=9000 ^&^& bootstrap.bat  explicit port
REM
REM  Stop: Ctrl + C
REM ============================================================

setlocal enabledelayedexpansion

cd /d "%~dp0"

set "VENV_DIR=.venv"
if not defined HOST set "HOST=0.0.0.0"

REM ---------- 1. Check .env ----------
if not exist ".env" (
    if exist ".env.example" (
        copy ".env.example" ".env" >nul
        echo [bootstrap] No .env found; generated one from .env.example
        echo [warn] Edit .env to set DEEPSEEK_API_KEY and JWT_SECRET, then run again
        exit /b 1
    ) else (
        echo [error] Neither .env nor .env.example found; configure your environment first
        exit /b 1
    )
) else (
    echo [bootstrap] .env found
)

REM ---------- 2. Check virtual environment (install if missing/broken) ----------
if not exist "%VENV_DIR%\Scripts\activate.bat" (
    echo [warn] Virtual environment %VENV_DIR% not found; running install.bat first ...
    call install.bat
    if errorlevel 1 (
        echo [error] Environment setup failed
        exit /b 1
    )
)

call "%VENV_DIR%\Scripts\activate.bat"
if errorlevel 1 (
    echo [error] Failed to activate the virtual environment
    exit /b 1
)

python -c "import uvicorn, fastapi" >nul 2>nul
if errorlevel 1 (
    echo [warn] Dependencies missing in %VENV_DIR%; running install.bat first ...
    call install.bat
    if errorlevel 1 (
        echo [error] Environment setup failed
        exit /b 1
    )
)

REM ---------- 3. Compile i18n (best effort) ----------
python -c "import babel" >nul 2>nul
if not errorlevel 1 (
    pybabel compile -d app\i18n\locales >nul 2>nul
    if errorlevel 1 python -m babel.messages.frontend compile -d app\i18n\locales >nul 2>nul
    if errorlevel 1 python scripts\compile_i18n.py >nul 2>nul
    if errorlevel 1 echo [warn] i18n compilation skipped (run python scripts\compile_i18n.py later)
)

REM ---------- 4. Initialize database (best effort) ----------
python scripts\init_db.py
if errorlevel 1 (
    echo [warn] Database init failed; server will retry at startup
)

REM ---------- 5. Resolve port (env var first, then .env, default 8000) ----------
if not defined PORT (
    if exist ".env" (
        for /f "usebackq tokens=1,* delims==" %%a in (".env") do (
            if /i "%%a"=="PORT" (
                set "PORT=%%b"
                goto :port_found
            )
        )
    )
)
:port_found
for /f "tokens=1 delims=#" %%c in ("!PORT!") do set "PORT=%%c"
for /l %%i in (1,1,20) do if "!PORT:~-1!"==" " set "PORT=!PORT:~0,-1!"
if not defined PORT set "PORT=8000"

echo [bootstrap] Starting R6AX:/Learn at http://localhost:%PORT%  (Ctrl + C to stop)
echo.

uvicorn app.main:app --host "%HOST%" --port %PORT% %*
exit /b %errorlevel%

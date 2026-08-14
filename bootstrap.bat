@echo off
REM ============================================================
REM  R6AX:/Learn 启动脚本 (Windows)
REM
REM  与 install.bat 的区别: install.bat 只负责安装环境;
REM  bootstrap.bat 负责"检查环境 -> 准备配置 -> 直接启动服务器"。
REM  若尚未安装依赖, 会自动调用 install.bat。
REM
REM  用法:
REM    bootstrap.bat                     默认端口 8000 (或读取 .env 中的 PORT)
REM    set PORT=9000 && bootstrap.bat    指定端口
REM
REM  停止: Ctrl + C
REM ============================================================

setlocal enabledelayedexpansion

cd /d "%~dp0"

set "VENV_DIR=.venv"
if not defined HOST set "HOST=0.0.0.0"

REM ---------- 1. 检查 .env ----------
if not exist ".env" (
    if exist ".env.example" (
        copy ".env.example" ".env" >nul
        echo [bootstrap] 未找到 .env, 已从 .env.example 生成
        echo [warn] 请编辑 .env, 填入 DEEPSEEK_API_KEY 与 JWT_SECRET, 然后重新运行
        exit /b 1
    ) else (
        echo [error] 未找到 .env 与 .env.example, 请先配置环境变量
        exit /b 1
    )
) else (
    echo [bootstrap] .env 已存在
)

REM ---------- 2. 检查虚拟环境 (缺失则先安装) ----------
if not exist "%VENV_DIR%\Scripts\activate.bat" (
    echo [warn] 未找到虚拟环境 %VENV_DIR%, 先执行安装脚本 ...
    call install.bat
    if errorlevel 1 (
        echo [error] 环境安装失败
        exit /b 1
    )
)

call "%VENV_DIR%\Scripts\activate.bat"
if errorlevel 1 (
    echo [error] 虚拟环境激活失败
    exit /b 1
)

REM ---------- 3. 编译 i18n (尽力而为) ----------
python -c "import babel" >nul 2>nul
if not errorlevel 1 (
    pybabel compile -d app\i18n\locales >nul 2>nul
    if errorlevel 1 python -m babel.messages.frontend compile -d app\i18n\locales >nul 2>nul
    if errorlevel 1 python scripts\compile_i18n.py >nul 2>nul
    if errorlevel 1 echo [warn] i18n 编译跳过 (可稍后运行 python scripts\compile_i18n.py)
)

REM ---------- 4. 确定端口 (环境变量优先, 其次 .env, 默认 8000) ----------
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
if not defined PORT set "PORT=8000"

echo [bootstrap] 启动 R6AX:/Learn 于 http://localhost:%PORT%  (Ctrl + C 停止)
echo.

uvicorn app.main:app --host %HOST% --port %PORT% %*
exit /b %errorlevel%

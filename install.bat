@echo off
REM ============================================================
REM  R6AX:/Learn 安装脚本 (Windows)
REM
REM  功能:
REM    1. 检查 Python 3.11+
REM    2. 创建虚拟环境 .venv
REM    3. 安装依赖 (含 dev 依赖)
REM    4. 从 .env.example 生成 .env (若不存在)
REM    5. 编译 i18n 翻译文件
REM
REM  用法:
REM    install.bat
REM
REM  安装完成后:
REM    .venv\Scripts\activate
REM    uvicorn app.main:app --reload --port 8000
REM    访问 http://localhost:8000 (默认账号 admin / admin)
REM ============================================================

setlocal enabledelayedexpansion

set "REQUIRED_MAJOR=3"
set "REQUIRED_MINOR=11"

REM ---------- 1. 检查 Python 版本 ----------
echo [install] 检查 Python 版本 (需要 >= %REQUIRED_MAJOR%.%REQUIRED_MINOR%) ...
where python >nul 2>nul
if errorlevel 1 (
    echo [error] 未找到 python, 请先安装 Python %REQUIRED_MAJOR%.%REQUIRED_MINOR%+ 并加入 PATH。
    exit /b 1
)

for /f "delims=" %%v in ('python -c "import sys;print(sys.version_info[0])"') do set "PY_MAJOR=%%v"
for /f "delims=" %%v in ('python -c "import sys;print(sys.version_info[1])"') do set "PY_MINOR=%%v"
echo [install] 检测到 Python %PY_MAJOR%.%PY_MINOR%

if %PY_MAJOR% LSS %REQUIRED_MAJOR% (
    echo [error] Python 版本过低: %PY_MAJOR%.%PY_MINOR%, 需要 %REQUIRED_MAJOR%.%REQUIRED_MINOR%+
    exit /b 1
)
if %PY_MAJOR% EQU %REQUIRED_MAJOR% if %PY_MINOR% LSS %REQUIRED_MINOR% (
    echo [error] Python 版本过低: %PY_MAJOR%.%PY_MINOR%, 需要 %REQUIRED_MAJOR%.%REQUIRED_MINOR%+
    exit /b 1
)

REM ---------- 2. 创建虚拟环境 ----------
if not exist ".venv" (
    echo [install] 创建虚拟环境 .venv ...
    python -m venv .venv
    if errorlevel 1 (
        echo [error] 虚拟环境创建失败
        exit /b 1
    )
) else (
    echo [install] 虚拟环境已存在, 跳过创建。
)

call ".venv\Scripts\activate.bat"
if errorlevel 1 (
    echo [error] 虚拟环境激活失败
    exit /b 1
)

echo [install] 升级 pip / setuptools / wheel ...
python -m pip install --upgrade pip setuptools wheel
if errorlevel 1 (
    echo [error] pip 升级失败
    exit /b 1
)

REM ---------- 3. 安装依赖 ----------
echo [install] 安装项目依赖 (含 dev 依赖) ...
python -m pip install -e ".[dev]"
if errorlevel 1 (
    echo [error] 依赖安装失败
    exit /b 1
)

REM ---------- 4. 生成 .env ----------
if not exist ".env" (
    if exist ".env.example" (
        copy ".env.example" ".env" >nul
        echo [warn] 已从 .env.example 生成 .env
        echo [warn] 请编辑 .env, 填入 DEEPSEEK_API_KEY 与 JWT_SECRET
    ) else (
        echo [warn] 未找到 .env.example, 跳过 .env 生成
    )
) else (
    echo [install] .env 已存在, 跳过生成
)

REM ---------- 5. 编译 i18n 翻译文件 ----------
python -c "import babel" >nul 2>nul
if not errorlevel 1 (
    echo [install] 编译 i18n 翻译文件 ...
    pybabel compile -d app\i18n\locales 2>nul
    if errorlevel 1 python -m babel.messages.frontend compile -d app\i18n\locales 2>nul
    if errorlevel 1 python compile_i18n.py 2>nul
    if errorlevel 1 echo [warn] i18n 编译跳过 (可稍后运行 python compile_i18n.py)
) else (
    echo [warn] 未安装 babel, 跳过 i18n 编译 (可稍后运行 python compile_i18n.py)
)

REM ---------- 完成 ----------
echo.
echo ============================================================
echo  安装完成!
echo.
echo  启动开发服务器:
echo    .venv\Scripts\activate
echo    uvicorn app.main:app --reload --port 8000
echo.
echo  访问 http://localhost:8000  (默认账号 admin / admin)
echo ============================================================
echo.

exit /b 0
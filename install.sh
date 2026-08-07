#!/usr/bin/env bash
#
# R6AX:/Learn 安装脚本（Linux / macOS）
#
# 功能：
#   1. 检查 Python 3.11+
#   2. 创建虚拟环境 .venv
#   3. 安装依赖（含 dev 依赖）
#   4. 从 .env.example 生成 .env（若不存在）
#   5. 编译 i18n 翻译文件
#
# 用法：
#   bash install.sh        # 或直接执行 ./install.sh
#
# 之后再手动：
#   source .venv/bin/activate
#   uvicorn app.main:app --reload --port 8000

set -euo pipefail

# 颜色输出
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

info()  { echo -e "${GREEN}[install]${NC} $*"; }
warn()  { echo -e "${YELLOW}[warn]${NC} $*"; }
error() { echo -e "${RED}[error]${NC} $*"; exit 1; }

# 脚本所在目录（项目根）
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

PYTHON_BIN="${PYTHON_BIN:-python3}"
REQUIRED_PY=3.11
VENV_DIR=".venv"
ACTIVATE="$VENV_DIR/bin/activate"

# ---------- 1. 检查 Python 版本 ----------
info "检查 Python 版本（需要 >= $REQUIRED_PY）..."
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
    error "未找到 $PYTHON_BIN。请先安装 Python $REQUIRED_PY+，然后重试。"
fi

PY_MAJOR=$("$PYTHON_BIN" -c 'import sys; print(sys.version_info[0])')
PY_MINOR=$("$PYTHON_BIN" -c 'import sys; print(sys.version_info[1])')
if [ "$PY_MAJOR" -lt 3 ] || { [ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 11 ]; }; then
    error "Python 版本过低：当前 $PY_MAJOR.$PY_MINOR，需要 $REQUIRED_PY+"
fi
info "Python 版本 OK：$PY_MAJOR.$PY_MINOR"

# ---------- 2. 创建虚拟环境 ----------
if [ ! -d "$VENV_DIR" ]; then
    info "创建虚拟环境 $VENV_DIR ..."
    "$PYTHON_BIN" -m venv "$VENV_DIR"
else
    info "虚拟环境已存在，跳过创建。"
fi

# shellcheck disable=SC1091
source "$SCRIPT_DIR/$ACTIVATE"

info "升级 pip / setuptools / wheel ..."
pip install --upgrade pip setuptools wheel
[ $? -ne 0 ] && error "pip 升级失败"

# ---------- 3. 安装依赖 ----------
info "安装项目依赖（含 dev 依赖）..."
pip install -e ".[dev]"
[ $? -ne 0 ] && error "依赖安装失败"

# ---------- 4. 生成 .env ----------
if [ ! -f ".env" ]; then
    if [ -f ".env.example" ]; then
        cp .env.example .env
        warn "已从 .env.example 生成 .env"
        warn "请编辑 .env，填入 DEEPSEEK_API_KEY 与 JWT_SECRET"
    else
        warn "未找到 .env.example，跳过 .env 生成"
    fi
else
    info ".env 已存在，跳过生成"
fi

# ---------- 5. 编译 i18n 翻译文件 ----------
if python -c "import babel" >/dev/null 2>&1; then
    info "编译 i18n 翻译文件 ..."
    pybabel compile -d app/i18n/locales 2>/dev/null \
        || python -m babel.messages.frontend compile -d app/i18n/locales 2>/dev/null \
        || python compile_i18n.py 2>/dev/null \
        || warn "i18n 编译跳过（可稍后运行 python compile_i18n.py）"
else
    warn "未安装 babel，跳过 i18n 编译（可稍后运行 python compile_i18n.py）"
fi

# ---------- 完成 ----------
info "=============================="
info " 安装完成！"
info ""
info " 启动开发服务器："
info "   source $ACTIVATE"
info "   uvicorn app.main:app --reload --port 8000"
info ""
info " 访问 http://localhost:8000 （默认账号 admin / admin）"
info "=============================="

exit 0
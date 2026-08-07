#!/usr/bin/env bash
#
# R6AX:/Learn 启动脚本（Linux / macOS）
#
# 与 install.sh 的区别：install.sh 只负责安装环境；
# bootstrap.sh 负责"检查环境 → 准备配置 → 直接启动服务器"。
# 若尚未安装依赖，会自动调用 install.sh。
#
# 用法：
#   ./bootstrap.sh            # 默认端口 8000（或读取 .env 中的 PORT）
#   PORT=9000 ./bootstrap.sh  # 指定端口
#
# 停止：Ctrl + C

set -euo pipefail

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

info()  { echo -e "${GREEN}[bootstrap]${NC} $*"; }
warn()  { echo -e "${YELLOW}[warn]${NC} $*"; }
error() { echo -e "${RED}[error]${NC} $*"; exit 1; }

# 脚本所在目录（项目根）
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

VENV_DIR=".venv"
ACTIVATE="$VENV_DIR/bin/activate"
HOST="${HOST:-0.0.0.0}"

# ---------- 1. 检查 .env ----------
if [ ! -f ".env" ]; then
    if [ -f ".env.example" ]; then
        cp .env.example .env
        warn "未找到 .env，已从 .env.example 生成"
        warn "请编辑 .env，填入 DEEPSEEK_API_KEY 与 JWT_SECRET，然后重新运行"
        exit 1
    else
        error "未找到 .env 与 .env.example，请先配置环境变量"
    fi
else
    info ".env 已存在"
fi

# ---------- 2. 检查虚拟环境（缺失则先安装） ----------
if [ ! -d "$VENV_DIR" ]; then
    warn "未找到虚拟环境 .venv，先执行安装脚本 ..."
    bash install.sh
fi

# shellcheck disable=SC1091
source "$SCRIPT_DIR/$ACTIVATE"

# ---------- 3. 编译 i18n（尽力而为） ----------
if python -c "import babel" >/dev/null 2>&1; then
    pybabel compile -d app/i18n/locales >/dev/null 2>&1 \
        || python -m babel.messages.frontend compile -d app/i18n/locales >/dev/null 2>&1 \
        || true
fi

# ---------- 4. 确定端口 ----------
PORT="${PORT:-}"
if [ -z "$PORT" ]; then
    PORT="$(grep -E '^PORT=' .env 2>/dev/null | head -n1 | cut -d= -f2 | tr -d ' \r')"
fi
PORT="${PORT:-8000}"

info "启动 R6AX:/Learn 于 http://localhost:$PORT （Ctrl + C 停止）"
echo

exec uvicorn app.main:app --host "$HOST" --port "$PORT" "$@"
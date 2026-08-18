#!/usr/bin/env bash
#
# R6AX:/Learn bootstrap script (Linux / macOS)
#
# Difference from install.sh: install.sh only sets up the environment;
# bootstrap.sh checks the environment, prepares the config and starts the
# server directly. It automatically runs install.sh if the setup is missing.
#
# Usage:
#   ./bootstrap.sh            # default port 8000 (or PORT from .env)
#   PORT=9000 ./bootstrap.sh  # explicit port
#
# Stop: Ctrl + C

set -euo pipefail

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

info()  { echo -e "${GREEN}[bootstrap]${NC} $*"; }
warn()  { echo -e "${YELLOW}[warn]${NC} $*"; }
error() { echo -e "${RED}[error]${NC} $*"; exit 1; }

# Directory of this script (project root)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

VENV_DIR=".venv"
ACTIVATE="$VENV_DIR/bin/activate"
HOST="${HOST:-0.0.0.0}"

# ---------- 1. Check .env ----------
if [ ! -f ".env" ]; then
    if [ -f ".env.example" ]; then
        cp .env.example .env
        warn "No .env found; generated one from .env.example"
        warn "Edit .env to set DEEPSEEK_API_KEY and JWT_SECRET, then run again"
        exit 1
    else
        error "Neither .env nor .env.example found; configure your environment first"
    fi
else
    info ".env found"
fi

# ---------- 2. Check virtual environment (install if missing/broken) ----------
if [ ! -d "$VENV_DIR" ]; then
    warn "Virtual environment '$VENV_DIR' not found; running install.sh first ..."
    bash install.sh
elif ! "$VENV_DIR/bin/python" -c "import uvicorn, fastapi" >/dev/null 2>&1; then
    warn "Dependencies missing in '$VENV_DIR'; running install.sh first ..."
    bash install.sh
fi

# shellcheck disable=SC1091
source "$SCRIPT_DIR/$ACTIVATE" || error "Failed to activate the virtual environment"

# ---------- 3. Compile i18n (best effort) ----------
if python -c "import babel" >/dev/null 2>&1; then
    pybabel compile -d app/i18n/locales >/dev/null 2>&1 \
        || python -m babel.messages.frontend compile -d app/i18n/locales >/dev/null 2>&1 \
        || true
fi

# ---------- 4. Initialize database (best effort) ----------
if ! python scripts/init_db.py; then
    warn "Database init failed; server will retry at startup"
fi

# ---------- 5. Resolve port ----------
PORT="${PORT:-}"
if [ -z "$PORT" ]; then
    PORT="$(grep -E '^PORT=' .env 2>/dev/null | head -n1 | cut -d= -f2 | tr -d ' \r"' || true)"
fi
PORT="${PORT:-8000}"

info "Starting R6AX:/Learn at http://localhost:$PORT  (Ctrl + C to stop)"
echo

exec uvicorn app.main:app --host "$HOST" --port "$PORT" "$@"

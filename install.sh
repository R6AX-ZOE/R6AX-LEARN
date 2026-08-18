#!/usr/bin/env bash
#
# R6AX:/Learn install script (Linux / macOS)
#
# What it does:
#   1. Check Python 3.11+
#   2. Create virtual environment .venv
#   3. Install dependencies (including dev extras)
#   4. Generate .env from .env.example (if missing)
#   5. Initialize the database (creates data/r6ax.db)
#   6. Compile i18n translation files
#
# Usage:
#   bash install.sh        # or run ./install.sh directly
#
# After install, start the dev server manually:
#   source .venv/bin/activate
#   uvicorn app.main:app --reload --port 8000

set -euo pipefail

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

info()  { echo -e "${GREEN}[install]${NC} $*"; }
warn()  { echo -e "${YELLOW}[warn]${NC} $*"; }
error() { echo -e "${RED}[error]${NC} $*"; exit 1; }

# Directory of this script (project root)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

PYTHON_BIN="${PYTHON_BIN:-python3}"
REQUIRED_PY=3.11
VENV_DIR=".venv"
ACTIVATE="$VENV_DIR/bin/activate"

# ---------- 1. Check Python version ----------
info "Checking Python version (>= $REQUIRED_PY required) ..."
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
    error "Python '$PYTHON_BIN' not found. Install Python $REQUIRED_PY+ first, then retry."
fi

PY_MAJOR=$("$PYTHON_BIN" -c 'import sys; print(sys.version_info[0])')
PY_MINOR=$("$PYTHON_BIN" -c 'import sys; print(sys.version_info[1])')
if [ "$PY_MAJOR" -lt 3 ] || { [ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 11 ]; }; then
    error "Python too old: $PY_MAJOR.$PY_MINOR, $REQUIRED_PY+ required"
fi
info "Python version OK: $PY_MAJOR.$PY_MINOR"

# ---------- 2. Create virtual environment ----------
if [ ! -d "$VENV_DIR" ]; then
    info "Creating virtual environment $VENV_DIR ..."
    "$PYTHON_BIN" -m venv "$VENV_DIR" || error "Failed to create the virtual environment"
else
    info "Virtual environment already exists, skipping creation."
fi

# shellcheck disable=SC1091
source "$SCRIPT_DIR/$ACTIVATE" || error "Failed to activate the virtual environment"

info "Upgrading pip / setuptools / wheel ..."
python -m pip install --upgrade pip setuptools wheel || error "Failed to upgrade pip"

# ---------- 3. Install dependencies ----------
info "Installing project dependencies (including dev extras) ..."
python -m pip install -e ".[dev]" || error "Failed to install dependencies"

# ---------- 4. Generate .env ----------
if [ ! -f ".env" ]; then
    if [ -f ".env.example" ]; then
        cp .env.example .env
        warn "Generated .env from .env.example"
        warn "Please edit .env and set DEEPSEEK_API_KEY (JWT_SECRET is handled by DB init below)"
    else
        warn ".env.example not found, skipping .env generation"
    fi
else
    info ".env already exists, skipping generation"
fi

# ---------- 5. Initialize database ----------
info "Initializing database (data/r6ax.db) ..."
if python scripts/init_db.py; then
    info "Database initialized: data/r6ax.db"
else
    warn "Database initialization failed"
    warn "Ensure .env has a valid JWT_SECRET (>=32 random chars), then run: python scripts/init_db.py"
fi

# ---------- 6. Compile i18n translation files ----------
if python -c "import babel" >/dev/null 2>&1; then
    info "Compiling i18n translation files ..."
    pybabel compile -d app/i18n/locales 2>/dev/null \
        || python -m babel.messages.frontend compile -d app/i18n/locales 2>/dev/null \
        || python scripts/compile_i18n.py 2>/dev/null \
        || warn "i18n compilation skipped (run python scripts/compile_i18n.py later)"
else
    warn "babel not installed, skipping i18n compilation (run python scripts/compile_i18n.py later)"
fi

# ---------- Done ----------
info "=============================="
info "  Installation complete!"
info ""
info "  Create a user account (required before first login):"
info "   python scripts/admin.py create_user <username> <password>"
info ""
info "  Start the dev server:"
info "   source $ACTIVATE"
info "   uvicorn app.main:app --reload --port 8000"
info ""
info "  Open http://localhost:8000"
info "=============================="

exit 0

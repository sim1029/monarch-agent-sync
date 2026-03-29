#!/usr/bin/env bash
# setup.sh — one-time setup for monarch-agent-sync on macOS
#
# What this does:
#   1. Checks for Python 3.11+
#   2. Creates a virtual environment
#   3. Installs dependencies
#   4. Copies .env.example → .env for you to fill in
#   5. Installs a launchd job to run sync.py daily at 6am
#
# Usage:
#   chmod +x setup.sh
#   ./setup.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$SCRIPT_DIR/.venv"
PLIST_NAME="com.simonschueller.monarch-agent-sync"
PLIST_PATH="$HOME/Library/LaunchAgents/$PLIST_NAME.plist"
LOG_DIR="$HOME/Library/Logs/monarch-agent-sync"

# ── 1. Python check ───────────────────────────────────────────────────────────
echo "Checking Python..."
if ! command -v python3 &>/dev/null; then
  echo "❌ python3 not found. Install from https://www.python.org or via brew install python"
  exit 1
fi

PY_VERSION=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
echo "  Found Python $PY_VERSION"

# ── 2. Virtual environment ────────────────────────────────────────────────────
echo "Setting up virtual environment..."
python3 -m venv "$VENV"
source "$VENV/bin/activate"

# ── 3. Dependencies ───────────────────────────────────────────────────────────
echo "Installing dependencies..."
pip install --quiet --upgrade pip
pip install --quiet -r "$SCRIPT_DIR/requirements.txt"
echo "  ✓ Dependencies installed"

# ── 4. .env file ─────────────────────────────────────────────────────────────
if [[ ! -f "$SCRIPT_DIR/.env" ]]; then
  cp "$SCRIPT_DIR/.env.example" "$SCRIPT_DIR/.env"
  echo "  ✓ Created .env — fill in your credentials before running sync.py"
else
  echo "  .env already exists, skipping"
fi

# ── 5. launchd plist ─────────────────────────────────────────────────────────
echo "Installing launchd job (daily sync at 6:00am)..."
mkdir -p "$LOG_DIR"
mkdir -p "$(dirname "$PLIST_PATH")"

PYTHON_BIN="$VENV/bin/python3"
SYNC_SCRIPT="$SCRIPT_DIR/sync.py"

cat > "$PLIST_PATH" << PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>${PLIST_NAME}</string>

  <key>ProgramArguments</key>
  <array>
    <string>${PYTHON_BIN}</string>
    <string>${SYNC_SCRIPT}</string>
  </array>

  <key>WorkingDirectory</key>
  <string>${SCRIPT_DIR}</string>

  <key>StartCalendarInterval</key>
  <dict>
    <key>Hour</key>
    <integer>6</integer>
    <key>Minute</key>
    <integer>0</integer>
  </dict>

  <key>StandardOutPath</key>
  <string>${LOG_DIR}/sync.log</string>

  <key>StandardErrorPath</key>
  <string>${LOG_DIR}/sync.error.log</string>

  <key>RunAtLoad</key>
  <false/>
</dict>
</plist>
PLIST

launchctl unload "$PLIST_PATH" 2>/dev/null || true
launchctl load "$PLIST_PATH"
echo "  ✓ launchd job installed — runs daily at 6:00am"

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Setup complete!"
echo ""
echo "  Next steps:"
echo "  1. Edit .env with your Monarch and Supabase credentials:"
echo "       open '$SCRIPT_DIR/.env'"
echo ""
echo "  2. Run the Supabase schema migration:"
echo "       — Open your Supabase dashboard → SQL Editor"
echo "       — Paste the contents of schema.sql and run it"
echo ""
echo "  3. Do a full historical backfill (first run):"
echo "       source .venv/bin/activate"
echo "       python sync.py --start 2023-01-01"
echo ""
echo "  4. After that, daily syncs run automatically at 6am."
echo "     Logs: $LOG_DIR/"
echo ""
echo "  Manual run anytime:"
echo "       source .venv/bin/activate && python sync.py"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

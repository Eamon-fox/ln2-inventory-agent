#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PYTHON_BIN="${PYTHON:-python3}"
MIN_PYTHON_VERSION="3.10"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "ERROR: macOS build must run on Darwin."
  exit 1
fi

cd "$ROOT_DIR"

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "ERROR: Python interpreter not found: $PYTHON_BIN"
  exit 1
fi

PYTHON_VERSION="$("$PYTHON_BIN" -c 'import platform; print(platform.python_version())')"
if ! "$PYTHON_BIN" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)'; then
  echo "ERROR: SnowFox macOS build requires Python ${MIN_PYTHON_VERSION}+."
  echo "Current interpreter: $PYTHON_BIN ($PYTHON_VERSION)"
  echo "Use a newer interpreter, for example:"
  echo "  PYTHON=/path/to/python3.11 bash installer/mac/build_app.sh"
  exit 1
fi

if ! "$PYTHON_BIN" -m PyInstaller --version >/dev/null 2>&1; then
  echo "ERROR: pyinstaller not installed for $PYTHON_BIN"
  echo "Run: $PYTHON_BIN -m pip install pyinstaller"
  exit 1
fi

echo "[1/1] Building macOS app bundle with PyInstaller..."
"$PYTHON_BIN" -m PyInstaller ln2_inventory.mac.spec "$@"

echo "Done. App bundle is under dist/SnowFox.app"

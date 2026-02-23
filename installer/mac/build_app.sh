#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PYTHON_BIN="${PYTHON:-python3}"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "ERROR: macOS build must run on Darwin."
  exit 1
fi

cd "$ROOT_DIR"

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "ERROR: Python interpreter not found: $PYTHON_BIN"
  exit 1
fi

if ! "$PYTHON_BIN" -m pyinstaller --version >/dev/null 2>&1; then
  echo "ERROR: pyinstaller not installed for $PYTHON_BIN"
  echo "Run: $PYTHON_BIN -m pip install pyinstaller"
  exit 1
fi

echo "[1/1] Building macOS app bundle with PyInstaller..."
"$PYTHON_BIN" -m pyinstaller ln2_inventory.mac.spec "$@"

echo "Done. App bundle is under dist/SnowFox.app"

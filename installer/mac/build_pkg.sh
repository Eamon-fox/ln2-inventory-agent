#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PYTHON_BIN="${PYTHON:-python3}"
APP_NAME="SnowFox"
APP_PATH="$ROOT_DIR/dist/${APP_NAME}.app"
PKG_DIR="$ROOT_DIR/dist/installer"
PKG_IDENTIFIER="com.eamonfox.snowfox"
SKIP_APP_BUILD=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --skip-app-build)
      SKIP_APP_BUILD=1
      shift
      ;;
    *)
      echo "ERROR: unknown argument: $1"
      echo "Usage: bash installer/mac/build_pkg.sh [--skip-app-build]"
      exit 1
      ;;
  esac
done

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "ERROR: macOS build must run on Darwin."
  exit 1
fi

cd "$ROOT_DIR"

if ! command -v pkgbuild >/dev/null 2>&1; then
  echo "ERROR: pkgbuild not found. Install Xcode Command Line Tools first."
  exit 1
fi

if [[ "$SKIP_APP_BUILD" -eq 0 ]]; then
  echo "[1/2] Building app bundle..."
  PYTHON="$PYTHON_BIN" bash installer/mac/build_app.sh
fi

if [[ ! -d "$APP_PATH" ]]; then
  echo "ERROR: app bundle not found: $APP_PATH"
  exit 1
fi

APP_VERSION="$(
  /usr/libexec/PlistBuddy -c 'Print :CFBundleShortVersionString' \
    "$APP_PATH/Contents/Info.plist"
)"
PKG_PATH="$PKG_DIR/${APP_NAME}-${APP_VERSION}-macOS.pkg"

mkdir -p "$PKG_DIR"

echo "[2/2] Building installer package..."
pkgbuild \
  --component "$APP_PATH" \
  --install-location /Applications \
  --identifier "$PKG_IDENTIFIER" \
  --version "$APP_VERSION" \
  "$PKG_PATH"

echo "Done. Installer package is under $PKG_PATH"

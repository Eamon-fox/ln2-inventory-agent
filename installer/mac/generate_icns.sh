#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SOURCE_ICON="$ROOT_DIR/app_gui/assets/icon.png"
OUTPUT_ICON="$ROOT_DIR/installer/mac/SnowFox.icns"
ICONSET_DIR="$ROOT_DIR/build/macos/SnowFox.iconset"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "ERROR: .icns generation must run on Darwin."
  exit 1
fi

if [[ ! -f "$SOURCE_ICON" ]]; then
  echo "ERROR: source icon not found: $SOURCE_ICON"
  exit 1
fi

if ! command -v sips >/dev/null 2>&1; then
  echo "ERROR: sips not found."
  exit 1
fi

if ! command -v iconutil >/dev/null 2>&1; then
  echo "ERROR: iconutil not found."
  exit 1
fi

if [[ -f "$OUTPUT_ICON" && "$OUTPUT_ICON" -nt "$SOURCE_ICON" ]]; then
  echo "macOS bundle icon is up to date: $OUTPUT_ICON"
  exit 0
fi

mkdir -p "$(dirname "$OUTPUT_ICON")" "$(dirname "$ICONSET_DIR")"
rm -rf "$ICONSET_DIR"
mkdir -p "$ICONSET_DIR"

render_icon() {
  local size="$1"
  local name="$2"
  sips -z "$size" "$size" "$SOURCE_ICON" --out "$ICONSET_DIR/$name" >/dev/null
}

render_icon 16 "icon_16x16.png"
render_icon 32 "icon_16x16@2x.png"
render_icon 32 "icon_32x32.png"
render_icon 64 "icon_32x32@2x.png"
render_icon 128 "icon_128x128.png"
render_icon 256 "icon_128x128@2x.png"
render_icon 256 "icon_256x256.png"
render_icon 512 "icon_256x256@2x.png"
render_icon 512 "icon_512x512.png"
render_icon 1024 "icon_512x512@2x.png"

iconutil -c icns "$ICONSET_DIR" -o "$OUTPUT_ICON"

rm -rf "$ICONSET_DIR"

echo "Generated macOS bundle icon: $OUTPUT_ICON"

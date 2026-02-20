#!/bin/bash
# Download Lucide icons from CDN
# Usage: ./download_icons.sh icon1 icon2 icon3 ...

set -e

ICONS_DIR="app_gui/assets/icons"
CDN_BASE="https://unpkg.com/lucide-static@latest/icons"

# Check if icons directory exists
if [ ! -d "$ICONS_DIR" ]; then
    echo "Error: Icons directory not found: $ICONS_DIR"
    echo "Please run this script from the project root directory."
    exit 1
fi

# Check if at least one icon name is provided
if [ $# -eq 0 ]; then
    echo "Usage: $0 icon1 icon2 icon3 ..."
    echo "Example: $0 trash edit save"
    exit 1
fi

echo "Downloading icons to $ICONS_DIR..."

# Download each icon
for icon in "$@"; do
    echo "  Downloading $icon.svg..."
    if curl -sL -o "$ICONS_DIR/$icon.svg" "$CDN_BASE/$icon.svg"; then
        # Verify the download
        if grep -q "svg" "$ICONS_DIR/$icon.svg"; then
            echo "  ✓ $icon.svg downloaded successfully"
        else
            echo "  ✗ $icon.svg download failed (invalid content)"
            rm -f "$ICONS_DIR/$icon.svg"
        fi
    else
        echo "  ✗ $icon.svg download failed"
    fi
done

echo ""
echo "Download complete. Icons saved to $ICONS_DIR/"
echo ""
echo "Next steps:"
echo "1. Update Icons class in app_gui/ui/icons.py"
echo "2. Use get_icon(Icons.ICON_NAME) in your code"

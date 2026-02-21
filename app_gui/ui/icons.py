"""Icon management for Lucide icons."""

import os
from PySide6.QtGui import QIcon, QPixmap, QPainter
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtCore import QSize, Qt, QByteArray

# Get the icons directory path
if hasattr(os.sys, "frozen"):
    # PyInstaller frozen app
    ICONS_DIR = os.path.join(os.sys._MEIPASS, "app_gui", "assets", "icons")
else:
    # Development
    ICONS_DIR = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "assets",
        "icons"
    )

# Global icon color (set by theme)
_ICON_COLOR = "#ffffff"  # Default to white for dark theme


def set_icon_color(color: str):
    """Set the global icon color based on theme."""
    global _ICON_COLOR
    _ICON_COLOR = color


def get_icon(name: str, size: int = 24, color: str = None) -> QIcon:
    """
    Load a Lucide icon from SVG file with dynamic color support.

    Args:
        name: Icon name (without .svg extension)
        size: Icon size in pixels (default: 24)
        color: Color for the icon (e.g., "#ffffff"). If None, uses global icon color.

    Returns:
        QIcon object
    """
    svg_path = os.path.join(ICONS_DIR, f"{name}.svg")

    if not os.path.exists(svg_path):
        # Return empty icon if file not found
        return QIcon()

    # Read SVG content
    with open(svg_path, 'r', encoding='utf-8') as f:
        svg_content = f.read()

    # Use global icon color if not specified
    if color is None:
        color = _ICON_COLOR

    # Replace currentColor with the specified color
    svg_content = svg_content.replace('stroke="currentColor"', f'stroke="{color}"')

    # Create QIcon from modified SVG content
    renderer = QSvgRenderer(QByteArray(svg_content.encode('utf-8')))
    pixmap = QPixmap(QSize(size, size))
    pixmap.fill(Qt.transparent)

    painter = QPainter(pixmap)
    renderer.render(painter)
    painter.end()

    return QIcon(pixmap)


# Icon name constants for easy reference
class Icons:
    """Lucide icon name constants."""
    PLUS = "plus"
    SETTINGS = "settings"
    FILE_TEXT = "file-text"
    REFRESH_CW = "refresh-cw"
    GRID_3X3 = "grid-3x3"
    TABLE = "table"
    CHEVRON_DOWN = "chevron-down"
    CHEVRON_UP = "chevron-up"
    X = "x"
    ZOOM_IN = "zoom-in"
    ZOOM_OUT = "zoom-out"
    DOWNLOAD = "download"
    PLAY = "play"
    SQUARE = "square"
    TRASH = "trash"
    FILE_PLUS = "file-plus"
    FOLDER_OPEN = "folder-open"
    ROTATE_CCW = "rotate-ccw"
    MAXIMIZE_2 = "maximize-2"
    MAXIMIZE = "maximize"
    MINIMIZE = "minimize"
    SCAN = "scan"
    FILTER = "filter"

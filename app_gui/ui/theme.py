import os

from PySide6.QtGui import QColor, QFont, QFontDatabase, QPalette
from PySide6.QtCore import Qt

# CJK fallback font paths (checked in order; non-existent entries are skipped)
_CJK_FONT_CANDIDATES = [
    # Windows
    os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts", "msyh.ttc"),
    os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts", "msyhbd.ttc"),
    os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts", "simsun.ttc"),
    # Linux
    "/usr/share/fonts/google-noto-cjk/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/google-droid/DroidSansFallback.ttf",
    "/usr/share/fonts/truetype/droid/DroidSansFallback.ttf",
    "/usr/share/fonts/wqy-microhei/wqy-microhei.ttc",
]


def _setup_cjk_font(app):
    """Load a CJK-capable font and set an application-wide font with fallbacks."""
    loaded_family = None
    for path in _CJK_FONT_CANDIDATES:
        if not os.path.isfile(path):
            continue
        fid = QFontDatabase.addApplicationFont(path)
        if fid < 0:
            continue
        families = QFontDatabase.applicationFontFamilies(fid)
        if families:
            loaded_family = families[0]
            break

    # Build font with CJK fallback chain
    font = QFont("Ubuntu")
    font.setPointSize(10)
    fallbacks = [
        "Cantarell",
        "DejaVu Sans",
    ]
    if loaded_family:
        fallbacks.append(loaded_family)
    fallbacks.extend(["Microsoft YaHei", "Noto Sans CJK SC", "WenQuanYi Micro Hei", "Droid Sans", "sans-serif"])
    font.setFamilies([font.family()] + fallbacks)
    app.setFont(font)


def apply_dark_theme(app):
    """Applies a modern dark theme to the QApplication."""
    app.setStyle("Fusion")
    _setup_cjk_font(app)

    dark_palette = QPalette()

    # Base colors
    color_bg = QColor(30, 41, 59)         # Slate 800
    color_alt_bg = QColor(15, 23, 42)     # Slate 900
    color_text = QColor(226, 232, 240)    # Slate 200
    color_disabled = QColor(100, 116, 139) # Slate 500
    color_primary = QColor(56, 189, 248)  # Sky 400
    color_link = QColor(56, 189, 248)     # Sky 400
    color_highlight = QColor(14, 165, 233) # Sky 500 (selection)
    color_highlight_text = QColor(255, 255, 255)

    dark_palette.setColor(QPalette.Window, color_bg)
    dark_palette.setColor(QPalette.WindowText, color_text)
    dark_palette.setColor(QPalette.Base, color_alt_bg)
    dark_palette.setColor(QPalette.AlternateBase, color_bg)
    dark_palette.setColor(QPalette.ToolTipBase, color_text)
    dark_palette.setColor(QPalette.ToolTipText, color_alt_bg)
    dark_palette.setColor(QPalette.Text, color_text)
    dark_palette.setColor(QPalette.Button, color_bg)
    dark_palette.setColor(QPalette.ButtonText, color_text)
    dark_palette.setColor(QPalette.BrightText, Qt.red)
    dark_palette.setColor(QPalette.Link, color_link)
    dark_palette.setColor(QPalette.Highlight, color_highlight)
    dark_palette.setColor(QPalette.HighlightedText, color_highlight_text)
    dark_palette.setColor(QPalette.Disabled, QPalette.Text, color_disabled)
    dark_palette.setColor(QPalette.Disabled, QPalette.ButtonText, color_disabled)
    
    app.setPalette(dark_palette)

    app.setStyleSheet("""
        QToolTip { 
            color: #0f172a; 
            background-color: #e2e8f0; 
            border: 1px solid #cbd5e1; 
        }
        QGroupBox {
            border: 1px solid #475569;
            border-radius: 6px;
            margin-top: 12px;
            font-weight: bold;
            color: #94a3b8; 
        }
        QGroupBox::title {
            subcontrol-origin: margin;
            subcontrol-position: top left;
            padding: 0 4px;
            left: 8px;
        }
        QTableWidget {
            gridline-color: #334155;
            background-color: #0f172a;
            selection-background-color: #0369a1;
        }
        QHeaderView::section {
            background-color: #1e293b;
            color: #cbd5e1;
            padding: 4px;
            border: 1px solid #334155;
        }
        QLineEdit, QSpinBox, QDateEdit, QComboBox, QTextEdit {
            background-color: #0f172a;
            border: 1px solid #475569;
            border-radius: 4px;
            color: #e2e8f0;
            padding: 4px;
            selection-background-color: #0ea5e9;
        }
        QLineEdit:focus, QSpinBox:focus, QDateEdit:focus, QComboBox:focus, QTextEdit:focus {
            border: 1px solid #38bdf8;
        }
        QPushButton {
            background-color: #334155;
            border: 1px solid #475569;
            border-radius: 4px;
            color: #e2e8f0;
            padding: 6px 12px;
        }
        QPushButton:hover {
            background-color: #475569;
            border: 1px solid #64748b;
        }
        QPushButton:pressed {
            background-color: #1e293b;
        }
        QPushButton:disabled {
            background-color: #1e293b;
            color: #64748b;
            border: 1px solid #334155;
        }
        /* Specific tweaks */
        QScrollBar:vertical {
            border: none;
            background: #0f172a;
            width: 10px;
            margin: 0;
        }
        QScrollBar::handle:vertical {
            background: #475569;
            min-height: 20px;
            border-radius: 5px;
        }
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
            height: 0px;
        }
    """)

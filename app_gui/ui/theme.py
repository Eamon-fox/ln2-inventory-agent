import os

from PySide6.QtGui import QColor, QFont, QFontDatabase, QPalette
from PySide6.QtCore import Qt

_CJK_FONT_CANDIDATES = [
    os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts", "msyh.ttc"),
    os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts", "msyhbd.ttc"),
    os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts", "simsun.ttc"),
    "/usr/share/fonts/google-noto-cjk/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/google-droid/DroidSansFallback.ttf",
    "/usr/share/fonts/truetype/droid/DroidSansFallback.ttf",
    "/usr/share/fonts/wqy-microhei/wqy-microhei.ttc",
]


def _setup_cjk_font(app):
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

    font = QFont("Inter")
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
    """Applies opencode-style dark theme to the QApplication."""
    _apply_theme(app, "dark")


def apply_light_theme(app):
    """Applies opencode-style light theme to the QApplication."""
    _apply_theme(app, "light")


def _apply_theme(app, mode):
    """Internal function to apply theme."""
    app.setStyle("Fusion")
    _setup_cjk_font(app)

    if mode == "light":
        palette = QPalette()
        palette.setColor(QPalette.Window, QColor(250, 250, 250))
        palette.setColor(QPalette.WindowText, QColor(30, 30, 30))
        palette.setColor(QPalette.Base, QColor(245, 245, 245))
        palette.setColor(QPalette.AlternateBase, QColor(250, 250, 250))
        palette.setColor(QPalette.ToolTipBase, QColor(30, 30, 30))
        palette.setColor(QPalette.ToolTipText, QColor(255, 255, 255))
        palette.setColor(QPalette.Text, QColor(30, 30, 30))
        palette.setColor(QPalette.Button, QColor(255, 255, 255))
        palette.setColor(QPalette.ButtonText, QColor(30, 30, 30))
        palette.setColor(QPalette.BrightText, Qt.red)
        palette.setColor(QPalette.Link, QColor(37, 99, 235))
        palette.setColor(QPalette.Highlight, QColor(37, 99, 235))
        palette.setColor(QPalette.HighlightedText, QColor(255, 255, 255))
        palette.setColor(QPalette.Disabled, QPalette.Text, QColor(180, 180, 180))
        palette.setColor(QPalette.Disabled, QPalette.ButtonText, QColor(180, 180, 180))
        
        app.setPalette(palette)

        app.setStyleSheet("""
            :root {
                --background-base: #fafafa;
                --background-strong: #f5f5f5;
                --background-raised: #ffffff;
                --background-inset: #f0f0f0;
                --text-strong: #1e1e1e;
                --text-weak: #646464;
                --text-muted: #a0a0a0;
                --border-weak: rgba(0,0,0,0.08);
                --border-subtle: rgba(0,0,0,0.12);
                --accent: #2563eb;
                --accent-hover: #1d4ed8;
                --accent-muted: rgba(37,99,235,0.1);
                --success: #16a34a;
                --warning: #d97706;
                --error: #dc2626;
                --radius-xs: 2px;
                --radius-sm: 4px;
                --radius-md: 6px;
                --radius-lg: 8px;
            }
            QToolTip { color: #1e1e1e; background-color: #ffffff; border: 1px solid rgba(0,0,0,0.1); border-radius: 4px; padding: 4px 8px; font-size: 12px; }
            QGroupBox { border: 1px solid var(--border-weak); border-radius: var(--radius-md); margin-top: 12px; font-weight: 500; color: var(--text-weak); padding-top: 8px; }
            QGroupBox::title { subcontrol-origin: margin; subcontrol-position: top left; padding: 0 8px; left: 8px; color: var(--text-weak); font-size: 13px; }
            QTableWidget { gridline-color: rgba(0,0,0,0.06); background-color: var(--background-inset); selection-background-color: var(--accent-muted); border: 1px solid var(--border-weak); border-radius: var(--radius-sm); }
            QTableWidget::item { padding: 4px 8px; border: none; }
            QTableWidget::item:selected { background-color: var(--accent-muted); color: var(--text-strong); }
            QHeaderView::section { background-color: var(--background-strong); color: var(--text-weak); padding: 6px 8px; border: none; border-bottom: 1px solid var(--border-weak); border-right: 1px solid var(--border-weak); font-weight: 500; font-size: 12px; }
            QLineEdit, QSpinBox, QDateEdit, QComboBox, QTextEdit { background-color: var(--background-inset); border: 1px solid var(--border-weak); border-radius: var(--radius-sm); color: var(--text-strong); padding: 6px 10px; selection-background-color: var(--accent-muted); font-size: 13px; }
            QLineEdit:focus, QSpinBox:focus, QDateEdit:focus, QComboBox:focus, QTextEdit:focus { border: 1px solid var(--accent); background-color: var(--background-raised); }
            QLineEdit:disabled, QSpinBox:disabled, QDateEdit:disabled, QComboBox:disabled, QTextEdit:disabled { background-color: var(--background-strong); color: var(--text-muted); border-color: transparent; }
            QComboBox::drop-down { border: none; width: 24px; }
            QComboBox::down-arrow { image: none; border-left: 4px solid transparent; border-right: 4px solid transparent; border-top: 5px solid var(--text-weak); margin-right: 8px; }
            QComboBox QAbstractItemView { background-color: var(--background-raised); border: 1px solid var(--border-subtle); border-radius: var(--radius-sm); selection-background-color: var(--accent-muted); selection-color: var(--text-strong); padding: 4px; }
            QPushButton { background-color: var(--background-raised); border: 1px solid var(--border-weak); border-radius: var(--radius-sm); color: var(--text-strong); padding: 8px 16px; font-weight: 500; font-size: 13px; }
            QPushButton:hover { background-color: #f0f0f0; border-color: var(--border-subtle); }
            QPushButton:pressed { background-color: #e5e5e5; }
            QPushButton:disabled { background-color: var(--background-strong); color: var(--text-muted); border-color: transparent; }
            QPushButton[variant="primary"] { background-color: var(--accent); color: #ffffff; border-color: var(--accent); font-weight: 500; }
            QPushButton[variant="primary"]:hover { background-color: var(--accent-hover); border-color: var(--accent-hover); }
            QPushButton[variant="ghost"] { background-color: transparent; border-color: transparent; color: var(--text-strong); }
            QPushButton[variant="ghost"]:hover { background-color: var(--background-raised); }
            QCheckBox { color: var(--text-strong); spacing: 8px; font-size: 13px; }
            QCheckBox::indicator { width: 16px; height: 16px; border-radius: 3px; border: 1px solid var(--border-subtle); background-color: var(--background-raised); }
            QCheckBox::indicator:hover { border-color: var(--accent); }
            QCheckBox::indicator:checked { background-color: var(--accent); border-color: var(--accent); }
            QCheckBox::indicator:checked:hover { background-color: var(--accent-hover); }
            QRadioButton { color: var(--text-strong); spacing: 8px; font-size: 13px; }
            QRadioButton::indicator { width: 16px; height: 16px; border-radius: 8px; border: 1px solid var(--border-subtle); background-color: var(--background-raised); }
            QRadioButton::indicator:hover { border-color: var(--accent); }
            QRadioButton::indicator:checked { background-color: var(--accent); border-color: var(--accent); }
            QScrollBar:vertical { border: none; background: transparent; width: 6px; margin: 2px; }
            QScrollBar::handle:vertical { background: rgba(0,0,0,0.15); min-height: 24px; border-radius: 3px; }
            QScrollBar::handle:vertical:hover { background: rgba(0,0,0,0.25); }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }
            QScrollBar:horizontal { border: none; background: transparent; height: 6px; margin: 2px; }
            QScrollBar::handle:horizontal { background: rgba(0,0,0,0.15); min-width: 24px; border-radius: 3px; }
            QScrollBar::handle:horizontal:hover { background: rgba(0,0,0,0.25); }
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0px; }
            QMenu { background-color: var(--background-raised); border: 1px solid var(--border-subtle); border-radius: var(--radius-md); padding: 4px; }
            QMenu::item { padding: 8px 32px 8px 12px; border-radius: var(--radius-xs); color: var(--text-strong); }
            QMenu::item:selected { background-color: var(--accent-muted); color: var(--accent); }
            QMenu::separator { height: 1px; background-color: var(--border-weak); margin: 4px 8px; }
            QLabel { color: var(--text-strong); background-color: transparent; }
            QLabel[secondary="true"] { color: var(--text-weak); }
            QLabel[muted="true"] { color: var(--text-muted); font-size: 12px; }
            QSplitter::handle { background-color: var(--border-weak); }
            QSplitter::handle:horizontal { width: 1px; }
            QSplitter::handle:vertical { height: 1px; }
        """)
    else:
        dark_palette = QPalette()
        dark_palette.setColor(QPalette.Window, QColor(26, 26, 26))
        dark_palette.setColor(QPalette.WindowText, QColor(232, 232, 232))
        dark_palette.setColor(QPalette.Base, QColor(36, 36, 36))
        dark_palette.setColor(QPalette.AlternateBase, QColor(26, 26, 26))
        dark_palette.setColor(QPalette.ToolTipBase, QColor(232, 232, 232))
        dark_palette.setColor(QPalette.ToolTipText, QColor(36, 36, 36))
        dark_palette.setColor(QPalette.Text, QColor(232, 232, 232))
        dark_palette.setColor(QPalette.Button, QColor(45, 45, 45))
        dark_palette.setColor(QPalette.ButtonText, QColor(232, 232, 232))
        dark_palette.setColor(QPalette.BrightText, Qt.red)
        dark_palette.setColor(QPalette.Link, QColor(56, 189, 248))
        dark_palette.setColor(QPalette.Highlight, QColor(14, 165, 233))
        dark_palette.setColor(QPalette.HighlightedText, QColor(255, 255, 255))
        dark_palette.setColor(QPalette.Disabled, QPalette.Text, QColor(85, 85, 85))
        dark_palette.setColor(QPalette.Disabled, QPalette.ButtonText, QColor(85, 85, 85))
        
        app.setPalette(dark_palette)

        app.setStyleSheet("""
            :root {
                --background-base: #1a1a1a;
                --background-strong: #242424;
                --background-raised: #2d2d2d;
                --background-inset: #1f1f1f;
                --text-strong: #e8e8e8;
                --text-weak: #888888;
                --text-muted: #555555;
                --border-weak: rgba(255,255,255,0.08);
                --border-subtle: rgba(255,255,255,0.12);
                --accent: #38bdf8;
                --accent-hover: #64b4ff;
                --accent-muted: rgba(56,189,248,0.15);
                --success: #22c55e;
                --warning: #f59e0b;
                --error: #ef4444;
                --radius-xs: 2px;
                --radius-sm: 4px;
                --radius-md: 6px;
                --radius-lg: 8px;
            }
            QToolTip { color: #1a1a1a; background-color: #e8e8e8; border: 1px solid rgba(0,0,0,0.1); border-radius: 4px; padding: 4px 8px; font-size: 12px; }
            QGroupBox { border: 1px solid var(--border-weak); border-radius: var(--radius-md); margin-top: 12px; font-weight: 500; color: var(--text-weak); padding-top: 8px; }
            QGroupBox::title { subcontrol-origin: margin; subcontrol-position: top left; padding: 0 8px; left: 8px; color: var(--text-weak); font-size: 13px; }
            QTableWidget { gridline-color: rgba(255,255,255,0.06); background-color: var(--background-inset); selection-background-color: var(--accent-muted); border: 1px solid var(--border-weak); border-radius: var(--radius-sm); }
            QTableWidget::item { padding: 4px 8px; border: none; }
            QTableWidget::item:selected { background-color: var(--accent-muted); color: var(--text-strong); }
            QHeaderView::section { background-color: var(--background-strong); color: var(--text-weak); padding: 6px 8px; border: none; border-bottom: 1px solid var(--border-weak); border-right: 1px solid var(--border-weak); font-weight: 500; font-size: 12px; }
            QLineEdit, QSpinBox, QDateEdit, QComboBox, QTextEdit { background-color: var(--background-inset); border: 1px solid var(--border-weak); border-radius: var(--radius-sm); color: var(--text-strong); padding: 6px 10px; selection-background-color: var(--accent-muted); font-size: 13px; }
            QLineEdit:focus, QSpinBox:focus, QDateEdit:focus, QComboBox:focus, QTextEdit:focus { border: 1px solid var(--accent); background-color: var(--background-base); }
            QLineEdit:disabled, QSpinBox:disabled, QDateEdit:disabled, QComboBox:disabled, QTextEdit:disabled { background-color: var(--background-strong); color: var(--text-muted); border-color: transparent; }
            QComboBox::drop-down { border: none; width: 24px; }
            QComboBox::down-arrow { image: none; border-left: 4px solid transparent; border-right: 4px solid transparent; border-top: 5px solid var(--text-weak); margin-right: 8px; }
            QComboBox QAbstractItemView { background-color: var(--background-raised); border: 1px solid var(--border-subtle); border-radius: var(--radius-sm); selection-background-color: var(--accent-muted); selection-color: var(--text-strong); padding: 4px; }
            QPushButton { background-color: var(--background-raised); border: 1px solid var(--border-weak); border-radius: var(--radius-sm); color: var(--text-strong); padding: 8px 16px; font-weight: 500; font-size: 13px; }
            QPushButton:hover { background-color: #383838; border-color: var(--border-subtle); }
            QPushButton:pressed { background-color: #333333; }
            QPushButton:disabled { background-color: var(--background-strong); color: var(--text-muted); border-color: transparent; }
            QPushButton[variant="primary"] { background-color: var(--accent); color: #000000; border-color: var(--accent); font-weight: 500; }
            QPushButton[variant="primary"]:hover { background-color: var(--accent-hover); border-color: var(--accent-hover); }
            QPushButton[variant="ghost"] { background-color: transparent; border-color: transparent; color: var(--text-strong); }
            QPushButton[variant="ghost"]:hover { background-color: var(--background-raised); }
            QCheckBox { color: var(--text-strong); spacing: 8px; font-size: 13px; }
            QCheckBox::indicator { width: 16px; height: 16px; border-radius: 3px; border: 1px solid var(--border-subtle); background-color: var(--background-inset); }
            QCheckBox::indicator:hover { border-color: var(--accent); }
            QCheckBox::indicator:checked { background-color: var(--accent); border-color: var(--accent); }
            QCheckBox::indicator:checked:hover { background-color: var(--accent-hover); }
            QRadioButton { color: var(--text-strong); spacing: 8px; font-size: 13px; }
            QRadioButton::indicator { width: 16px; height: 16px; border-radius: 8px; border: 1px solid var(--border-subtle); background-color: var(--background-inset); }
            QRadioButton::indicator:hover { border-color: var(--accent); }
            QRadioButton::indicator:checked { background-color: var(--accent); border-color: var(--accent); }
            QScrollBar:vertical { border: none; background: transparent; width: 6px; margin: 2px; }
            QScrollBar::handle:vertical { background: rgba(255,255,255,0.1); min-height: 24px; border-radius: 3px; }
            QScrollBar::handle:vertical:hover { background: rgba(255,255,255,0.15); }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }
            QScrollBar:horizontal { border: none; background: transparent; height: 6px; margin: 2px; }
            QScrollBar::handle:horizontal { background: rgba(255,255,255,0.1); min-width: 24px; border-radius: 3px; }
            QScrollBar::handle:horizontal:hover { background: rgba(255,255,255,0.15); }
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0px; }
            QMenu { background-color: var(--background-raised); border: 1px solid var(--border-subtle); border-radius: var(--radius-md); padding: 4px; }
            QMenu::item { padding: 8px 32px 8px 12px; border-radius: var(--radius-xs); color: var(--text-strong); }
            QMenu::item:selected { background-color: var(--accent-muted); color: var(--accent); }
            QMenu::separator { height: 1px; background-color: var(--border-weak); margin: 4px 8px; }
            QLabel { color: var(--text-strong); background-color: transparent; }
            QLabel[secondary="true"] { color: var(--text-weak); }
            QLabel[muted="true"] { color: var(--text-muted); font-size: 12px; }
            QSplitter::handle { background-color: var(--border-weak); }
            QSplitter::handle:horizontal { width: 1px; }
            QSplitter::handle:vertical { height: 1px; }
        """)


def card_style():
    return """
        background-color: var(--background-inset);
        border: 1px solid var(--border-weak);
        border-radius: var(--radius-md);
    """


def button_primary_style():
    return """
        QPushButton {
            background-color: var(--accent);
            color: #000000;
            border: none;
            border-radius: var(--radius-sm);
            padding: 8px 16px;
            font-weight: 500;
        }
        QPushButton:hover {
            background-color: var(--accent-hover);
        }
        QPushButton:pressed {
            background-color: #2090e8;
        }
    """


def button_ghost_style():
    return """
        QPushButton {
            background-color: transparent;
            color: var(--text-strong);
            border: none;
            border-radius: var(--radius-sm);
            padding: 8px 16px;
        }
        QPushButton:hover {
            background-color: var(--background-raised);
        }
    """


def input_style():
    return """
        background-color: var(--background-inset);
        border: 1px solid var(--border-weak);
        border-radius: var(--radius-sm);
        color: var(--text-strong);
        padding: 6px 10px;
        font-size: 13px;
    """


def cell_occupied_style(color="#22c55e", is_selected=False):
    border_color = "#38bdf8" if is_selected else "#d0d0d0"
    return f"""
        QPushButton {{
            background-color: {color};
            color: white;
            border: {'2px' if is_selected else '1px'} solid {border_color};
            border-radius: var(--radius-xs);
            font-size: 9px;
            font-weight: 500;
            padding: 1px;
        }}
        QPushButton:hover {{
            border: 2px solid #38bdf8;
        }}
    """


def cell_empty_style(is_selected=False):
    border_color = "#38bdf8" if is_selected else "#d0d0d0"
    bg_color = "#e8e8e8" if is_selected else "#f5f5f5"
    text_color = "#606060" if is_selected else "#808080"
    return f"""
        QPushButton {{
            background-color: {bg_color};
            color: {text_color};
            border: {'2px' if is_selected else '1px'} solid {border_color};
            border-radius: var(--radius-xs);
            font-size: 8px;
            padding: 1px;
        }}
        QPushButton:hover {{
            border: 2px solid var(--accent);
            background-color: var(--background-raised);
            color: var(--text-weak);
        }}
    """


def cell_preview_add_style():
    return """
        QPushButton {{
            background-color: rgba(34, 197, 94, 0.25);
            color: var(--text-strong);
            border: 2px solid var(--success);
            border-radius: var(--radius-xs);
            font-size: 9px;
            font-weight: 500;
            padding: 1px;
        }}
    """


def cell_preview_takeout_style():
    return """
        QPushButton {{
            background-color: rgba(239, 68, 68, 0.25);
            color: var(--text-strong);
            border: 2px solid var(--error);
            border-radius: var(--radius-xs);
            font-size: 9px;
            font-weight: 500;
            padding: 1px;
        }}
    """


def cell_preview_move_source_style():
    return """
        QPushButton {{
            background-color: rgba(56, 189, 248, 0.2);
            color: var(--text-strong);
            border: 2px solid var(--accent);
            border-radius: var(--radius-xs);
            font-size: 9px;
            font-weight: 500;
            padding: 1px;
        }}
    """


def cell_preview_move_target_style():
    return """
        QPushButton {{
            background-color: rgba(56, 189, 248, 0.35);
            color: var(--text-strong);
            border: 2px solid var(--accent);
            border-radius: var(--radius-xs);
            font-size: 9px;
            font-weight: 500;
            padding: 1px;
        }}
    """


def chat_code_block_style(is_dark=True):
    if is_dark:
        return """
            background-color: #1a1a1a;
            border: 1px solid rgba(255,255,255,0.08);
            border-radius: 6px;
            padding: 12px;
            font-family: "IBM Plex Mono", "Consolas", "Monaco", monospace;
            font-size: 13px;
            color: #e8e8e8;
        """
    else:
        return """
            background-color: #f5f5f5;
            border: 1px solid rgba(0,0,0,0.08);
            border-radius: 6px;
            padding: 12px;
            font-family: "IBM Plex Mono", "Consolas", "Monaco", monospace;
            font-size: 13px;
            color: #1e1e1e;
        """


def chat_inline_code_style(is_dark=True):
    if is_dark:
        return "background-color: rgba(255,255,255,0.1); padding: 2px 6px; border-radius: 4px; font-family: monospace;"
    else:
        return "background-color: rgba(0,0,0,0.06); padding: 2px 6px; border-radius: 4px; font-family: monospace;"


def chat_collapsible_header_style(is_dark=True):
    if is_dark:
        return """
            QPushButton {
                background-color: #242424;
                border: 1px solid rgba(255,255,255,0.08);
                border-radius: 6px;
                padding: 8px 12px;
                text-align: left;
                font-size: 13px;
                color: #e8e8e8;
            }
            QPushButton:hover {
                background-color: #2d2d2d;
                border-color: rgba(255,255,255,0.12);
            }
            QPushButton:checked {
                border-bottom-left-radius: 0;
                border-bottom-right-radius: 0;
            }
        """
    else:
        return """
            QPushButton {
                background-color: #f5f5f5;
                border: 1px solid rgba(0,0,0,0.08);
                border-radius: 6px;
                padding: 8px 12px;
                text-align: left;
                font-size: 13px;
                color: #1e1e1e;
            }
            QPushButton:hover {
                background-color: #eaeaea;
                border-color: rgba(0,0,0,0.12);
            }
            QPushButton:checked {
                border-bottom-left-radius: 0;
                border-bottom-right-radius: 0;
            }
        """


def chat_collapsible_content_style(is_dark=True):
    if is_dark:
        return """
            background-color: #1f1f1f;
            border: 1px solid rgba(255,255,255,0.08);
            border-top: none;
            border-bottom-left-radius: 6px;
            border-bottom-right-radius: 6px;
            padding: 8px 12px;
            font-family: "IBM Plex Mono", monospace;
            font-size: 12px;
            color: #888888;
        """
    else:
        return """
            background-color: #fafafa;
            border: 1px solid rgba(0,0,0,0.08);
            border-top: none;
            border-bottom-left-radius: 6px;
            border-bottom-right-radius: 6px;
            padding: 8px 12px;
            font-family: "IBM Plex Mono", monospace;
            font-size: 12px;
            color: #646464;
        """


def syntax_colors(is_dark=True):
    if is_dark:
        return {
            "string": "#00ceb9",
            "primitive": "#ffba92",
            "property": "#ff9ae2",
            "type": "#ecf58c",
            "constant": "#93e9f6",
            "keyword": "#c792ea",
            "comment": "#636d83",
            "number": "#f78c6c",
        }
    else:
        return {
            "string": "#006656",
            "primitive": "#fb4804",
            "property": "#ed6dc8",
            "type": "#596600",
            "constant": "#007b80",
            "keyword": "#8b0a50",
            "comment": "#6a737d",
            "number": "#b52a1d",
        }

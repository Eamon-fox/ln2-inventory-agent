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
    """Applies the dark theme to the QApplication."""
    _apply_theme(app, "dark")


def apply_light_theme(app):
    """Applies the light theme to the QApplication."""
    _apply_theme(app, "light")


def _apply_theme(app, mode):
    """Internal function to apply theme."""
    app.setStyle("Fusion")
    _setup_cjk_font(app)

    if mode == "light":
        palette = QPalette()
        palette.setColor(QPalette.Window, QColor(247, 250, 252))
        palette.setColor(QPalette.WindowText, QColor(15, 23, 42))
        palette.setColor(QPalette.Base, QColor(241, 246, 251))
        palette.setColor(QPalette.AlternateBase, QColor(247, 250, 252))
        palette.setColor(QPalette.ToolTipBase, QColor(15, 23, 42))
        palette.setColor(QPalette.ToolTipText, QColor(255, 255, 255))
        palette.setColor(QPalette.Text, QColor(15, 23, 42))
        palette.setColor(QPalette.Button, QColor(255, 255, 255))
        palette.setColor(QPalette.ButtonText, QColor(15, 23, 42))
        palette.setColor(QPalette.BrightText, Qt.red)
        palette.setColor(QPalette.Link, QColor(43, 127, 229))
        palette.setColor(QPalette.Highlight, QColor(43, 127, 229))
        palette.setColor(QPalette.HighlightedText, QColor(255, 255, 255))
        palette.setColor(QPalette.Disabled, QPalette.Text, QColor(148, 163, 184))
        palette.setColor(QPalette.Disabled, QPalette.ButtonText, QColor(148, 163, 184))
        palette.setColor(QPalette.PlaceholderText, QColor(148, 163, 184))
        
        app.setPalette(palette)

        app.setStyleSheet("""
            :root {
                --background-base: #f7fafc;
                --background-strong: #eef3f8;
                --background-raised: #ffffff;
                --background-inset: #f1f6fb;
                --text-strong: #0f172a;
                --text-weak: #334155;
                --text-muted: #64748b;
                --border-weak: rgba(15,23,42,0.10);
                --border-subtle: rgba(15,23,42,0.18);
                --accent: #2b7fe5;
                --accent-hover: #1f6ed0;
                --accent-muted: rgba(43,127,229,0.14);
                --success: #16a34a;
                --warning: #d97706;
                --error: #dc2626;
                --radius-xs: 2px;
                --radius-sm: 4px;
                --radius-md: 6px;
                --radius-lg: 8px;
                --btn-danger: #dc2626;
                --btn-danger-hover: #b91c1c;
                --btn-danger-border: #7f1d1d;
                --btn-warning: #d97706;
                --btn-warning-hover: #b45309;
                --btn-warning-border: #92400e;
                --btn-primary: #2b7fe5;
                --btn-primary-hover: #1f6ed0;
                --btn-primary-border: #174f98;
                --status-success: #15803d;
                --status-warning: #b45309;
                --status-error: #b91c1c;
                --status-muted: #64748b;
                --cell-border-default: #c6d3e3;
                --cell-empty-bg: #eef3f8;
                --cell-empty-selected-bg: #deebf8;
                --cell-empty-text: #6b7f95;
                --cell-empty-selected-text: #34506d;
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
            QPushButton:hover { background-color: #f2f6fb; border-color: var(--border-subtle); }
            QPushButton:pressed { background-color: #e6eef7; }
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
            /* Variant buttons */
            QPushButton[variant="primary"] { background-color: var(--btn-primary); color: #ffffff; font-weight: bold; border: 1px solid var(--btn-primary-border); }
            QPushButton[variant="primary"]:hover { background-color: var(--btn-primary-hover); }
            QPushButton[variant="primary"]:pressed { background-color: var(--btn-primary-border); }
            QPushButton[variant="danger"] { background-color: var(--btn-danger); color: #ffffff; font-weight: bold; border: 1px solid var(--btn-danger-border); }
            QPushButton[variant="danger"]:hover { background-color: var(--btn-danger-hover); }
            QPushButton[variant="danger"]:pressed { background-color: var(--btn-danger-border); }
            QPushButton[variant="ghost"] { background-color: transparent; color: var(--text-weak); border: none; }
            QPushButton[variant="ghost"]:hover { background-color: var(--background-raised); }
            /* AI Panel - floating dock */
            QTextEdit#aiChatArea { border: none; background-color: transparent; padding: 2px 4px; color: var(--text-strong); }
            QWidget#aiPromptDock { background-color: transparent; }
            QWidget#aiInputContainer { background-color: rgba(0,0,0,0.04); border: 1px solid rgba(0,0,0,0.06); border-radius: 12px; }
            QTextEdit#aiPromptInput { border: none; border-radius: 8px; background-color: transparent; padding: 2px 4px; font-size: 13px; color: var(--text-strong); }
            QPushButton[class="quick-prompt-btn"] { padding: 3px 10px; font-size: 11px; border-radius: 10px; background-color: rgba(43,127,229,0.10); border: none; color: #34506d; }
            QPushButton[class="quick-prompt-btn"]:hover { background-color: rgba(43,127,229,0.18); color: #0f172a; }
            QWidget#OverviewPanel { background-color: #f5f9fd; }
        """)
    else:
        dark_palette = QPalette()
        dark_palette.setColor(QPalette.Window, QColor(15, 23, 36))
        dark_palette.setColor(QPalette.WindowText, QColor(230, 241, 255))
        dark_palette.setColor(QPalette.Base, QColor(19, 32, 51))
        dark_palette.setColor(QPalette.AlternateBase, QColor(15, 23, 36))
        dark_palette.setColor(QPalette.ToolTipBase, QColor(230, 241, 255))
        dark_palette.setColor(QPalette.ToolTipText, QColor(19, 32, 51))
        dark_palette.setColor(QPalette.Text, QColor(230, 241, 255))
        dark_palette.setColor(QPalette.Button, QColor(27, 42, 63))
        dark_palette.setColor(QPalette.ButtonText, QColor(230, 241, 255))
        dark_palette.setColor(QPalette.BrightText, Qt.red)
        dark_palette.setColor(QPalette.Link, QColor(99, 179, 255))
        dark_palette.setColor(QPalette.Highlight, QColor(99, 179, 255))
        dark_palette.setColor(QPalette.HighlightedText, QColor(255, 255, 255))
        dark_palette.setColor(QPalette.Disabled, QPalette.Text, QColor(109, 130, 152))
        dark_palette.setColor(QPalette.Disabled, QPalette.ButtonText, QColor(109, 130, 152))
        dark_palette.setColor(QPalette.PlaceholderText, QColor(109, 130, 152))
        
        app.setPalette(dark_palette)

        app.setStyleSheet("""
            :root {
                --background-base: #0f1724;
                --background-strong: #152235;
                --background-raised: #1b2a3f;
                --background-inset: #132033;
                --text-strong: #e6f1ff;
                --text-weak: #9fb3c8;
                --text-muted: #6d8298;
                --border-weak: rgba(159,179,200,0.15);
                --border-subtle: rgba(159,179,200,0.24);
                --accent: #63b3ff;
                --accent-hover: #8bc7ff;
                --accent-muted: rgba(99,179,255,0.22);
                --success: #22c55e;
                --warning: #f59e0b;
                --error: #ef4444;
                --radius-xs: 2px;
                --radius-sm: 4px;
                --radius-md: 6px;
                --radius-lg: 8px;
                --btn-danger: #ef4444;
                --btn-danger-hover: #dc2626;
                --btn-danger-border: #991b1b;
                --btn-warning: #f59e0b;
                --btn-warning-hover: #d97706;
                --btn-warning-border: #b45309;
                --btn-primary: #63b3ff;
                --btn-primary-hover: #8bc7ff;
                --btn-primary-border: #3c90df;
                --status-success: #22c55e;
                --status-warning: #f59e0b;
                --status-error: #ef4444;
                --status-muted: #94a3b8;
                --cell-border-default: #36506d;
                --cell-empty-bg: #1a2a40;
                --cell-empty-selected-bg: #223956;
                --cell-empty-text: #86a0bb;
                --cell-empty-selected-text: #c6dbf3;
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
            QPushButton:hover { background-color: #24364d; border-color: var(--border-subtle); }
            QPushButton:pressed { background-color: #1e3047; }
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
            /* Variant buttons */
            QPushButton[variant="primary"] { background-color: var(--btn-primary); color: #ffffff; font-weight: bold; border: 1px solid var(--btn-primary-border); }
            QPushButton[variant="primary"]:hover { background-color: var(--btn-primary-hover); }
            QPushButton[variant="primary"]:pressed { background-color: var(--btn-primary-border); }
            QPushButton[variant="danger"] { background-color: var(--btn-danger); color: #ffffff; font-weight: bold; border: 1px solid var(--btn-danger-border); }
            QPushButton[variant="danger"]:hover { background-color: var(--btn-danger-hover); }
            QPushButton[variant="danger"]:pressed { background-color: var(--btn-danger-border); }
            QPushButton[variant="ghost"] { background-color: transparent; color: var(--text-weak); border: none; }
            QPushButton[variant="ghost"]:hover { background-color: var(--background-raised); }
            /* AI Panel - floating dock */
            QTextEdit#aiChatArea { border: none; background-color: transparent; padding: 2px 4px; color: var(--text-strong); }
            QWidget#aiPromptDock { background-color: transparent; }
            QWidget#aiInputContainer { background-color: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.06); border-radius: 12px; }
            QTextEdit#aiPromptInput { border: none; border-radius: 8px; background-color: transparent; padding: 2px 4px; font-size: 13px; color: var(--text-strong); }
            QPushButton[class="quick-prompt-btn"] { padding: 3px 10px; font-size: 11px; border-radius: 10px; background-color: rgba(99,179,255,0.16); border: none; color: #a9c6e3; }
            QPushButton[class="quick-prompt-btn"]:hover { background-color: rgba(99,179,255,0.24); color: #e6f1ff; }
            QWidget#OverviewPanel { background-color: #112033; }
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
            background-color: var(--btn-primary);
            color: #ffffff;
            border: 1px solid var(--btn-primary-border);
            border-radius: var(--radius-sm);
            padding: 8px 16px;
            font-weight: 500;
        }
        QPushButton:hover {
            background-color: var(--btn-primary-hover);
        }
        QPushButton:pressed {
            background-color: var(--btn-primary-border);
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


def button_danger_style():
    return """
        QPushButton {
            background-color: var(--btn-danger);
            color: #ffffff;
            border: 1px solid var(--btn-danger-border);
            border-radius: var(--radius-sm);
            padding: 8px 16px;
            font-weight: 500;
        }
        QPushButton:hover {
            background-color: var(--btn-danger-hover);
        }
        QPushButton:pressed {
            background-color: var(--btn-danger-border);
        }
    """


def button_warning_style():
    return """
        QPushButton {
            background-color: var(--btn-warning);
            color: #ffffff;
            border: 1px solid var(--btn-warning-border);
            border-radius: var(--radius-sm);
            padding: 8px 16px;
            font-weight: 500;
        }
        QPushButton:hover {
            background-color: var(--btn-warning-hover);
        }
        QPushButton:pressed {
            background-color: var(--btn-warning-border);
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


def cell_occupied_style(color="#22c55e", is_selected=False, font_size=9):
    if is_selected:
        return f"""
            QPushButton {{
                background-color: {color};
                color: white;
                border: 2px solid var(--accent);
                border-radius: var(--radius-xs);
                font-size: {font_size}px;
                font-weight: 500;
                padding: 1px;

            }}
            QPushButton:hover {{
                border: 2px solid var(--accent);
            }}
        """
    else:
        return f"""
            QPushButton {{
                background-color: {color};
                color: white;
                border: 1px solid var(--cell-border-default);
                border-radius: var(--radius-xs);
                font-size: {font_size}px;
                font-weight: 500;
                padding: 1px;

            }}
            QPushButton:hover {{
                border: 2px solid var(--accent);
            }}
        """


def cell_empty_style(is_selected=False, font_size=8):
    if is_selected:
        return f"""
            QPushButton {{
                background-color: var(--cell-empty-selected-bg);
                color: var(--cell-empty-selected-text);
                border: 2px solid var(--accent);
                border-radius: var(--radius-xs);
                font-size: {font_size}px;
                padding: 1px;

            }}
            QPushButton:hover {{
                border: 2px solid var(--accent);
                background-color: var(--background-raised);
                color: var(--text-weak);
            }}
        """
    else:
        return f"""
            QPushButton {{
                background-color: var(--cell-empty-bg);
                color: var(--cell-empty-text);
                border: 1px solid var(--cell-border-default);
                border-radius: var(--radius-xs);
                font-size: {font_size}px;
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
            cursor: pointing-hand;
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
            cursor: pointing-hand;
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
            cursor: pointing-hand;
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
            cursor: pointing-hand;
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


_THEME_COLORS = {
    "light": {
        "success": QColor(21, 128, 61),
        "warning": QColor(180, 83, 9),
        "error": QColor(185, 28, 28),
        "muted": QColor(100, 116, 139),
    },
    "dark": {
        "success": QColor(34, 197, 94),
        "warning": QColor(245, 158, 11),
        "error": QColor(239, 68, 68),
        "muted": QColor(148, 163, 184),
    },
}


def get_theme_color(color_name, is_dark=True):
    theme = "dark" if is_dark else "light"
    return _THEME_COLORS.get(theme, {}).get(color_name, QColor(128, 128, 128))

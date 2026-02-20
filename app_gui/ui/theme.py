import os
import re

from PySide6.QtGui import QColor, QFont, QFontDatabase, QPalette
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication


# =============================================================================
# Typography / Font Size Configuration
# =============================================================================
# Usage in f-strings: f"font-size: {FONT_SIZE_SM}px;"
FONT_SIZE_CELL = 13      # Grid cells, smallest text (increased for overview readability)
FONT_SIZE_MONO = 12      # Monospace/code blocks
FONT_SIZE_XS = 12        # Hints, small buttons, secondary text
FONT_SIZE_SM = 13        # Body text, tooltips
FONT_SIZE_MD = 14        # Default size for buttons, inputs, titles
FONT_SIZE_LG = 16        # Large titles
FONT_SIZE_XL = 20        # Extra large (big numbers)
FONT_SIZE_XXL = 24       # Huge text (rarely used)

FONT_POINT_SIZE = 11     # QApplication global font point size

# Font weights for better typography hierarchy
FONT_WEIGHT_NORMAL = 400
FONT_WEIGHT_MEDIUM = 500
FONT_WEIGHT_SEMIBOLD = 600
FONT_WEIGHT_BOLD = 700

# Line heights for better readability
LINE_HEIGHT_TIGHT = 1.2   # Headings
LINE_HEIGHT_NORMAL = 1.5  # Body text
LINE_HEIGHT_RELAXED = 1.75 # Long-form content


# =============================================================================
# Spacing System (4px-based scale)
# =============================================================================
# Consistent spacing tokens for margins, paddings, and gaps
SPACE_1 = 4    # Tight spacing
SPACE_2 = 8    # Default spacing
SPACE_3 = 12   # Medium spacing
SPACE_4 = 16   # Large spacing
SPACE_5 = 20   # XL spacing
SPACE_6 = 24   # XXL spacing
SPACE_8 = 32   # Huge spacing


# =============================================================================
# Animation System
# =============================================================================
# Duration constants for consistent animations
ANIMATION_DURATION_FAST = 80    # Quick feedback (hover)
ANIMATION_DURATION_NORMAL = 150 # Standard transitions
ANIMATION_DURATION_SLOW = 300   # Smooth entrances

# Material Design easing function
ANIMATION_EASING = "cubic-bezier(0.4, 0.0, 0.2, 1)"


# =============================================================================
# Layout Configuration
# =============================================================================
# Panel width constraints (in pixels, resolution-independent)
LAYOUT_OVERVIEW_MIN_WIDTH = 400        # Overview panel minimum width
LAYOUT_OPS_MIN_WIDTH = 280             # Operations panel minimum width
LAYOUT_OPS_MAX_WIDTH = 450             # Operations panel maximum width
LAYOUT_OPS_DEFAULT_WIDTH = 350         # Operations panel preferred width
LAYOUT_AI_MIN_WIDTH = 280              # AI panel minimum width
LAYOUT_AI_MAX_WIDTH = 450              # AI panel maximum width
LAYOUT_AI_DEFAULT_WIDTH = 320          # AI panel preferred width

# Spacing
LAYOUT_SPLITTER_HANDLE_WIDTH = 6       # Width of draggable splitter handles

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
    font.setPointSize(FONT_POINT_SIZE)
    fallbacks = [
        "Segoe UI",
        "Roboto",
        "Cantarell",
        "DejaVu Sans",
    ]
    if loaded_family:
        fallbacks.append(loaded_family)
    fallbacks.extend(["Microsoft YaHei", "Noto Sans CJK SC", "WenQuanYi Micro Hei", "Droid Sans", "sans-serif"])
    font.setFamilies([font.family()] + fallbacks)
    app.setFont(font)


def _resolve_qss_vars(stylesheet):
    """Expand CSS var() tokens for Qt style sheets.

    Qt QSS does not support CSS custom properties (``:root`` / ``var()``),
    so we resolve them before applying the style string.
    """
    token_map = {}
    for block in re.findall(r":root\s*\{([^}]*)\}", stylesheet, flags=re.S):
        for match in re.finditer(r"--([A-Za-z0-9_-]+)\s*:\s*([^;]+);", block):
            key = match.group(1).strip()
            value = match.group(2).strip()
            if key and value:
                token_map[f"var(--{key})"] = value

    # Remove :root blocks; Qt QSS does not understand them.
    resolved = re.sub(r":root\s*\{[^}]*\}\s*", "", stylesheet, flags=re.S)

    # Resolve nested var(...) references (e.g. var(--input-focus-bg) -> var(--bg) -> #fff).
    for _ in range(4):
        prev = resolved
        for token, value in token_map.items():
            resolved = resolved.replace(token, value)
        if resolved == prev:
            break

    return resolved


def _current_theme_mode():
    """Best-effort theme mode inference from current app palette."""
    app = QApplication.instance()
    if app is None:
        return "dark"
    window = app.palette().color(QPalette.Window)
    return "dark" if window.lightness() < 128 else "light"


def _resolve_inline_qss(fragment, mode=None):
    """Resolve var(--token) in runtime inline QSS fragments."""
    active_mode = mode or _current_theme_mode()
    wrapped = f":root {{ {_get_theme_vars(active_mode)} }}\n{fragment}"
    return _resolve_qss_vars(wrapped)


def _get_theme_vars(mode):
    """Return CSS variables for the given theme mode."""
    if mode == "light":
        return """
            --background-base: #f7fafc;
            --background-strong: #eef3f8;
            --background-raised: #ffffff;
            --background-default: #ffffff;
            --background-inset: #f1f6fb;
            --background-hover: #f2f6fb;
            --text-strong: #0f172a;
            --text-weak: #334155;
            --text-muted: #64748b;
            --text-primary: #0f172a;
            --text-secondary: #64748b;
            --border-weak: rgba(15,23,42,0.10);
            --border-subtle: rgba(15,23,42,0.18);
            --border-strong: rgba(15,23,42,0.28);
            --accent: #2b7fe5;
            --accent-hover: #1f6ed0;
            --accent-muted: rgba(43,127,229,0.14);
            --success: #16a34a;
            --warning: #d97706;
            --error: #dc2626;
            --status-success-bg: rgba(22,163,74,0.12);
            --button-background: #ffffff;
            --button-border: #cbd5e1;
            --button-hover: #f2f6fb;
            --button-pressed: #e6eef7;
            --input-bg: #ffffff;
            --input-border: rgba(15,23,42,0.16);
            --input-border-focus: #2b7fe5;
            --input-text: #0f172a;
            --input-placeholder: #64748b;
            --display-bg: #f1f6fb;
            --display-text: #0f172a;
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
            --table-gridline: rgba(15,23,42,0.10);
            --cell-border-default: #95adc6;
            --cell-empty-bg: #eef3f8;
            --cell-empty-selected-bg: #deebf8;
            --cell-empty-text: #6b7f95;
            --cell-empty-selected-text: #34506d;
            --scrollbar-handle: rgba(0,0,0,0.15);
            --scrollbar-handle-hover: rgba(0,0,0,0.25);
            --splitter-color: rgba(15,23,42,0.12);
            --splitter-hover: rgba(43,127,229,0.35);
            --overview-bg: #f5f9fd;
            --tooltip-bg: #ffffff;
            --tooltip-color: #1e1e1e;
            --input-focus-bg: var(--background-raised);
            --primary-btn-text: #ffffff;
            --toggle-checked-text: #ffffff;
            --quick-prompt-bg: rgba(43,127,229,0.10);
            --quick-prompt-color: #34506d;
            --quick-prompt-hover-bg: rgba(43,127,229,0.18);
            --quick-prompt-hover-color: #0f172a;
            --radio-bg: var(--background-raised);
        """
    else:  # dark
        return """
            --background-base: #0f1724;
            --background-strong: #152235;
            --background-raised: #1b2a3f;
            --background-default: #1b2a3f;
            --background-inset: #132033;
            --background-hover: #24364d;
            --text-strong: #e6f1ff;
            --text-weak: #9fb3c8;
            --text-muted: #6d8298;
            --text-primary: #e6f1ff;
            --text-secondary: #9fb3c8;
            --border-weak: #6b8aaa;
            --border-subtle: #7a9aba;
            --border-strong: #9fb3c8;
            --accent: #63b3ff;
            --accent-hover: #8bc7ff;
            --accent-muted: rgba(99,179,255,0.22);
            --success: #22c55e;
            --warning: #f59e0b;
            --error: #ef4444;
            --status-success-bg: rgba(34,197,94,0.14);
            --button-background: #1e2a3a;
            --button-border: #475569;
            --button-hover: #24364d;
            --button-pressed: #1e3047;
            --input-bg: #1b2a3f;
            --input-border: #5b728a;
            --input-border-focus: #63b3ff;
            --input-text: #e6f1ff;
            --input-placeholder: #86a0bb;
            --display-bg: #132033;
            --display-text: #e6f1ff;
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
            --table-gridline: rgba(159,179,200,0.20);
            --cell-border-default: #4e6a88;
            --cell-empty-bg: #1a2a40;
            --cell-empty-selected-bg: #223956;
            --cell-empty-text: #86a0bb;
            --cell-empty-selected-text: #c6dbf3;
            --scrollbar-handle: rgba(255,255,255,0.1);
            --scrollbar-handle-hover: rgba(255,255,255,0.15);
            --splitter-color: rgba(159,179,200,0.18);
            --splitter-hover: rgba(99,179,255,0.42);
            --overview-bg: #112033;
            --tooltip-bg: #e8e8e8;
            --tooltip-color: #1a1a1a;
            --input-focus-bg: var(--background-base);
            --primary-btn-text: #ffffff;
            --toggle-checked-text: #000000;
            --quick-prompt-bg: rgba(99,179,255,0.16);
            --quick-prompt-color: #a9c6e3;
            --quick-prompt-hover-bg: rgba(99,179,255,0.24);
            --quick-prompt-hover-color: #e6f1ff;
            --radio-bg: var(--background-inset);
        """


def _get_common_qss():
    """Return common QSS styles that work for both themes."""
    qss = """
        :root {
            /* Border radius */
            --radius-xs: 1px;
            --radius-sm: 1px;
            --radius-md: 6px;
            --radius-lg: 8px;

            /* Spacing */
            --space-1: 4px;
            --space-2: 8px;
            --space-3: 12px;
            --space-4: 16px;
            --space-5: 20px;
            --space-6: 24px;
            --space-8: 32px;

            /* Borders */
            --border-thin: 1px;
            --border-medium: 2px;
            --border-thick: 3px;

            /* Sizes */
            --input-height: 20px;
            --indicator-sm: 16px;
            --indicator-md: 18px;
            --input-icon-size: 16px;
            --input-arrow-size: 8px;
            --scrollbar-width: 6px;
            --scrollbar-handle-min: 24px;
            --scrollbar-handle-radius: 3px;
            --splitter-width: 6px;
            --splitter-radius: 2px;
        }
        QToolTip { color: var(--tooltip-color); background-color: var(--tooltip-bg); border: 1px solid rgba(0,0,0,0.1); border-radius: var(--radius-sm); padding: var(--space-1) var(--space-2); font-size: {FONT_SIZE_SM}px; }
        QGroupBox {{ border: var(--border-thin) solid var(--border-weak); border-radius: var(--radius-lg); margin-top: var(--space-3); font-weight: {FONT_WEIGHT_MEDIUM}; color: var(--text-weak); padding-top: var(--space-2); }}
        QGroupBox::title {{ subcontrol-origin: margin; subcontrol-position: top left; padding: 0 var(--space-2); left: var(--space-2); color: var(--text-weak); font-size: {FONT_SIZE_MD}px; }}
        QTableWidget {{ gridline-color: var(--table-gridline); background-color: var(--background-inset); selection-background-color: var(--accent-muted); border: var(--border-thin) solid var(--border-weak); border-radius: var(--radius-md); }}
        QTableWidget::item {{ padding: var(--space-1) var(--space-2); border: none; }}
        QTableWidget::item:selected {{ background-color: var(--accent-muted); color: var(--text-strong); }}
        QHeaderView::section {{ background-color: var(--background-strong); color: var(--text-weak); padding: 6px var(--space-2); border: none; border-bottom: var(--border-thin) solid var(--border-weak); border-right: var(--border-thin) solid var(--border-weak); font-weight: 500; font-size: {FONT_SIZE_SM}px; }}
        QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QDateEdit {{ min-height: var(--input-height); max-height: var(--input-height); }}
        QLineEdit, QComboBox {{ padding: 0 var(--space-2); }}
        QSpinBox, QDoubleSpinBox, QDateEdit {{ padding: 0; margin: 0; }}
        QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QDateEdit, QTextEdit, QTextBrowser, QPlainTextEdit {{ background-color: var(--input-bg); border: var(--border-thin) solid var(--input-border); border-radius: var(--radius-sm); color: var(--input-text); selection-background-color: var(--accent-muted); selection-color: var(--text-strong); }}
        QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus, QDateEdit:focus, QTextEdit:focus, QTextBrowser:focus, QPlainTextEdit:focus {{ border-color: var(--input-border-focus); background-color: var(--input-focus-bg); }}
        QLineEdit[readOnly="true"], QTextEdit[readOnly="true"], QTextBrowser[readOnly="true"], QPlainTextEdit[readOnly="true"] {{ background-color: var(--display-bg); border-color: transparent; color: var(--display-text); }}
        QPushButton {{ background-color: var(--button-background); border: var(--border-thin) solid var(--button-border); border-radius: var(--radius-xs); color: var(--text-strong); padding: 1px var(--space-2); font-weight: {FONT_WEIGHT_MEDIUM}; font-size: {FONT_SIZE_MD}px; }}
        QPushButton:hover {{ background-color: var(--button-hover); border-color: var(--button-border); }}
        QPushButton:focus {{ border: var(--border-thin) solid var(--accent); outline: none; }}
        QPushButton:pressed {{ background-color: var(--button-pressed); }}
        QPushButton:disabled {{ background-color: var(--background-strong); color: var(--text-muted); border-color: transparent; opacity: 0.6; }}
        QWidget#overviewViewToggle {{ background-color: transparent; border: none; border-radius: 0; padding: 0; }}
        QWidget#overviewViewToggle QPushButton[segmented] {{ background-color: transparent; border: none; border-radius: 0; color: var(--text-strong); padding: var(--space-1) var(--space-2); margin: 0; }}
        QWidget#overviewViewToggle QPushButton[segmented]:hover:!checked {{ background-color: var(--button-hover); }}
        QWidget#overviewViewToggle QPushButton[segmented]:checked {{ background-color: var(--accent); color: var(--toggle-checked-text); }}
        QWidget#overviewViewToggle QPushButton[segmented="left"] {{ border-top-left-radius: var(--radius-xs); border-bottom-left-radius: var(--radius-xs); }}
        QWidget#overviewViewToggle QPushButton[segmented="right"] {{ border-left: var(--border-thin) solid var(--button-border); border-top-right-radius: var(--radius-xs); border-bottom-right-radius: var(--radius-xs); }}
        QWidget#overviewViewToggle QPushButton[segmented="right"]:checked {{ border-left-color: var(--accent); }}
        QPushButton#overviewBoxNavButton {{ border: var(--border-thin) solid var(--border-weak); background: transparent; border-radius: var(--radius-xs); font-size: {FONT_SIZE_XS}px; padding: 0; }}
        QPushButton#overviewBoxNavButton:hover {{ background: var(--background-hover); border-color: var(--border-strong); }}
        QLabel#operationsPlanEmptyLabel {{ color: var(--warning); padding: 16px; font-weight: 500; background-color: var(--background-inset); border: var(--border-thin) solid var(--border-weak); border-radius: var(--radius-md); }}
        QTableWidget#operationsPlanTable {{ border: var(--border-thin) solid var(--border-weak); border-radius: var(--radius-md); }}
        QWidget#resultCard {{ background-color: var(--background-inset); border: 1px solid var(--border-weak); border-radius: var(--radius-md); }}
        QWidget#resultCard[state="success"] {{ border-color: var(--success); }}
        QWidget#resultCard[state="warning"] {{ border-color: var(--warning); }}
        QWidget#resultCard[state="error"] {{ border-color: var(--error); }}
        QLabel#operationsResultTitle {{ color: var(--text-weak); font-size: {FONT_SIZE_MD}px; font-weight: {FONT_WEIGHT_BOLD}; border: none; }}
        QTextBrowser#operationsResultSummary {{ color: var(--text-strong); border: none; background: transparent; }}
        QWidget#operationsResultActions {{ background: transparent; }}
        QWidget#operationsResultActions QPushButton {{ min-height: 28px; }}
        QLabel#operationsPlanFeedback {{ border: 1px solid var(--border-weak); border-radius: var(--radius-sm); padding: 8px 10px; }}
        QLabel#operationsPlanFeedback[level="info"] {{ color: var(--text-muted); background: var(--background-inset); }}
        QLabel#operationsPlanFeedback[level="warning"] {{ color: var(--status-warning); background: rgba(255, 193, 7, 0.12); }}
        QLabel#operationsPlanFeedback[level="error"] {{ color: var(--status-error); background: rgba(220, 53, 69, 0.12); }}
        QLabel[role="statusWarning"] {{ color: var(--status-warning); }}
        QLabel[role="readonlyField"] {{ background: var(--display-bg); border: none; color: var(--display-text); padding: 2px 4px; }}
        QLineEdit[role="contextEditable"][readOnly="true"] {{ background: var(--display-bg); border: none; color: var(--display-text); padding: 2px 4px; }}
        QLineEdit[role="contextEditable"][readOnly="false"] {{ background: var(--input-bg); border: var(--border-thin) solid var(--input-border-focus); color: var(--input-text); padding: 2px 4px; }}
        QPushButton#inlineLockBtn {{ border: none; padding: 0; font-size: {FONT_SIZE_SM}px; background: transparent; }}
        QPushButton#inlineConfirmBtn {{ border: none; padding: 0; font-size: {FONT_SIZE_LG}px; font-weight: {FONT_WEIGHT_BOLD}; color: var(--status-success); background: transparent; }}
        QLabel[role="mutedInline"] {{ color: var(--text-muted); }}
        QWidget#overviewStatCard {{ background-color: var(--background-inset); border: var(--border-thin) solid var(--border-weak); border-radius: var(--radius-md); margin-top: 8px; padding-top: 8px; }}
        QWidget#overviewStatCard QLabel#overviewStatValue {{ color: var(--text-strong); font-weight: {FONT_WEIGHT_MEDIUM}; font-size: {FONT_SIZE_XL}px; }}
        QPushButton#overviewIconButton {{ border: none; background: transparent; }}
        QLabel#overviewZoomLabel {{ font-size: {FONT_SIZE_XS}px; }}
        QLabel#overviewZoomSeparator {{ color: var(--border-weak); margin: 0 4px; }}
        QLabel#overviewHoverHint {{ color: var(--text-weak); font-weight: {FONT_WEIGHT_MEDIUM}; }}
        QLabel#overviewHoverHint[state="warning"] {{ color: var(--warning); padding: 8px; background-color: rgba(245,158,11,0.1); border-radius: var(--radius-xs); }}
        QLabel[role="settingsHint"], QLabel[role="dialogHint"] {{ color: var(--text-muted); font-size: {FONT_SIZE_XS}px; margin-left: 100px; }}
        QLabel[role="dialogHint"] {{ margin-left: 0; margin-bottom: 4px; }}
        QLabel[role="cfHeaderLabel"] {{ font-size: {FONT_SIZE_XS}px; color: var(--text-muted); font-weight: {FONT_WEIGHT_SEMIBOLD}; }}
        QLabel[role="inlineFormLabel"] {{ font-size: {FONT_SIZE_SM}px; }}
        QLineEdit#settingsModelPreview {{ color: var(--text-muted); }}
        QLabel#settingsAboutLabel, QLabel#settingsSupportLabel {{ color: var(--text-muted); font-size: {FONT_SIZE_SM}px; }}
        QLabel#settingsAboutLabel {{ padding: 4px; }}
        QLabel#settingsSupportLabel {{ margin-bottom: 4px; }}
        QLabel#mainStatsBar {{ color: var(--text-muted); font-size: {FONT_SIZE_XS}px; padding: 1px 6px; }}
        QLabel#auditEventDetail {{ background-color: var(--background-inset); border: 1px solid var(--border-weak); border-radius: var(--radius-sm); padding: 8px; }}
        QLabel#auditEventDetail[state="success"] {{ border-color: var(--success); }}
        QLabel#auditEventDetail[state="error"] {{ border-color: var(--error); }}
        QLabel#auditEventDetail[state="default"] {{ border-color: var(--border-weak); }}
        QLabel#aiInputHint {{ font-size: {FONT_SIZE_XS}px; padding-right: 2px; }}
        QPushButton[variant="primary"] {{ background-color: var(--accent); color: var(--primary-btn-text); border-color: var(--accent); font-weight: {FONT_WEIGHT_MEDIUM}; }}
        QPushButton[variant="primary"]:hover {{ background-color: var(--accent-hover); border-color: var(--accent-hover); }}
        QPushButton[variant="primary"]:focus {{ border: var(--border-thin) solid var(--accent-hover); outline: none; }}
        QPushButton[variant="ghost"] {{ background-color: transparent; border-color: transparent; color: var(--text-strong); }}
        QPushButton[variant="ghost"]:hover {{ background-color: var(--background-raised); }}
        QPushButton[variant="ghost"]:focus {{ border: var(--border-medium) solid var(--accent); outline: none; }}
        QPushButton[variant="danger"] {{ background-color: var(--btn-danger); color: #ffffff; font-weight: bold; border: 1px solid var(--btn-danger-border); }}
        QPushButton[variant="danger"]:hover {{ background-color: var(--btn-danger-hover); }}
        QPushButton[variant="danger"]:pressed {{ background-color: var(--btn-danger-border); }}
        QPushButton[variant="warning"] {{ background-color: var(--btn-warning); color: #ffffff; font-weight: bold; border: 1px solid var(--btn-warning-border); }}
        QPushButton[variant="warning"]:hover {{ background-color: var(--btn-warning-hover); }}
        QPushButton[variant="warning"]:pressed {{ background-color: var(--btn-warning-border); }}
        QTextEdit#aiChatArea {{ border: none; background-color: transparent; padding: var(--space-1) var(--space-1); color: var(--text-strong); }}
        QWidget#aiPromptDock {{ background-color: transparent; }}
        QWidget#aiInputContainer {{ background-color: var(--background-raised); border: 1px solid var(--border-weak); }}
        QTextEdit#aiPromptInput {{ border: none; border-radius: var(--space-2); background-color: transparent; padding: var(--space-1) var(--space-1); font-size: {FONT_SIZE_MD}px; color: var(--text-strong); }}
        QPushButton[class="quick-prompt-btn"] {{ padding: 3px 10px; font-size: {FONT_SIZE_XS}px; border-radius: 10px; background-color: var(--quick-prompt-bg); border: none; color: var(--quick-prompt-color); }}
        QPushButton[class="quick-prompt-btn"]:hover {{ background-color: var(--quick-prompt-hover-bg); color: var(--quick-prompt-hover-color); }}
        QWidget#OverviewPanel {{ background-color: var(--overview-bg); }}
        QSplitter#mainSplitter::handle {{ background-color: var(--splitter-color); }}
        QSplitter#mainSplitter::handle:hover {{ background-color: var(--splitter-hover); }}
    """
    qss = qss.replace("{FONT_SIZE_SM}", str(FONT_SIZE_SM))
    qss = qss.replace("{FONT_SIZE_MD}", str(FONT_SIZE_MD))
    qss = qss.replace("{FONT_SIZE_XS}", str(FONT_SIZE_XS))
    qss = qss.replace("{FONT_WEIGHT_MEDIUM}", str(FONT_WEIGHT_MEDIUM))
    return qss.replace("{{", "{").replace("}}", "}")


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

    theme_vars = _get_theme_vars(mode)
    common_qss = _get_common_qss()
    qss = f":root {{ {theme_vars} }}\n{common_qss}"
    app.setStyleSheet(_resolve_qss_vars(qss))


def input_style():
    return _resolve_inline_qss(f"""
        background-color: var(--background-inset);
        border: 1px solid var(--border-weak);
        border-radius: var(--radius-sm);
        color: var(--text-strong);
        padding: 6px 10px;
        font-size: {FONT_SIZE_MD}px;
    """)


def cell_occupied_style(color="#22c55e", is_selected=False, font_size=9):
    if is_selected:
        return _resolve_inline_qss(f"""
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
        """)
    else:
        return _resolve_inline_qss(f"""
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
        """)


def cell_empty_style(is_selected=False, font_size=8):
    if is_selected:
        return _resolve_inline_qss(f"""
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
        """)
    else:
        return _resolve_inline_qss(f"""
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
        """)


def cell_preview_add_style():
    return _resolve_inline_qss(f"""
        QPushButton {{
            background-color: rgba(34, 197, 94, 0.25);
            color: var(--text-strong);
            border: 2px solid var(--success);
            border-radius: var(--radius-xs);
            font-size: {FONT_SIZE_CELL}px;
            font-weight: 500;
            padding: 1px;
        }}
    """)


def cell_preview_takeout_style():
    return _resolve_inline_qss(f"""
        QPushButton {{
            background-color: rgba(239, 68, 68, 0.25);
            color: var(--text-strong);
            border: 2px solid var(--error);
            border-radius: var(--radius-xs);
            font-size: {FONT_SIZE_CELL}px;
            font-weight: 500;
            padding: 1px;
        }}
    """)


def cell_preview_move_source_style():
    return _resolve_inline_qss(f"""
        QPushButton {{
            background-color: rgba(56, 189, 248, 0.2);
            color: var(--text-strong);
            border: 2px solid var(--accent);
            border-radius: var(--radius-xs);
            font-size: {FONT_SIZE_CELL}px;
            font-weight: 500;
            padding: 1px;
        }}
    """)


def cell_preview_move_target_style():
    return _resolve_inline_qss(f"""
        QPushButton {{
            background-color: rgba(56, 189, 248, 0.35);
            color: var(--text-strong);
            border: 2px solid var(--accent);
            border-radius: var(--radius-xs);
            font-size: {FONT_SIZE_CELL}px;
            font-weight: 500;
            padding: 1px;
        }}
    """)


def chat_code_block_style(is_dark=True):
    if is_dark:
        return f"""
            background-color: #1a1a1a;
            border: 1px solid rgba(255,255,255,0.08);
            border-radius: 6px;
            padding: 12px;
            font-family: "IBM Plex Mono", "Consolas", "Monaco", monospace;
            font-size: {FONT_SIZE_MD}px;
            color: #e8e8e8;
        """
    else:
        return f"""
            background-color: #f5f5f5;
            border: 1px solid rgba(0,0,0,0.08);
            border-radius: 6px;
            padding: 12px;
            font-family: "IBM Plex Mono", "Consolas", "Monaco", monospace;
            font-size: {FONT_SIZE_MD}px;
            color: #1e1e1e;
        """


def chat_inline_code_style(is_dark=True):
    if is_dark:
        return "background-color: rgba(255,255,255,0.1); padding: 2px 6px; border-radius: 4px; font-family: monospace;"
    else:
        return "background-color: rgba(0,0,0,0.06); padding: 2px 6px; border-radius: 4px; font-family: monospace;"


def chat_collapsible_header_style(is_dark=True):
    if is_dark:
        return f"""
            QPushButton {{
                background-color: #242424;
                border: 1px solid rgba(255,255,255,0.08);
                border-radius: 6px;
                padding: 8px 12px;
                text-align: left;
                font-size: {FONT_SIZE_MD}px;
                color: #e8e8e8;
            }}
            QPushButton:hover {{
                background-color: #2d2d2d;
                border-color: rgba(255,255,255,0.12);
            }}
            QPushButton:checked {{
                border-bottom-left-radius: 0;
                border-bottom-right-radius: 0;
            }}
        """
    else:
        return f"""
            QPushButton {{
                background-color: #f5f5f5;
                border: 1px solid rgba(0,0,0,0.08);
                border-radius: 6px;
                padding: 8px 12px;
                text-align: left;
                font-size: {FONT_SIZE_MD}px;
                color: #1e1e1e;
            }}
            QPushButton:hover {{
                background-color: #eaeaea;
                border-color: rgba(0,0,0,0.12);
            }}
            QPushButton:checked {{
                border-bottom-left-radius: 0;
                border-bottom-right-radius: 0;
            }}
        """


def chat_collapsible_content_style(is_dark=True):
    if is_dark:
        return f"""
            background-color: #1f1f1f;
            border: 1px solid rgba(255,255,255,0.08);
            border-top: none;
            border-bottom-left-radius: 6px;
            border-bottom-right-radius: 6px;
            padding: 8px 12px;
            font-family: "IBM Plex Mono", monospace;
            font-size: {FONT_SIZE_SM}px;
            color: #888888;
        """
    else:
        return f"""
            background-color: #fafafa;
            border: 1px solid rgba(0,0,0,0.08);
            border-top: none;
            border-bottom-left-radius: 6px;
            border-bottom-right-radius: 6px;
            padding: 8px 12px;
            font-family: "IBM Plex Mono", monospace;
            font-size: {FONT_SIZE_SM}px;
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

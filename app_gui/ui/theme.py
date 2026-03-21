import os
import re
import sys
from functools import lru_cache

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
    # Prioritize fonts with thicker strokes for better readability
    os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts", "simhei.ttf"),      # SimHei (黑体) - thick strokes
    os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts", "msyhbd.ttc"),      # Microsoft YaHei Bold
    os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts", "msyh.ttc"),        # Microsoft YaHei Regular
    os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts", "simsun.ttc"),      # SimSun
    "/usr/share/fonts/google-noto-cjk/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/noto-cjk/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/google-noto-cjk/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/google-droid/DroidSansFallback.ttf",
    "/usr/share/fonts/truetype/droid/DroidSansFallback.ttf",
    "/usr/share/fonts/wqy-microhei/wqy-microhei.ttc",
]

_MONO_FONT_FAMILIES = [
    "Cascadia Mono",
    "Consolas",
    "JetBrains Mono",
    "SF Mono",
    "Menlo",
    "Monaco",
    "Source Code Pro",
    "DejaVu Sans Mono",
    "Noto Sans Mono CJK SC",
    "Sarasa Mono SC",
    # CJK-safe fallbacks when no true mono CJK font is available.
    "Microsoft YaHei UI",
    "Microsoft YaHei",
    "SimHei",
    "SimSun",
]

MONO_FONT_CSS_FAMILY = ", ".join([f"'{name}'" for name in _MONO_FONT_FAMILIES] + ["monospace"])


@lru_cache(maxsize=1)
def _available_font_families():
    return set(QFontDatabase.families())


def _preferred_ui_font_families():
    if sys.platform == "darwin":
        return [
            "SF Pro Text",
            "SF Pro Display",
            "Helvetica Neue",
            "Arial",
            "Inter",
        ]
    if sys.platform.startswith("win"):
        return [
            "Segoe UI Variable",
            "Segoe UI",
            "Arial",
            "Inter",
        ]
    return [
        "Inter",
        "Noto Sans",
        "Cantarell",
        "Ubuntu",
        "DejaVu Sans",
        "Arial",
    ]


def _pick_installed_font(candidates):
    available = _available_font_families()
    for family in candidates:
        if family in available:
            return family
    return None


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

    primary_family = _pick_installed_font(_preferred_ui_font_families())
    font = QFont(primary_family) if primary_family else QFont(app.font())
    font.setPointSize(FONT_POINT_SIZE)
    fallback_candidates = list(_preferred_ui_font_families()) + [
        "Roboto",
        "Cantarell",
        "DejaVu Sans",
    ]
    if loaded_family:
        fallback_candidates.append(loaded_family)
    fallback_candidates.extend(["Microsoft YaHei", "Microsoft YaHei UI", "SimHei", "SimSun"])

    family_chain = []
    seen = set()
    for family in [primary_family] + fallback_candidates:
        if not family or family in seen:
            continue
        seen.add(family)
        if family == loaded_family or family in _available_font_families():
            family_chain.append(family)
    if family_chain:
        font.setFamilies(family_chain)
    app.setFont(font)


def build_mono_font(point_size=FONT_SIZE_MONO):
    """Return a cross-platform monospace-ish font without Fixedsys fallback."""
    font = QFont(_MONO_FONT_FAMILIES[0])
    font.setPointSize(int(point_size))
    font.setFamilies(list(_MONO_FONT_FAMILIES))
    font.setFixedPitch(True)
    return font


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


_TOKEN_DECL_PATTERN = re.compile(r"--([A-Za-z0-9_-]+)\s*:\s*([^;]+);")
_TOKEN_REF_PATTERN = re.compile(r"var\(--([A-Za-z0-9_-]+)\)")


def get_theme_tokens(mode=None):
    """Return resolved theme tokens as a ``dict`` for the given mode."""
    active_mode = mode or _current_theme_mode()
    raw = _get_theme_vars(active_mode)

    tokens = {}
    for match in _TOKEN_DECL_PATTERN.finditer(raw):
        key = match.group(1).strip()
        value = match.group(2).strip()
        if key and value:
            tokens[key] = value

    # Resolve nested refs like var(--background-raised)
    for _ in range(6):
        changed = False
        for key, value in list(tokens.items()):
            resolved = _TOKEN_REF_PATTERN.sub(
                lambda m: tokens.get(m.group(1), m.group(0)),
                str(value),
            )
            if resolved != value:
                tokens[key] = resolved
                changed = True
        if not changed:
            break

    return tokens


def resolve_theme_token(token_name, mode=None, fallback=""):
    """Resolve a single theme token like ``'status-success'`` or ``'--status-success'``."""
    key = str(token_name or "").strip()
    if key.startswith("--"):
        key = key[2:]
    if not key:
        return str(fallback)
    return str(get_theme_tokens(mode).get(key, fallback))


def _coerce_qcolor(value):
    if isinstance(value, QColor):
        color = QColor(value)
    else:
        color = QColor(str(value or ""))
    return color if color.isValid() else QColor()


def _srgb_channel_to_linear(channel):
    c = float(channel)
    if c <= 0.04045:
        return c / 12.92
    return ((c + 0.055) / 1.055) ** 2.4


def _relative_luminance(color):
    if not isinstance(color, QColor) or not color.isValid():
        return 0.0
    r = _srgb_channel_to_linear(color.redF())
    g = _srgb_channel_to_linear(color.greenF())
    b = _srgb_channel_to_linear(color.blueF())
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast_ratio(lhs_luminance, rhs_luminance):
    lighter = max(float(lhs_luminance), float(rhs_luminance))
    darker = min(float(lhs_luminance), float(rhs_luminance))
    return (lighter + 0.05) / (darker + 0.05)


def pick_contrasting_text_color(background, light="#ffffff", dark="#0f172a"):
    """Pick a readable text color for a background.

    Returns either ``light`` or ``dark`` (normalized as hex) based on WCAG
    contrast ratio against ``background``.
    """
    bg_color = _coerce_qcolor(background)
    if not bg_color.isValid():
        return str(QColor("#0f172a").name())

    light_color = _coerce_qcolor(light)
    if not light_color.isValid():
        light_color = QColor("#ffffff")

    dark_color = _coerce_qcolor(dark)
    if not dark_color.isValid():
        dark_color = QColor("#0f172a")

    bg_lum = _relative_luminance(bg_color)
    light_ratio = _contrast_ratio(bg_lum, _relative_luminance(light_color))
    dark_ratio = _contrast_ratio(bg_lum, _relative_luminance(dark_color))
    winner = light_color if light_ratio >= dark_ratio else dark_color
    return str(winner.name())


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
            --status-warning-bg: rgba(245,158,11,0.12);
            --status-error-bg: rgba(220,53,69,0.12);
            --status-info-bg: rgba(43,127,229,0.12);
            --status-muted-bg: rgba(100,116,139,0.10);
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
            --table-bg: #ffffff;
            --table-alt-bg: #f8fbff;
            --table-header-bg: #f3f7fd;
            --table-header-text: #41576f;
            --table-border-soft: #dde5ef;
            --table-hover-bg: rgba(43,127,229,0.10);
            --table-selection-bg: #e0f2fe;
            --cell-border-default: #e0e0e0;
            --cell-selected-border: var(--accent);
            --cell-empty-bg: #eef3f8;
            --cell-empty-selected-bg: #deebf8;
            --cell-empty-text: #6b7f95;
            --cell-empty-selected-text: #34506d;
            --cell-empty-fresh-bg: #ffffff;
            --cell-empty-fresh-border: #dce3ed;
            --cell-empty-fresh-text: #7a8796;
            --cell-empty-fresh-selected-bg: #f4f8ff;
            --cell-empty-fresh-selected-text: #3f5d7d;
            --cell-occupied-hairline: rgba(0,0,0,0.08);
            --groupbox-bg: #ffffff;
            --groupbox-border: #e3e8ef;
            --scrollbar-handle: rgba(0,0,0,0.15);
            --scrollbar-handle-hover: rgba(0,0,0,0.25);
            --splitter-color: rgba(15,23,42,0.12);
            --splitter-hover: rgba(43,127,229,0.35);
            --overview-bg: #f5f9fd;
            --tooltip-bg: #ffffff;
            --tooltip-color: #1e1e1e;
            --tooltip-border: rgba(15,23,42,0.16);
            --surface-border-subtle: rgba(15,23,42,0.08);
            --surface-border-strong: rgba(15,23,42,0.16);
            --input-focus-bg: var(--background-raised);
            --primary-btn-text: #ffffff;
            --toggle-checked-text: #ffffff;
            --toggle-unchecked-text: #ffffff;
            --quick-prompt-bg: rgba(43,127,229,0.10);
            --quick-prompt-color: #34506d;
            --quick-prompt-hover-bg: rgba(43,127,229,0.18);
            --quick-prompt-hover-color: #0f172a;
            --radio-bg: var(--background-raised);
            --chat-panel-bg: #f5f5f5;
            --chat-panel-header-bg: #f5f5f5;
            --chat-panel-content-bg: #fafafa;
            --chat-panel-border: rgba(0,0,0,0.08);
            --chat-panel-border-hover: rgba(0,0,0,0.12);
            --chat-inline-code-bg: rgba(0,0,0,0.06);
            --chat-code-bg: #f5f5f5;
            --chat-code-border: rgba(0,0,0,0.08);
            --chat-code-text: #1e1e1e;
            --chat-muted-text: #646464;
            --chat-link: #2563eb;
            --chat-role-agent: #0284c7;
            --chat-role-you: #4d7c0f;
            --chat-role-tool: #b45309;
            --chat-role-system: #c2410c;
            --chat-role-muted: #64748b;
            --chat-role-link: #2563eb;
            --preview-add-bg: rgba(34,197,94,0.25);
            --preview-takeout-bg: rgba(239,68,68,0.25);
            --preview-move-source-bg: rgba(56,189,248,0.20);
            --preview-move-target-bg: rgba(56,189,248,0.35);
            --icon-default: #000000;
            --icon-on-primary: #ffffff;
            --icon-on-danger: #ffffff;
            --sheet-bg: #ffffff;
            --sheet-text-primary: #1f2937;
            --sheet-text-muted: #6b7280;
            --sheet-border: #e5e7eb;
            --sheet-section-bg: #f9fafb;
            --sheet-tip-bg: #fef3c7;
            --sheet-tip-border: #f59e0b;
            --sheet-tip-text: #78350f;
            --sheet-tip-title: #92400e;
            --sheet-grid-bg: #0f1a2a;
            --sheet-grid-border: #36506d;
            --sheet-grid-text: #c6dbf3;
            --sheet-grid-empty-bg: #1a2a40;
            --sheet-grid-empty-text: #86a0bb;
            --sheet-grid-overlay-bg: rgba(0,0,0,0.7);
            --sheet-chip-takeout-bg: #fef3c7;
            --sheet-chip-move-bg: #dbeafe;
            --sheet-chip-add-bg: #ede9fe;
            --sheet-chip-edit-bg: #cffafe;
            --sheet-chip-rollback-bg: #f3f4f6;
            --sheet-action-takeout: #f59e0b;
            --sheet-action-move: #3b82f6;
            --sheet-action-add: #8b5cf6;
            --sheet-action-edit: #06b6d4;
            --sheet-action-rollback: #6b7280;
            --marker-add: #16a34a;
            --marker-takeout: #dc2626;
            --marker-edit: #0891b2;
            --marker-move: #2b7fe5;
            --badge-bg: rgba(0,0,0,160);
            --indicator-active: var(--accent);
            --watermark-tint: #94a3b8;
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
            --status-warning-bg: rgba(245,158,11,0.16);
            --status-error-bg: rgba(239,68,68,0.16);
            --status-info-bg: rgba(99,179,255,0.18);
            --status-muted-bg: rgba(148,163,184,0.14);
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
            --table-bg: #1f2f43;
            --table-alt-bg: #25384e;
            --table-header-bg: #2a3f56;
            --table-header-text: #d5e5f6;
            --table-border-soft: rgba(230,241,255,0.22);
            --table-hover-bg: rgba(99,179,255,0.16);
            --table-selection-bg: rgba(125,211,252,0.24);
            --cell-border-default: rgba(230,241,255,0.18);
            --cell-selected-border: var(--accent);
            --cell-empty-bg: #1a2a40;
            --cell-empty-selected-bg: #223956;
            --cell-empty-text: #86a0bb;
            --cell-empty-selected-text: #c6dbf3;
            --cell-empty-fresh-bg: #243448;
            --cell-empty-fresh-border: rgba(230,241,255,0.22);
            --cell-empty-fresh-text: #bdd0e3;
            --cell-empty-fresh-selected-bg: #2f465f;
            --cell-empty-fresh-selected-text: #e3eef9;
            --cell-occupied-hairline: rgba(255,255,255,0.10);
            --groupbox-bg: #1f2f43;
            --groupbox-border: rgba(230,241,255,0.20);
            --scrollbar-handle: rgba(255,255,255,0.1);
            --scrollbar-handle-hover: rgba(255,255,255,0.15);
            --splitter-color: rgba(159,179,200,0.18);
            --splitter-hover: rgba(99,179,255,0.42);
            --overview-bg: #112033;
            --tooltip-bg: #e8e8e8;
            --tooltip-color: #1a1a1a;
            --tooltip-border: rgba(255,255,255,0.18);
            --surface-border-subtle: rgba(255,255,255,0.08);
            --surface-border-strong: rgba(255,255,255,0.16);
            --input-focus-bg: var(--background-base);
            --primary-btn-text: #ffffff;
            --toggle-checked-text: #000000;
            --toggle-unchecked-text: #ffffff;
            --quick-prompt-bg: rgba(99,179,255,0.16);
            --quick-prompt-color: #a9c6e3;
            --quick-prompt-hover-bg: rgba(99,179,255,0.24);
            --quick-prompt-hover-color: #e6f1ff;
            --radio-bg: var(--background-inset);
            --chat-panel-bg: #1f1f1f;
            --chat-panel-header-bg: #242424;
            --chat-panel-content-bg: #1f1f1f;
            --chat-panel-border: rgba(255,255,255,0.08);
            --chat-panel-border-hover: rgba(255,255,255,0.12);
            --chat-inline-code-bg: rgba(255,255,255,0.10);
            --chat-code-bg: #1a1a1a;
            --chat-code-border: rgba(255,255,255,0.08);
            --chat-code-text: #e8e8e8;
            --chat-muted-text: #888888;
            --chat-link: #38bdf8;
            --chat-role-agent: #38bdf8;
            --chat-role-you: #a3e635;
            --chat-role-tool: #f59e0b;
            --chat-role-system: #f97316;
            --chat-role-muted: #9ca3af;
            --chat-role-link: #60a5fa;
            --preview-add-bg: rgba(34,197,94,0.25);
            --preview-takeout-bg: rgba(239,68,68,0.25);
            --preview-move-source-bg: rgba(56,189,248,0.20);
            --preview-move-target-bg: rgba(56,189,248,0.35);
            --icon-default: #ffffff;
            --icon-on-primary: #ffffff;
            --icon-on-danger: #ffffff;
            --sheet-bg: #0f1724;
            --sheet-text-primary: #e6f1ff;
            --sheet-text-muted: #9fb3c8;
            --sheet-border: #36506d;
            --sheet-section-bg: #132033;
            --sheet-tip-bg: rgba(245,158,11,0.16);
            --sheet-tip-border: #f59e0b;
            --sheet-tip-text: #fcd34d;
            --sheet-tip-title: #fbbf24;
            --sheet-grid-bg: #0f1a2a;
            --sheet-grid-border: #36506d;
            --sheet-grid-text: #c6dbf3;
            --sheet-grid-empty-bg: #1a2a40;
            --sheet-grid-empty-text: #86a0bb;
            --sheet-grid-overlay-bg: rgba(0,0,0,0.7);
            --sheet-chip-takeout-bg: rgba(245,158,11,0.22);
            --sheet-chip-move-bg: rgba(59,130,246,0.22);
            --sheet-chip-add-bg: rgba(139,92,246,0.22);
            --sheet-chip-edit-bg: rgba(6,182,212,0.22);
            --sheet-chip-rollback-bg: rgba(148,163,184,0.22);
            --sheet-action-takeout: #f59e0b;
            --sheet-action-move: #63b3ff;
            --sheet-action-add: #a78bfa;
            --sheet-action-edit: #22d3ee;
            --sheet-action-rollback: #94a3b8;
            --marker-add: #22c55e;
            --marker-takeout: #ef4444;
            --marker-edit: #06b6d4;
            --marker-move: #63b3ff;
            --badge-bg: rgba(0,0,0,180);
            --indicator-active: var(--accent);
            --watermark-tint: #94a3b8;
        """


def _get_common_qss():
    """Return common QSS styles that work for both themes."""
    qss = """
        :root {
            /* Border radius */
            --radius-xs: 3px;
            --radius-sm: 4px;
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
            --scrollbar-width: 4px;
            --scrollbar-handle-min: 20px;
            --scrollbar-handle-radius: 2px;
            --splitter-width: 6px;
            --splitter-radius: 2px;
        }
        QToolTip { color: var(--tooltip-color); background-color: var(--tooltip-bg); border: 1px solid var(--tooltip-border); border-radius: var(--radius-sm); padding: var(--space-1) var(--space-2); font-size: {FONT_SIZE_SM}px; }
        QGroupBox {{ background-color: var(--groupbox-bg); border: var(--border-thin) solid var(--groupbox-border); border-radius: var(--radius-lg); margin-top: var(--space-3); font-weight: {FONT_WEIGHT_MEDIUM}; color: var(--text-weak); padding-top: var(--space-2); }}
        QGroupBox::title {{ subcontrol-origin: margin; subcontrol-position: top left; padding: 0 var(--space-2); padding-left: var(--space-2); left: var(--space-2); color: var(--text-weak); font-size: {FONT_SIZE_MD}px; border-left: 2px solid var(--accent); }}
        QTableWidget {{ gridline-color: var(--table-border-soft); background-color: var(--table-bg); alternate-background-color: var(--table-alt-bg); selection-background-color: var(--table-selection-bg); border: var(--border-thin) solid var(--table-border-soft); border-radius: var(--radius-md); }}
        QTableWidget::item {{ padding: 6px var(--space-2); border: none; }}
        QTableWidget::item:hover {{ background-color: var(--table-hover-bg); }}
        QTableWidget::item:selected {{ background-color: var(--table-selection-bg); color: var(--text-strong); }}
        QHeaderView::section {{ background-color: var(--table-header-bg); color: var(--table-header-text); padding: 7px var(--space-2); border: none; border-bottom: var(--border-thin) solid var(--table-border-soft); border-right: var(--border-thin) solid var(--table-border-soft); font-weight: 500; font-size: {FONT_SIZE_SM}px; }}
        QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QDateEdit {{ min-height: var(--input-height); max-height: var(--input-height); }}
        QLineEdit, QComboBox {{ padding: 0 var(--space-2); }}
        QSpinBox, QDoubleSpinBox, QDateEdit {{ padding: 0; margin: 0; }}
        QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QDateEdit, QTextEdit, QTextBrowser, QPlainTextEdit {{ background-color: var(--input-bg); border: var(--border-thin) solid var(--input-border); border-radius: var(--radius-sm); color: var(--input-text); selection-background-color: var(--accent-muted); selection-color: var(--text-strong); }}
        QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus, QDateEdit:focus, QTextEdit:focus, QTextBrowser:focus, QPlainTextEdit:focus {{ border: var(--border-medium) solid var(--input-border-focus); background-color: var(--input-focus-bg); }}
        QLineEdit[readOnly="true"], QTextEdit[readOnly="true"], QTextBrowser[readOnly="true"], QPlainTextEdit[readOnly="true"] {{ background-color: var(--display-bg); border-color: transparent; color: var(--display-text); }}
        QPushButton {{ background-color: var(--button-background); border: var(--border-thin) solid var(--button-border); border-radius: var(--radius-xs); color: var(--text-strong); padding: 1px var(--space-2); font-weight: {FONT_WEIGHT_MEDIUM}; font-size: {FONT_SIZE_MD}px; }}
        QPushButton:hover {{ background-color: var(--button-hover); border-color: var(--button-border); }}
        QPushButton:focus {{ border: var(--border-thin) solid var(--accent); outline: none; }}
        QPushButton:pressed {{ background-color: var(--button-pressed); }}
        QPushButton:disabled {{ background-color: var(--background-strong); color: var(--text-muted); border-color: transparent; opacity: 0.6; }}
        QWidget#overviewViewToggle {{ background-color: transparent; border: none; border-radius: 0; padding: 0; }}
        QWidget#overviewViewToggle QPushButton[segmented] {{ background-color: transparent; border: none; border-radius: 0; color: var(--toggle-unchecked-text); padding: var(--space-1) var(--space-2); margin: 0; }}
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
        QLabel#operationsPlanFeedback[level="warning"] {{ color: var(--status-warning); background: var(--status-warning-bg); }}
        QLabel#operationsPlanFeedback[level="error"] {{ color: var(--status-error); background: var(--status-error-bg); }}
        QLabel#aiMigrationModeBanner, QLabel#operationsMigrationModeBanner {{
            color: var(--status-warning);
            background: var(--status-warning-bg);
            border: 1px solid var(--status-warning);
            border-radius: var(--radius-sm);
            padding: 6px 10px;
            font-weight: {FONT_WEIGHT_SEMIBOLD};
        }}
        QLabel#mainMigrationModeBadge {{
            color: var(--status-warning);
            background: var(--status-warning-bg);
            border: 1px solid var(--status-warning);
            border-radius: var(--radius-xs);
            padding: 2px 8px;
            font-size: {FONT_SIZE_XS}px;
            font-weight: {FONT_WEIGHT_BOLD};
        }}
        QPushButton#mainToolbarIconBtn {{
            min-width: 28px;
            max-width: 28px;
            min-height: 28px;
            max-height: 28px;
            padding: 0;
            border: var(--border-thin) solid transparent;
            border-radius: var(--radius-xs);
            background: transparent;
        }}
        QPushButton#mainToolbarIconBtn:hover {{
            background: var(--background-hover);
            border-color: var(--border-weak);
        }}
        QPushButton#mainToolbarIconBtn:focus {{
            border-color: var(--accent);
        }}
        QPushButton#mainToolbarIconBtn:pressed {{
            background: var(--background-raised);
            border-color: var(--border-strong);
        }}
        QLabel#mainMigrationStatusIndicator {{
            color: var(--status-warning);
            background: var(--status-warning-bg);
            border: 1px solid var(--status-warning);
            border-radius: var(--radius-xs);
            padding: 0 8px;
            font-size: {FONT_SIZE_XS}px;
            font-weight: {FONT_WEIGHT_SEMIBOLD};
        }}
        QWidget#operationsMigrationLockOverlay {{
            background-color: var(--sheet-grid-overlay-bg);
            border: 1px solid var(--status-warning);
            border-radius: var(--radius-sm);
        }}
        QLabel#operationsMigrationLockOverlayLabel {{
            color: var(--status-warning);
            background: var(--status-warning-bg);
            border: 1px solid var(--status-warning);
            border-radius: var(--radius-sm);
            padding: 8px 12px;
            font-weight: {FONT_WEIGHT_SEMIBOLD};
        }}
        QLabel[role="statusWarning"] {{ color: var(--status-warning); }}
        QLabel[role="readonlyField"] {{ background: var(--display-bg); border: none; color: var(--display-text); padding: 2px 4px; }}
        QLineEdit[role="contextEditable"][readOnly="true"] {{ background: var(--display-bg); border: none; color: var(--display-text); padding: 2px 4px; }}
        QLineEdit[role="contextEditable"][readOnly="false"] {{ background: var(--input-bg); border: var(--border-thin) solid var(--input-border-focus); color: var(--input-text); padding: 2px 4px; }}
        QPlainTextEdit[role="contextEditable"][readOnly="true"] {{ background: var(--display-bg); border: none; color: var(--display-text); padding: 2px 4px; }}
        QPlainTextEdit[role="contextEditable"][readOnly="false"] {{ background: var(--input-bg); border: var(--border-thin) solid var(--input-border-focus); color: var(--input-text); padding: 2px 4px; }}
        QPushButton#inlineLockBtn {{ border: none; padding: 0; font-size: {FONT_SIZE_SM}px; background: transparent; }}
        QPushButton#inlineConfirmBtn {{ border: none; padding: 0; font-size: {FONT_SIZE_LG}px; font-weight: {FONT_WEIGHT_BOLD}; color: var(--status-success); background: transparent; }}
        QLabel[role="mutedInline"] {{ color: var(--text-muted); }}
        QWidget#overviewStatCard {{ background-color: var(--background-inset); border: var(--border-thin) solid var(--border-weak); border-radius: var(--radius-md); margin-top: 8px; padding-top: 8px; }}
        QWidget#overviewStatCard QLabel#overviewStatValue {{ color: var(--text-strong); font-weight: {FONT_WEIGHT_MEDIUM}; font-size: {FONT_SIZE_XL}px; }}
        QPushButton#overviewIconButton {{ border: none; background: transparent; }}
        QPushButton#overviewFloatingActionBtn {{
            border: none;
            background: transparent;
            padding: 0;
        }}
        QPushButton#overviewFloatingActionBtn:hover {{ background: transparent; }}
        QLabel#overviewZoomLabel {{ font-size: {FONT_SIZE_XS}px; }}
        QLabel#overviewZoomSeparator {{ color: var(--border-weak); margin: 0 4px; }}
        QLabel#overviewHoverHint {{ color: var(--text-weak); font-weight: {FONT_WEIGHT_MEDIUM}; }}
        QLabel#overviewHoverHint[state="warning"] {{ color: var(--warning); padding: 8px; background-color: var(--status-warning-bg); border-radius: var(--radius-xs); }}
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
        QPushButton#aiRunActionBtn[migrationAttention="true"] {{
            border: 2px solid var(--status-warning);
            background-color: var(--btn-warning);
            color: #ffffff;
            font-weight: {FONT_WEIGHT_BOLD};
        }}
        QPushButton#aiRunActionBtn[migrationAttention="true"]:hover {{
            background-color: var(--btn-warning-hover);
        }}
        QTextEdit#aiChatArea {{ border: none; background-color: transparent; padding: var(--space-1) var(--space-1); color: var(--text-strong); }}
        QWidget#aiPromptDock {{ background-color: transparent; }}
        QWidget#aiInputContainer {{ background-color: var(--background-raised); border: 1px solid var(--border-weak); }}
        QTextEdit#aiPromptInput {{ border: none; border-radius: var(--space-2); background-color: transparent; padding: var(--space-1) var(--space-1); font-size: {FONT_SIZE_MD}px; color: var(--text-strong); }}
        QTextEdit#exportTaskSourcePreview[state="empty"] {{ color: var(--text-muted); }}
        QTextEdit#exportTaskSourcePreview[state="filled"] {{ color: var(--text-strong); }}
        QPushButton#aiModelSwitchBtn {{
            min-width: 18px;
            max-width: 18px;
            min-height: 18px;
            max-height: 18px;
            padding: 0;
            border: none;
            border-radius: 0;
            background-color: transparent;
            color: var(--text-strong);
            font-size: {FONT_SIZE_SM}px;
            font-weight: {FONT_WEIGHT_MEDIUM};
        }}
        QPushButton#aiModelSwitchBtn:hover {{
            background-color: transparent;
            color: var(--accent);
        }}
        QPushButton#aiModelSwitchBtn:focus {{
            border: none;
            outline: none;
        }}
        QPushButton#aiModelSwitchBtn:disabled {{
            color: var(--text-muted);
            opacity: 0.6;
        }}
        QPushButton[class="quick-prompt-btn"] {{ padding: 3px 10px; font-size: {FONT_SIZE_XS}px; border-radius: 10px; background-color: var(--quick-prompt-bg); border: none; color: var(--quick-prompt-color); }}
        QPushButton[class="quick-prompt-btn"]:hover {{ background-color: var(--quick-prompt-hover-bg); color: var(--quick-prompt-hover-color); }}
        QScrollBar:vertical {{ width: var(--scrollbar-width); margin: 0; background: transparent; border: none; }}
        QScrollBar:horizontal {{ height: var(--scrollbar-width); margin: 0; background: transparent; border: none; }}
        QScrollBar::handle:vertical {{ min-height: var(--scrollbar-handle-min); background: var(--scrollbar-handle); border-radius: var(--scrollbar-handle-radius); }}
        QScrollBar::handle:horizontal {{ min-width: var(--scrollbar-handle-min); background: var(--scrollbar-handle); border-radius: var(--scrollbar-handle-radius); }}
        QScrollBar::handle:vertical:hover, QScrollBar::handle:horizontal:hover {{ background: var(--scrollbar-handle-hover); }}
        QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; border: none; width: 0; height: 0; }}
        QTableCornerButton::section {{ background: var(--table-header-bg); border: none; border-bottom: var(--border-thin) solid var(--table-border-soft); border-right: var(--border-thin) solid var(--table-border-soft); }}
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
    _cell_occupied_style_cached.cache_clear()
    _cell_empty_style_cached.cache_clear()


def cell_occupied_style(color="#22c55e", is_selected=False, font_size=None):
    """Return QSS for an occupied cell.

    *font_size* is accepted for API compatibility but ignored — callers
    should set the pixel size via ``QFont.setPixelSize()`` instead so that
    zoom-level changes do not invalidate cached stylesheets.
    """
    mode = _current_theme_mode()
    return _cell_occupied_style_cached(color, is_selected, mode)


def _tint_color(hex_color, mode):
    """Blend a color with the theme background to produce a soft tint.

    Returns (tint_hex, text_hex) suitable for cell backgrounds.
    """
    from PySide6.QtGui import QColor as _QC

    base = _QC(hex_color)
    if not base.isValid():
        base = _QC("#8A949B")

    if mode == "dark":
        # Blend with dark background at ~25% opacity
        bg = _QC("#1e293b")
        alpha = 0.25
    else:
        # Blend with white background at ~18% opacity
        bg = _QC("#ffffff")
        alpha = 0.18

    r = int(bg.red() * (1 - alpha) + base.red() * alpha)
    g = int(bg.green() * (1 - alpha) + base.green() * alpha)
    b = int(bg.blue() * (1 - alpha) + base.blue() * alpha)
    tint = _QC(r, g, b)
    text = pick_contrasting_text_color(tint.name())
    return tint.name(), text


@lru_cache(maxsize=128)
def _cell_occupied_style_cached(color, is_selected, mode):
    tint_bg, text_color = _tint_color(color, mode)
    if is_selected:
        return _resolve_inline_qss(f"""
            QPushButton {{
                background-color: {tint_bg};
                color: {text_color};
                border: 1px solid var(--cell-occupied-hairline);
                border-radius: 3px;
                font-weight: 500;
                padding: 1px;

            }}
            QPushButton:hover {{
                border: 1px solid var(--cell-occupied-hairline);
            }}
        """, mode=mode)
    return _resolve_inline_qss(f"""
        QPushButton {{
            background-color: {tint_bg};
            color: {text_color};
            border: 1px solid var(--cell-occupied-hairline);
            border-radius: 3px;
            font-weight: 500;
            padding: 1px;

        }}
        QPushButton:hover {{
            border: 2px solid var(--accent);
        }}
    """, mode=mode)


def cell_empty_style(is_selected=False, font_size=None):
    """Return QSS for an empty cell.

    *font_size* is accepted for API compatibility but ignored.
    """
    mode = _current_theme_mode()
    return _cell_empty_style_cached(is_selected, mode)


@lru_cache(maxsize=32)
def _cell_empty_style_cached(is_selected, mode):
    if is_selected:
        return _resolve_inline_qss("""
            QPushButton {
                background-color: var(--cell-empty-fresh-selected-bg);
                color: var(--cell-empty-fresh-selected-text);
                border: 1px solid transparent;
                border-radius: 3px;
                padding: 1px;

            }
            QPushButton:hover {
                border: 1px solid transparent;
                background-color: var(--cell-empty-fresh-selected-bg);
                color: var(--cell-empty-fresh-selected-text);
            }
        """, mode=mode)
    return _resolve_inline_qss("""
        QPushButton {
            background-color: var(--cell-empty-fresh-bg);
            color: var(--cell-empty-fresh-text);
            border: 1px solid var(--cell-empty-fresh-border);
            border-radius: 3px;
            padding: 1px;

        }
        QPushButton:hover {
            border: 1px solid var(--cell-empty-fresh-border);
            background-color: var(--background-raised);
            color: var(--text-weak);
        }
    """, mode=mode)


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

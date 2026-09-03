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
FONT_SIZE_MD = 13        # Default size for buttons, inputs, titles
FONT_SIZE_LG = 16        # Large titles
FONT_SIZE_XL = 20        # Extra large (big numbers)
FONT_SIZE_XXL = 24       # Huge text (rarely used)

FONT_POINT_SIZE = 10     # QApplication global font point size (compact)

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
    # Prefer modern, hinted UI faces (YaHei) over legacy SimHei/SimSun so CJK
    # glyphs match the Segoe UI Latin glyphs in weight and rhythm.
    os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts", "msyh.ttc"),        # Microsoft YaHei Regular
    os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts", "msyhbd.ttc"),      # Microsoft YaHei Bold
    os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts", "simhei.ttf"),      # SimHei (黑体) - legacy fallback
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
    # Installed CJK UI faces come before the file-loaded family so a loaded
    # SimHei never shadows YaHei for CJK glyph fallback.
    fallback_candidates.extend(["Microsoft YaHei UI", "Microsoft YaHei", "PingFang SC", "Hiragino Sans GB", "Noto Sans CJK SC"])
    if loaded_family:
        fallback_candidates.append(loaded_family)
    fallback_candidates.extend(["SimHei", "SimSun"])

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


_QSS_ICON_CACHE_DIR = None


def _qss_icon_url(name, color):
    """Return a QSS ``url(...)`` for a Lucide icon tinted with *color*.

    Qt style sheets cannot recolor SVGs, so a tinted copy is written once per
    (icon, color) pair into a per-user cache directory.
    """
    global _QSS_ICON_CACHE_DIR
    import tempfile

    try:
        from app_gui.ui.icons import ICONS_DIR
    except Exception:
        return "none"
    src = os.path.join(ICONS_DIR, f"{name}.svg")
    if not os.path.isfile(src):
        return "none"
    if _QSS_ICON_CACHE_DIR is None:
        _QSS_ICON_CACHE_DIR = os.path.join(tempfile.gettempdir(), "snowfox-qss-icons")
    try:
        os.makedirs(_QSS_ICON_CACHE_DIR, exist_ok=True)
        safe_color = re.sub(r"[^0-9a-zA-Z]", "", str(color))
        dst = os.path.join(_QSS_ICON_CACHE_DIR, f"{name}-{safe_color}.svg")
        if not os.path.isfile(dst):
            with open(src, "r", encoding="utf-8") as fh:
                svg = fh.read()
            svg = svg.replace('stroke="currentColor"', f'stroke="{color}"')
            with open(dst, "w", encoding="utf-8") as fh:
                fh.write(svg)
    except Exception:
        return "none"
    return 'url("' + dst.replace("\\", "/") + '")'


def _get_icon_vars(mode):
    """Theme tokens for control glyphs (combo arrows, spin buttons, check marks)."""
    tokens = get_theme_tokens(mode)
    muted = tokens.get("text-muted", "#64748b")
    on_primary = tokens.get("primary-btn-text", "#ffffff")
    return (
        f"--icon-chevron-down: {_qss_icon_url('chevron-down', muted)};\n"
        f"--icon-chevron-up: {_qss_icon_url('chevron-up', muted)};\n"
        f"--icon-check-on-primary: {_qss_icon_url('check', on_primary)};\n"
    )


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


def _qss_assets_dir():
    """Directory holding the bundled .qss files (dev tree or PyInstaller bundle)."""
    if getattr(sys, "frozen", False):
        return os.path.join(getattr(sys, "_MEIPASS", ""), "app_gui", "assets", "qss")
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "qss")


@lru_cache(maxsize=8)
def _read_qss_asset(name):
    path = os.path.join(_qss_assets_dir(), name)
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


def _get_theme_vars(mode):
    """Return the CSS variable declarations for the given theme mode.

    Tokens live in ``app_gui/assets/qss/{light,dark}.qss`` inside a single
    ``:root { ... }`` block; only the declarations are returned.
    """
    raw = _read_qss_asset("light.qss" if mode == "light" else "dark.qss")
    match = re.search(r":root\s*\{([^}]*)\}", raw, flags=re.S)
    return match.group(1) if match else ""


def _get_common_qss():
    """Return the shared widget QSS (``app_gui/assets/qss/common.qss``).

    ``{FONT_*}`` placeholders are resolved against this module's typography
    constants so that a single source of truth drives both Python and QSS.
    """
    qss = _read_qss_asset("common.qss")
    return re.sub(
        r"\{(FONT_[A-Z_]+)\}",
        lambda m: str(globals().get(m.group(1), m.group(0))),
        qss,
    )


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

    theme_vars = _get_theme_vars(mode) + _get_icon_vars(mode)
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
            border: 1px solid transparent;
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
            background-color: transparent;
            color: var(--cell-empty-fresh-text);
            border: 1px dashed var(--cell-empty-fresh-border);
            border-radius: 3px;
            padding: 1px;

        }
        QPushButton:hover {
            border: 1px solid var(--border-strong);
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

---
name: lucide-icons
description: Add or replace Lucide icons in the ln2-inventory-agent project. Use when the user wants to add new icons, replace existing icons, download Lucide SVG files, update icon constants, or troubleshoot icon display issues (icons not showing, wrong colors in dark/light theme).
---

# Lucide Icons Management

Add or replace modern flat-style icons from Lucide Icons library in the ln2-inventory-agent project.

## Project Icon Architecture

**Icon Library**: Lucide Icons (https://lucide.dev) - Modern, flat-style line icons with MIT license

**Directory Structure**:
```
app_gui/
├── assets/icons/          # SVG icon files
│   ├── plus.svg
│   ├── settings.svg
│   └── ...
└── ui/icons.py           # Icon management module
```

**Icon Management Module** (`app_gui/ui/icons.py`):
- `set_icon_color(color)` - Set global icon color based on theme
- `get_icon(name, size, color)` - Load icon with specified parameters
- `Icons` class - Icon name constants (e.g., `Icons.PLUS`, `Icons.SETTINGS`)

**Color Rules**:
- Dark theme: `#ffffff` (white icons)
- Light theme: `#000000` (black icons)
- Set automatically in `main.py` on app startup

## Adding New Icons

### 1. Download Icon

**Single icon**:
```bash
cd /analysis4/fanym/projects/personal/ln2-inventory-agent
curl -sL -o app_gui/assets/icons/<icon-name>.svg \
  "https://unpkg.com/lucide-static@latest/icons/<icon-name>.svg"
```

**Multiple icons** (use bundled script):
```bash
cd /analysis4/fanym/projects/personal/ln2-inventory-agent
.claude/lucide-icons/scripts/download_icons.sh trash edit save copy
```

**Verify download**:
```bash
cat app_gui/assets/icons/<icon-name>.svg | head -5
# Should show SVG content with stroke="currentColor"
```

**Common icon names**: trash, edit, save, copy, download, upload, search, filter, menu, eye, eye-off, arrow-left, arrow-right, check, alert-circle

Browse all icons: https://lucide.dev/icons/

### 2. Update Icons Class

Edit `app_gui/ui/icons.py`, add constant to `Icons` class:

```python
class Icons:
    # Existing icons...
    PLUS = "plus"
    SETTINGS = "settings"

    # Add new icon (use UPPER_CASE with underscores)
    TRASH = "trash"
    EDIT = "edit"
    SAVE = "save"
```

**Naming convention**: SVG filename `file-plus.svg` → constant `FILE_PLUS = "file-plus"`

### 3. Use Icon in Code

```python
from app_gui.ui.icons import get_icon, Icons

# Basic usage
button = QPushButton("Delete")
button.setIcon(get_icon(Icons.TRASH))
button.setIconSize(QSize(16, 16))

# Different sizes
small_icon = get_icon(Icons.EDIT, size=14)
large_icon = get_icon(Icons.SETTINGS, size=24)

# Custom color (override theme color)
red_icon = get_icon(Icons.TRASH, color="#ff0000")
```

**Size guidelines**:
- Small buttons/inline: 12-14px
- Normal buttons: 16-18px
- Large buttons/toolbar: 20-24px

## Replacing Existing Icons

### 1. Download New Icon

```bash
cd /analysis4/fanym/projects/personal/ln2-inventory-agent
curl -sL -o app_gui/assets/icons/<new-icon-name>.svg \
  "https://unpkg.com/lucide-static@latest/icons/<new-icon-name>.svg"
```

### 2. Update Icons Class (if name changes)

```python
# Old
REFRESH = "refresh-cw"

# New
REFRESH = "rotate-cw"
```

### 3. Update Code References (if constant name changes)

Search and replace icon constant usage across codebase.

## Troubleshooting

### Icons Show Black in Dark Theme

**Cause**: Icon color not set correctly

**Fix**: Check `main.py` theme initialization:
```python
# Should be BEFORE apply_theme
if theme == "light":
    set_icon_color("#000000")
    apply_light_theme(app)
else:
    set_icon_color("#ffffff")
    apply_dark_theme(app)
```

### Icons Not Showing

**Check 1**: Verify SVG file exists
```bash
ls -la app_gui/assets/icons/<icon-name>.svg
```

**Check 2**: Verify Icons class has constant
```bash
grep "ICON_NAME" app_gui/ui/icons.py
```

**Check 3**: Verify SVG uses currentColor
```bash
grep "currentColor" app_gui/assets/icons/<icon-name>.svg
```

If SVG has fixed color (e.g., `stroke="#000000"`), replace with `currentColor`:
```bash
sed -i 's/stroke="#[0-9a-fA-F]\{6\}"/stroke="currentColor"/g' \
  app_gui/assets/icons/<icon-name>.svg
```

### Wrong Icon Downloaded

**Symptom**: SVG file contains HTML redirect text instead of SVG content

**Cause**: curl didn't follow redirect

**Fix**: Use `-L` flag:
```bash
curl -sL -o icon.svg "https://unpkg.com/lucide-static@latest/icons/icon.svg"
```

## Testing

After adding/replacing icons:

```bash
# Test imports
python -c "from app_gui.ui.icons import get_icon, Icons; print('OK')"

# Run GUI tests
pytest tests/test_gui_panels.py -k overview -v
```

Test icon display in both dark and light themes.

## PyInstaller Packaging

Icons are automatically included in builds via `ln2_inventory.spec`:
```python
datas=[
    ("app_gui/assets", "app_gui/assets"),
]
```

No additional configuration needed.

## Resources

### scripts/download_icons.sh

Batch download multiple icons:
```bash
.claude/lucide-icons/scripts/download_icons.sh icon1 icon2 icon3
```

Automatically:
- Downloads from Lucide CDN
- Validates SVG content
- Reports success/failure for each icon

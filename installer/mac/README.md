# macOS Self-Use Packaging

This folder contains helper assets for building an unsigned macOS app bundle and installer package.

## Prerequisites

- Build must run on macOS (Darwin).
- Python 3.10+ with project dependencies installed. Python 3.11 is recommended.
- PyInstaller installed in the same environment.

## Build

From repository root:

```bash
python3.11 -m pip install -r requirements.txt
python3.11 -m pip install pyinstaller
PYTHON=python3.11 bash installer/mac/build_app.sh
```

`build_app.sh` now auto-generates `installer/mac/SnowFox.icns` from `app_gui/assets/icon.png`
before invoking PyInstaller, so the bundled macOS app icon stays in sync with the project icon.

Or run PyInstaller directly:

```bash
python3.11 -m PyInstaller ln2_inventory.mac.spec
```

## Output

- App bundle: `dist/SnowFox.app`
- Installer package: `dist/installer/SnowFox-<version>-macOS.pkg`

These outputs are intended for self-use testing (unsigned/not notarized).

## Build Installer Package

From repository root:

```bash
python3.11 -m pip install -r requirements.txt
python3.11 -m pip install pyinstaller
PYTHON=python3.11 bash installer/mac/build_pkg.sh
```

If you already built the app bundle and only want to regenerate the installer:

```bash
PYTHON=python3.11 bash installer/mac/build_pkg.sh --skip-app-build
```

# macOS Self-Use Packaging

This folder contains helper assets for building an unsigned macOS app bundle.

## Prerequisites

- Build must run on macOS (Darwin).
- Python 3.8+ with project dependencies installed.
- PyInstaller installed in the same environment.

## Build

From repository root:

```bash
python3 -m pip install -r requirements.txt
python3 -m pip install pyinstaller
bash installer/mac/build_app.sh
```

Or run PyInstaller directly:

```bash
pyinstaller ln2_inventory.mac.spec
```

## Output

- App bundle: `dist/SnowFox.app`

This path is intended for self-use testing (unsigned/not notarized).

# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for LN2 Inventory Agent GUI (onedir build).

Usage (on Windows with PySide6 + PyYAML installed):
    pip install pyinstaller
    pyinstaller ln2_inventory.spec
"""

import os
import re
import shutil

# Extract APP_VERSION from main.py without triggering full import
with open("app_gui/main.py", encoding="utf-8") as f:
    content = f.read()
    match = re.search(r'APP_VERSION\s*=\s*["\']([^"\']+)["\']', content)
    if match:
        APP_VERSION = match.group(1)
    else:
        APP_VERSION = "1.0.0"

block_cipher = None

a = Analysis(
    ["app_gui/main.py"],
    pathex=[],
    binaries=[],
    datas=[
        ("app_gui/i18n/translations", "app_gui/i18n/translations"),
        ("app_gui/assets", "app_gui/assets"),
        ("migration_assets", "migration_assets"),
        ("migrate/README.md", "migrate"),
        ("migrate/inputs/.gitkeep", "migrate/inputs"),
        ("migrate/output/.gitkeep", "migrate/output"),
    ],
    hiddenimports=["yaml", "mistune", "openpyxl", "et_xmlfile"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["scripts", "tests", "pytest", "matplotlib", "numpy", "scipy"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=f"SnowFox-{APP_VERSION}",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="installer/windows/icon.ico",
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="SnowFox",
)


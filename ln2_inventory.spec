# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for LN2 Inventory Agent GUI (onedir build).

Usage (on Windows with PySide6 + PyYAML installed):
    pip install pyinstaller
    pyinstaller ln2_inventory.spec
"""

import os
import shutil

block_cipher = None

a = Analysis(
    ["app_gui/main.py"],
    pathex=[],
    binaries=[],
    datas=[
        ("app_gui/i18n/translations", "app_gui/i18n/translations"),
        ("app_gui/assets", "app_gui/assets"),
    ],
    hiddenimports=["yaml"],
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
    name="LN2InventoryAgent",
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
    name="LN2InventoryAgent",
)

# Copy demo folder to output directory
demo_src = os.path.join(os.path.dirname(SPEC), "demo", "ln2_inventory.demo.yaml")
demo_dst_dir = os.path.join(coll.name, "demo")
os.makedirs(demo_dst_dir, exist_ok=True)
shutil.copy2(demo_src, demo_dst_dir)

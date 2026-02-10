# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for LN2 Inventory Agent GUI.

Usage (on Windows with PySide6 + PyYAML installed):
    pip install pyinstaller
    pyinstaller ln2_inventory.spec
"""

import os

block_cipher = None

a = Analysis(
    ["app_gui/main.py"],
    pathex=[],
    binaries=[],
    datas=[
        ("demo/ln2_inventory.demo.yaml", "demo"),
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
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="LN2InventoryAgent",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # windowed mode, no console
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

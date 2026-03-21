# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for SnowFox macOS app bundle (self-use, unsigned).

Usage (on macOS with PySide6 + dependencies installed):
    python3 -m pip install pyinstaller
    pyinstaller ln2_inventory.mac.spec
"""

import os
import re
import subprocess
import sys


def _extract_app_version():
    with open("app_gui/version.py", encoding="utf-8") as handle:
        content = handle.read()
    match = re.search(r'APP_VERSION[^=]*=\s*["\']([^"\']+)["\']', content)
    if match:
        return match.group(1)
    return "1.0.0"


def _collect_datas():
    datas = []
    candidates = [
        ("app_gui/i18n/translations", "app_gui/i18n/translations"),
        ("app_gui/assets", "app_gui/assets"),
        ("agent_skills", "agent_skills"),
        ("migration_assets", "migration_assets"),
        ("migrate/README.md", "migrate"),
        ("migrate/inputs", "migrate/inputs"),
        ("migrate/output", "migrate/output"),
    ]
    for source, target in candidates:
        if os.path.exists(source):
            datas.append((source, target))
    return datas


def _resolve_bundle_icon():
    icon_path = os.path.join("installer", "mac", "SnowFox.icns")
    icon_source = os.path.join("app_gui", "assets", "icon.png")
    generator = os.path.join("installer", "mac", "generate_icns.sh")

    if (
        os.path.exists(icon_path)
        and os.path.exists(icon_source)
        and os.path.getmtime(icon_path) >= os.path.getmtime(icon_source)
    ):
        return icon_path

    if sys.platform == "darwin" and os.path.exists(generator):
        try:
            subprocess.run(["bash", generator], check=True)
        except Exception as exc:
            print(f"WARN: failed to generate macOS bundle icon: {exc}")

    return icon_path if os.path.exists(icon_path) else None


APP_VERSION = _extract_app_version()
APP_ICON = _resolve_bundle_icon()
block_cipher = None

a = Analysis(
    ["app_gui/main.py"],
    pathex=[],
    binaries=[],
    datas=_collect_datas(),
    hiddenimports=["yaml", "mistune", "openpyxl", "et_xmlfile"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tests", "pytest", "matplotlib", "numpy", "scipy"],
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
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name="SnowFox",
)

app = BUNDLE(
    coll,
    name="SnowFox.app",
    icon=APP_ICON,
    bundle_identifier="com.eamonfox.snowfox",
    info_plist={
        "CFBundleName": "SnowFox",
        "CFBundleDisplayName": "SnowFox",
        "CFBundleShortVersionString": APP_VERSION,
        "CFBundleVersion": APP_VERSION,
        "NSHighResolutionCapable": True,
    },
)

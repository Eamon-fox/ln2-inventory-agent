"""Path utilities shared by GUI runtime and tests."""

from __future__ import annotations

import ntpath
import os
import sys
from typing import Optional


def _demo_from_executable(executable: str) -> str:
    """Build demo dataset path next to executable for frozen builds."""
    exe_path = str(executable or "")
    posix_dir = os.path.dirname(exe_path)
    nt_dir = ntpath.dirname(exe_path)

    # On non-Windows hosts, os.path.dirname("D:\\x\\a.exe") is empty.
    if not posix_dir and nt_dir:
        return ntpath.join(nt_dir, "demo", "ln2_inventory.demo.yaml")
    return os.path.join(posix_dir, "demo", "ln2_inventory.demo.yaml")


def resolve_demo_dataset_path(
    root: Optional[str] = None,
    frozen: Optional[bool] = None,
    executable: Optional[str] = None,
) -> str:
    """Resolve demo dataset path for both packaged and source runs."""
    project_root = root or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    is_frozen = getattr(sys, "frozen", False) if frozen is None else bool(frozen)

    if is_frozen:
        exe_path = sys.executable if executable is None else executable
        return _demo_from_executable(str(exe_path))

    return os.path.join(project_root, "demo", "ln2_inventory.demo.yaml")

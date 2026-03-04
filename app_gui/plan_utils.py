"""Shared lightweight helpers for plan preview/outcome modules."""

from __future__ import annotations

from typing import Any


def to_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default

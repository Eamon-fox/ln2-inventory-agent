"""Helpers for applying SnowFox UI scale to Qt process environments."""

from __future__ import annotations

import os
from collections.abc import MutableMapping
from typing import Mapping


QT_SCALE_FACTOR = "QT_SCALE_FACTOR"
QT_ENABLE_HIGHDPI_SCALING = "QT_ENABLE_HIGHDPI_SCALING"
QT_SCALE_FACTOR_ROUNDING_POLICY = "QT_SCALE_FACTOR_ROUNDING_POLICY"
_QT_SCALE_KEYS = (
    QT_SCALE_FACTOR,
    QT_ENABLE_HIGHDPI_SCALING,
    QT_SCALE_FACTOR_ROUNDING_POLICY,
)


def coerce_ui_scale(value, default: float = 1.0) -> float:
    """Parse a positive UI scale value with a conservative fallback."""
    try:
        parsed = float(value)
    except Exception:
        return float(default)
    if parsed <= 0:
        return float(default)
    return parsed


def build_qt_scale_environment(
    ui_scale,
    *,
    base_env: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Return a process environment with Qt scale variables normalized."""
    env = dict(os.environ if base_env is None else base_env)
    scale = coerce_ui_scale(ui_scale, default=1.0)
    if scale == 1.0:
        for key in _QT_SCALE_KEYS:
            env.pop(key, None)
        return env

    env[QT_SCALE_FACTOR] = str(scale)
    env[QT_ENABLE_HIGHDPI_SCALING] = "1"
    env[QT_SCALE_FACTOR_ROUNDING_POLICY] = "PassThrough"
    return env


def apply_qt_scale_environment(
    ui_scale,
    *,
    environ: MutableMapping[str, str] | None = None,
) -> None:
    """Normalize Qt scale variables on the current process environment."""
    target = os.environ if environ is None else environ
    normalized = build_qt_scale_environment(ui_scale, base_env=target)
    for key in _QT_SCALE_KEYS:
        if key in normalized:
            target[key] = normalized[key]
        else:
            target.pop(key, None)


__all__ = [
    "QT_ENABLE_HIGHDPI_SCALING",
    "QT_SCALE_FACTOR",
    "QT_SCALE_FACTOR_ROUNDING_POLICY",
    "apply_qt_scale_environment",
    "build_qt_scale_environment",
    "coerce_ui_scale",
]

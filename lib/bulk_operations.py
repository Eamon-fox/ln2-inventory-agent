"""Registry-derived metadata for SnowFox batch operation diagnostics.

Execution dispatch remains owned by the plan executor and write adapters.
This module only projects registry descriptors into lightweight capability
metadata so diagnostics do not grow a second capability truth source.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Iterable

from .tool_registry import (
    GUI_BRIDGE_READ,
    get_tool_descriptor,
    iter_gui_bridge_descriptors,
    iter_tool_descriptors,
    iter_write_tool_descriptors,
)


@dataclass(frozen=True)
class BatchCapability:
    """Metadata describing one internal batch-capable operation."""

    action: str
    tool_name: str
    write_api_attr: str | None = None
    supports_preflight: bool = True
    supports_execute: bool = True
    read_only: bool = False
    notes: str = ""


@lru_cache(maxsize=1)
def _write_capabilities() -> dict[str, BatchCapability]:
    descriptors_by_action = {
        str(descriptor.plan_action or "").strip().lower(): descriptor
        for descriptor in iter_write_tool_descriptors()
        if descriptor.plan_action
    }

    for name in ("batch_add_entries", "batch_edit_entries"):
        descriptor = get_tool_descriptor(name)
        if descriptor is None or not descriptor.plan_action:
            continue
        descriptors_by_action[str(descriptor.plan_action).strip().lower()] = descriptor

    capabilities: dict[str, BatchCapability] = {}
    for action, descriptor in descriptors_by_action.items():
        notes = "Rollback must be executed alone." if action == "rollback" else ""
        capabilities[action] = BatchCapability(
            action=action,
            tool_name=descriptor.name,
            write_api_attr=descriptor.write_api_attr,
            notes=notes,
        )
    return capabilities


@lru_cache(maxsize=1)
def _read_capabilities() -> dict[str, BatchCapability]:
    descriptors = {
        descriptor.name: descriptor
        for descriptor in iter_tool_descriptors()
        if not descriptor.is_write and not descriptor.is_migration
    }
    descriptors.update(
        {
            descriptor.name: descriptor
            for descriptor in iter_gui_bridge_descriptors()
            if descriptor.gui_bridge is not None
            and descriptor.gui_bridge.strategy == GUI_BRIDGE_READ
        }
    )
    return {
        name: BatchCapability(
            action=name,
            tool_name=name,
            read_only=True,
            supports_execute=False,
        )
        for name in sorted(descriptors)
    }


def get_write_capability(action: str) -> BatchCapability | None:
    return _write_capabilities().get(str(action or "").strip().lower())


def get_read_capability(tool_name: str) -> BatchCapability | None:
    return _read_capabilities().get(str(tool_name or "").strip())


def iter_write_capabilities() -> tuple[BatchCapability, ...]:
    return tuple(_write_capabilities().values())


def iter_read_capabilities() -> tuple[BatchCapability, ...]:
    return tuple(_read_capabilities().values())


def group_plan_items_by_action(items: Iterable[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in list(items or []):
        action = str((item or {}).get("action") or "").strip().lower()
        if not action:
            continue
        grouped.setdefault(action, []).append(item)
    return grouped

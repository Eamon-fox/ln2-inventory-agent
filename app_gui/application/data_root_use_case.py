"""Application-layer helpers for writable data-root changes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from lib.app_storage import ensure_data_root_layout, migrate_data_root, normalize_data_root, remap_inventory_yaml_path


@dataclass(frozen=True)
class DataRootChangeResult:
    data_root: str
    yaml_path: str = ""
    migrated: bool = False


class DataRootUseCase:
    def __init__(
        self,
        *,
        ensure_data_root_layout_fn: Callable[[str], str] = ensure_data_root_layout,
        migrate_data_root_fn: Callable[[str, str], dict] = migrate_data_root,
        remap_inventory_yaml_path_fn: Callable[..., str] = remap_inventory_yaml_path,
        normalize_data_root_fn: Callable[[str], str] = normalize_data_root,
    ):
        self._ensure_data_root_layout = ensure_data_root_layout_fn
        self._migrate_data_root = migrate_data_root_fn
        self._remap_inventory_yaml_path = remap_inventory_yaml_path_fn
        self._normalize_data_root = normalize_data_root_fn

    def initialize_root(self, *, target_root: str) -> DataRootChangeResult:
        target = self._ensure_data_root_layout(target_root)
        return DataRootChangeResult(data_root=self._normalize_data_root(target))

    def migrate_root(
        self,
        *,
        source_root: str,
        target_root: str,
        current_yaml_path: str = "",
    ) -> DataRootChangeResult:
        result = self._migrate_data_root(source_root, target_root)
        mapped_yaml = self._remap_inventory_yaml_path(
            current_yaml_path,
            source_root=source_root,
            target_root=target_root,
        )
        return DataRootChangeResult(
            data_root=self._normalize_data_root(result.get("data_root") or target_root),
            yaml_path=mapped_yaml,
            migrated=self._normalize_data_root(source_root) != self._normalize_data_root(target_root),
        )


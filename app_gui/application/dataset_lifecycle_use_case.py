"""Managed dataset lifecycle orchestration for the GUI application layer."""

import os
from dataclasses import dataclass
from typing import Callable, Optional

import yaml

from lib.inventory_paths import (
    assert_allowed_inventory_yaml_path,
    build_dataset_delete_payload,
    build_dataset_rename_payload,
    create_managed_dataset_yaml_path,
    delete_managed_dataset_yaml_path,
    ensure_inventories_root,
    latest_managed_inventory_yaml_path,
    list_managed_datasets,
    normalize_inventory_yaml_path,
    rename_managed_dataset_yaml_path,
)
from lib.yaml_ops import append_audit_event, ensure_runtime_dataset_canonical, load_yaml


@dataclass(frozen=True)
class DatasetLifecycleResult:
    target_path: str
    audit_error: Optional[str] = None


@dataclass(frozen=True)
class DatasetDeleteResult(DatasetLifecycleResult):
    deleted_yaml_path: str = ""
    fallback_created: bool = False


@dataclass(frozen=True)
class DatasetLifecyclePathPolicy:
    normalize_yaml_path: Callable[[str], str] = normalize_inventory_yaml_path
    assert_allowed_path: Callable[..., str] = assert_allowed_inventory_yaml_path


@dataclass(frozen=True)
class ManagedDatasetGateway:
    ensure_inventories_root: Callable[[], None] = ensure_inventories_root
    latest_inventory_yaml_path: Callable[[], str] = latest_managed_inventory_yaml_path
    create_dataset_yaml_path: Callable[[str], str] = create_managed_dataset_yaml_path
    list_managed_datasets: Callable[[], list] = list_managed_datasets
    rename_dataset_yaml_path: Callable[[str, str], str] = rename_managed_dataset_yaml_path
    delete_dataset_yaml_path: Callable[[str], dict] = delete_managed_dataset_yaml_path


@dataclass(frozen=True)
class DatasetLifecycleServices:
    build_dataset_rename_payload: Callable[[str, str], dict] = build_dataset_rename_payload
    build_dataset_delete_payload: Callable[[str, str], dict] = build_dataset_delete_payload
    append_audit_event: Callable[..., None] = append_audit_event
    ensure_runtime_ready: Callable[..., object] = ensure_runtime_dataset_canonical
    load_yaml: Callable[[str], dict] = load_yaml


class DatasetLifecycleUseCase:
    """Coordinate managed dataset create/rename/delete/startup behaviors."""

    def __init__(
        self,
        *,
        path_policy: Optional[DatasetLifecyclePathPolicy] = None,
        managed_datasets: Optional[ManagedDatasetGateway] = None,
        services: Optional[DatasetLifecycleServices] = None,
    ):
        self._path_policy = path_policy or DatasetLifecyclePathPolicy()
        self._managed_datasets = managed_datasets or ManagedDatasetGateway()
        self._services = services or DatasetLifecycleServices()

        self._normalize_yaml_path = self._path_policy.normalize_yaml_path
        self._assert_allowed_path = self._path_policy.assert_allowed_path
        self._ensure_inventories_root = self._managed_datasets.ensure_inventories_root
        self._latest_inventory_yaml_path = self._managed_datasets.latest_inventory_yaml_path
        self._create_dataset_yaml_path = self._managed_datasets.create_dataset_yaml_path
        self._list_managed_datasets = self._managed_datasets.list_managed_datasets
        self._rename_dataset_yaml_path = self._managed_datasets.rename_dataset_yaml_path
        self._delete_dataset_yaml_path = self._managed_datasets.delete_dataset_yaml_path
        self._build_dataset_rename_payload = self._services.build_dataset_rename_payload
        self._build_dataset_delete_payload = self._services.build_dataset_delete_payload
        self._append_audit_event = self._services.append_audit_event
        self._ensure_runtime_ready = self._services.ensure_runtime_ready
        self._load_yaml = self._services.load_yaml

    @staticmethod
    def default_inventory_payload():
        return {
            "meta": {
                "version": "1.0",
                "box_layout": {
                    "rows": 9,
                    "cols": 9,
                    "box_count": 5,
                    "box_numbers": [1, 2, 3, 4, 5],
                },
                "custom_fields": [],
            },
            "inventory": [],
        }

    def write_inventory_yaml(self, path, payload=None):
        target_path = os.path.abspath(str(path or "").strip())
        if not target_path:
            raise ValueError("target inventory path is required")
        target_dir = os.path.dirname(target_path)
        if target_dir:
            os.makedirs(target_dir, exist_ok=True)
        with open(target_path, "w", encoding="utf-8") as handle:
            yaml.safe_dump(
                payload or self.default_inventory_payload(),
                handle,
                allow_unicode=True,
                sort_keys=False,
            )
        return target_path

    def resolve_startup_yaml_path(self, *, configured_yaml_path: str) -> str:
        self._ensure_inventories_root()

        configured = self._normalize_yaml_path(configured_yaml_path)
        if configured:
            try:
                resolved = self._assert_allowed_path(configured, must_exist=True)
                return self.prepare_runtime_yaml_path(
                    resolved,
                    source="app_gui.startup.resolve_dataset",
                )
            except Exception:
                pass

        latest = self._latest_inventory_yaml_path()
        if latest:
            resolved = self._assert_allowed_path(latest, must_exist=True)
            return self.prepare_runtime_yaml_path(
                resolved,
                source="app_gui.startup.latest_dataset",
            )

        default_yaml = self._create_dataset_yaml_path("inventory")
        self.write_inventory_yaml(default_yaml)
        resolved = self._assert_allowed_path(default_yaml, must_exist=True)
        return self.prepare_runtime_yaml_path(
            resolved,
            source="app_gui.startup.default_dataset",
        )

    def prepare_runtime_yaml_path(self, yaml_path: str, *, source: str = "app_gui.dataset_open") -> str:
        """Ensure one managed dataset is canonical before runtime reads/writes."""
        target = self._assert_allowed_path(yaml_path, must_exist=True)
        result = self._ensure_runtime_ready(
            target,
            source=str(source or "app_gui.dataset_open"),
        )
        if isinstance(result, dict):
            prepared = str(result.get("path") or target)
            return self._assert_allowed_path(prepared, must_exist=True)
        return self._assert_allowed_path(str(result or target), must_exist=True)

    def create_dataset(
        self,
        *,
        target_path: str,
        box_layout: dict,
        custom_fields: list,
        display_key: str = "",
        color_key: str = "",
    ) -> DatasetLifecycleResult:
        target = self._assert_allowed_path(target_path, must_exist=False)
        meta = {
            "version": "1.0",
            "box_layout": box_layout,
            "custom_fields": list(custom_fields or []),
        }
        if display_key:
            meta["display_key"] = display_key
        if color_key:
            meta["color_key"] = color_key
        payload = {
            "meta": meta,
            "inventory": [],
        }
        self.write_inventory_yaml(target, payload)
        return DatasetLifecycleResult(target_path=target)

    def rename_dataset(
        self,
        *,
        current_yaml_path: str,
        new_dataset_name: str,
        audit_source: str = "app_gui.settings",
    ) -> DatasetLifecycleResult:
        source_yaml = self._normalize_yaml_path(current_yaml_path)
        new_yaml_path = self._rename_dataset_yaml_path(source_yaml, new_dataset_name)
        details = self._build_dataset_rename_payload(source_yaml, new_yaml_path)
        audit_error = self._append_dataset_audit(
            yaml_path=new_yaml_path,
            action="dataset_rename",
            source=audit_source,
            details=details,
        )
        return DatasetLifecycleResult(
            target_path=new_yaml_path,
            audit_error=audit_error,
        )

    def delete_dataset(
        self,
        *,
        current_yaml_path: str,
        fallback_dataset_name: str = "inventory",
        audit_source: str = "app_gui.settings",
    ) -> DatasetDeleteResult:
        source_yaml = self._normalize_yaml_path(current_yaml_path)
        deleted = self._delete_dataset_yaml_path(source_yaml)
        deleted_yaml = self._normalize_yaml_path((deleted or {}).get("yaml_path") or source_yaml)
        fallback_yaml, fallback_created = self._resolve_delete_fallback(
            fallback_dataset_name=fallback_dataset_name,
        )
        details = self._build_dataset_delete_payload(deleted_yaml, fallback_yaml)
        audit_error = self._append_dataset_audit(
            yaml_path=fallback_yaml,
            action="dataset_delete",
            source=audit_source,
            details=details,
        )
        return DatasetDeleteResult(
            target_path=fallback_yaml,
            audit_error=audit_error,
            deleted_yaml_path=deleted_yaml,
            fallback_created=fallback_created,
        )

    def _resolve_delete_fallback(self, *, fallback_dataset_name: str) -> tuple[str, bool]:
        rows = self._list_managed_datasets()
        fallback_yaml = ""
        if rows:
            fallback_yaml = self._normalize_yaml_path(rows[0].get("yaml_path"))

        fallback_created = False
        if not fallback_yaml:
            fallback_yaml = self._create_dataset_yaml_path(fallback_dataset_name)
            self.write_inventory_yaml(fallback_yaml)
            fallback_created = True

        return self._assert_allowed_path(fallback_yaml, must_exist=True), fallback_created

    def _append_dataset_audit(self, *, yaml_path: str, action: str, source: str, details: dict):
        try:
            current_data = self._load_yaml(yaml_path)
        except Exception:
            current_data = None

        try:
            self._append_audit_event(
                yaml_path=yaml_path,
                before_data=current_data,
                after_data=current_data,
                backup_path=None,
                warnings=[],
                audit_meta={
                    "action": str(action or ""),
                    "source": str(source or ""),
                    "details": details,
                },
            )
        except Exception as exc:
            return str(exc)
        return None

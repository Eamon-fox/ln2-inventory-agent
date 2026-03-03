"""Write gateway for settings-driven dataset mutations."""

import os
from typing import Any, Dict

from .inventory_paths import assert_allowed_inventory_yaml_path
from .yaml_ops import (
    append_backup_event,
    create_yaml_backup,
    get_audit_log_path,
    write_yaml,
)


def _error_result(error_code: str, message: str) -> Dict[str, Any]:
    return {
        "ok": False,
        "error_code": str(error_code or "write_failed"),
        "message": str(message or "Write failed"),
    }


def persist_custom_fields_update(
    *,
    yaml_path: Any,
    pending_data: Dict[str, Any],
    audit_details: Dict[str, Any],
) -> Dict[str, Any]:
    """Persist one custom-fields update with backup + audit.

    Flow:
    1) create request backup (must succeed)
    2) append backup audit event (must succeed)
    3) write pending data through write_yaml(meta-only validation)
    """
    try:
        yaml_abs = assert_allowed_inventory_yaml_path(str(yaml_path or ""))
    except Exception as exc:
        return _error_result("invalid_yaml_path", str(exc))

    try:
        created = create_yaml_backup(yaml_abs)
    except Exception as exc:
        return _error_result(
            "backup_create_failed",
            f"Failed to create backup before saving custom fields: {exc}",
        )

    if not created:
        return _error_result(
            "backup_create_failed",
            "Failed to create backup before saving custom fields.",
        )

    backup_abs = os.path.abspath(str(created))

    try:
        append_backup_event(
            yaml_path=yaml_abs,
            backup_path=backup_abs,
            source="settings.custom_fields",
            details={"kind": "settings_custom_fields"},
        )
    except Exception as exc:
        return _error_result(
            "backup_audit_failed",
            f"Failed to append backup audit event: {exc}",
        )

    try:
        write_yaml(
            pending_data,
            path=yaml_abs,
            auto_backup=False,
            backup_path=backup_abs,
            audit_meta={
                "action": "edit_custom_fields",
                "source": "settings_dialog",
                "tool_name": "settings.custom_fields",
                "status": "success",
                "details": dict(audit_details or {}),
            },
            validation_scope="meta_only",
        )
    except ValueError as exc:
        return _error_result("validation_failed", str(exc))
    except Exception as exc:
        return _error_result("write_failed", str(exc))

    return {
        "ok": True,
        "backup_path": backup_abs,
        "audit_log_path": get_audit_log_path(yaml_abs),
    }


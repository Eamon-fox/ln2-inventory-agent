"""Domain service for Settings custom-fields update planning.

This module is intentionally I/O free. It computes the in-memory draft for a
custom-fields update, including rename conflict detection, selector sync, and
write-canonical legacy field handling.
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Set, Tuple

from .legacy_field_policy import (
    canonicalize_record_legacy_fields,
    normalize_legacy_custom_field_defs,
    normalize_legacy_field_key,
)


def _has_nonempty_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    return True


def _copy_inventory(inventory: Any) -> List[Any]:
    copied: List[Any] = []
    if not isinstance(inventory, list):
        return copied
    for rec in inventory:
        if isinstance(rec, dict):
            cloned = dict(rec)
            canonicalize_record_legacy_fields(cloned)
            copied.append(cloned)
        else:
            copied.append(rec)
    return copied


def _normalize_new_fields(raw_fields: Any) -> Tuple[List[Dict[str, Any]], Dict[str, str]]:
    normalized: List[Dict[str, Any]] = []
    renames: Dict[str, str] = {}

    if not isinstance(raw_fields, list):
        return normalized, renames

    canonical_fields, _alias_changes = normalize_legacy_custom_field_defs(raw_fields)
    for raw in canonical_fields:
        if not isinstance(raw, dict):
            continue
        item = dict(raw)
        original_key = normalize_legacy_field_key(item.pop("_original_key", ""))
        key = normalize_legacy_field_key(item.get("key", ""))
        if key:
            item["key"] = key
        if original_key and key and original_key != key:
            renames[original_key] = key
        normalized.append(item)
    return normalized, renames


def _collect_rename_conflicts(
    inventory: List[Any],
    renames: Dict[str, str],
) -> List[Dict[str, Any]]:
    conflicts: List[Dict[str, Any]] = []
    if not renames:
        return conflicts

    for rec in inventory:
        if not isinstance(rec, dict):
            continue
        rid = rec.get("id")
        for old_key, new_key in renames.items():
            if old_key not in rec or new_key not in rec:
                continue
            old_value = rec.get(old_key)
            new_value = rec.get(new_key)
            if not _has_nonempty_value(old_value) or not _has_nonempty_value(new_value):
                continue
            if str(old_value).strip() == str(new_value).strip():
                continue
            conflicts.append(
                {
                    "record_id": rid,
                    "from_key": old_key,
                    "to_key": new_key,
                    "from_value": old_value,
                    "to_value": new_value,
                }
            )
    return conflicts


def _apply_renames(inventory: List[Any], renames: Dict[str, str]) -> int:
    """Apply rename map in-place and return touched record count."""
    if not renames:
        return 0

    touched = 0
    for rec in inventory:
        if not isinstance(rec, dict):
            continue
        rec_touched = False
        for old_key, new_key in renames.items():
            if old_key not in rec:
                continue
            old_value = rec.get(old_key)
            target_value = rec.get(new_key)
            if _has_nonempty_value(target_value):
                rec.pop(old_key, None)
            else:
                rec[new_key] = rec.pop(old_key)
            rec_touched = True
        if rec_touched:
            touched += 1
    return touched


def _resolve_selector_key(
    *,
    current_value: Any,
    requested_value: Any,
    renames: Dict[str, str],
    allowed_keys: Set[str],
) -> str:
    selected = ""
    if isinstance(requested_value, str) and requested_value:
        selected = normalize_legacy_field_key(requested_value)
    elif isinstance(current_value, str) and current_value:
        selected = normalize_legacy_field_key(current_value)
    selected = renames.get(selected, selected)
    if selected and selected in allowed_keys:
        return selected
    return ""


@dataclass
class CustomFieldsUpdateDraft:
    pending_meta: Dict[str, Any]
    pending_inventory: List[Any]
    new_fields: List[Dict[str, Any]]
    renames: Dict[str, str]
    rename_conflicts: List[Dict[str, Any]]
    old_keys: Set[str]
    new_keys: Set[str]
    added_keys: Set[str]
    removed_keys: Set[str]
    removed_keys_with_data: Set[str]
    selector_before: Dict[str, str]
    selector_after: Dict[str, str]
    stats: Dict[str, Any]


def prepare_custom_fields_update(
    *,
    meta: Any,
    inventory: Any,
    existing_fields: Any,
    new_fields: Any,
    current_display_key: Any,
    current_color_key: Any,
    requested_display_key: Any,
    requested_color_key: Any,
) -> CustomFieldsUpdateDraft:
    meta_dict = dict(meta) if isinstance(meta, dict) else {}
    pending_inventory = _copy_inventory(inventory)
    normalized_fields, renames = _normalize_new_fields(new_fields)

    conflicts = _collect_rename_conflicts(pending_inventory, renames)
    rename_touched_records = 0
    if not conflicts:
        rename_touched_records = _apply_renames(pending_inventory, renames)

    old_keys = {
        normalize_legacy_field_key(item.get("key"))
        for item in (existing_fields or [])
        if isinstance(item, dict) and normalize_legacy_field_key(item.get("key"))
    }
    new_keys = {
        str(item.get("key") or "").strip()
        for item in normalized_fields
        if isinstance(item, dict) and str(item.get("key") or "").strip()
    }
    renamed_old_keys = set(renames.keys())
    protected_keys = {"note"}
    removed_keys = {
        key for key in (old_keys - new_keys - renamed_old_keys) if key not in protected_keys
    }
    removed_keys_with_data = {
        key
        for key in removed_keys
        if any(
            isinstance(rec, dict) and rec.get(key) is not None
            for rec in pending_inventory
        )
    }
    added_keys = new_keys - old_keys

    resolved_display_key = _resolve_selector_key(
        current_value=current_display_key,
        requested_value=requested_display_key,
        renames=renames,
        allowed_keys=new_keys,
    )
    resolved_color_key = _resolve_selector_key(
        current_value=current_color_key,
        requested_value=requested_color_key,
        renames=renames,
        allowed_keys=new_keys,
    )

    pending_meta = dict(meta_dict)
    pending_meta["custom_fields"] = normalized_fields
    if resolved_display_key:
        pending_meta["display_key"] = resolved_display_key
    else:
        pending_meta.pop("display_key", None)

    if resolved_color_key:
        pending_meta["color_key"] = resolved_color_key
    else:
        pending_meta.pop("color_key", None)

    pending_meta.pop("cell_line_options", None)
    pending_meta.pop("cell_line_required", None)

    return CustomFieldsUpdateDraft(
        pending_meta=pending_meta,
        pending_inventory=pending_inventory,
        new_fields=normalized_fields,
        renames=renames,
        rename_conflicts=conflicts,
        old_keys=old_keys,
        new_keys=new_keys,
        added_keys=added_keys,
        removed_keys=removed_keys,
        removed_keys_with_data=removed_keys_with_data,
        selector_before={
            "display_key": str(current_display_key or "").strip(),
            "color_key": str(current_color_key or "").strip(),
        },
        selector_after={
            "display_key": str(pending_meta.get("display_key") or "").strip(),
            "color_key": str(pending_meta.get("color_key") or "").strip(),
        },
        stats={
            "records_total": sum(1 for rec in pending_inventory if isinstance(rec, dict)),
            "records_touched_by_rename": rename_touched_records,
        },
    )


def drop_removed_fields_from_inventory(inventory: List[Any], removed_keys: Set[str]) -> int:
    """Drop removed keys from records in-place and return touched record count."""
    if not removed_keys:
        return 0
    touched = 0
    for rec in inventory:
        if not isinstance(rec, dict):
            continue
        rec_touched = False
        for key in removed_keys:
            if key in rec:
                rec.pop(key, None)
                rec_touched = True
        if rec_touched:
            touched += 1
    return touched


def validate_custom_fields_update_draft(draft: CustomFieldsUpdateDraft):
    """Run meta-only validation for one prepared draft."""
    from .import_validation_core import validate_inventory_document

    pending_data = {
        "meta": draft.pending_meta,
        "inventory": draft.pending_inventory,
    }
    return validate_inventory_document(
        pending_data,
        skip_record_validation=True,
    )


def build_custom_fields_update_audit_details(
    draft: CustomFieldsUpdateDraft,
    *,
    removed_data_cleaned: bool,
    removed_records_count: int,
) -> Dict[str, Any]:
    """Build summary-level audit details for one custom-fields save."""
    renames = [
        {"from": old_key, "to": new_key}
        for old_key, new_key in sorted(draft.renames.items())
    ]
    return {
        "op": "edit_custom_fields",
        "added_keys": sorted(draft.added_keys),
        "removed_keys": sorted(draft.removed_keys),
        "removed_keys_with_data": sorted(draft.removed_keys_with_data),
        "renames": renames,
        "display_key_before": draft.selector_before.get("display_key") or "",
        "display_key_after": draft.selector_after.get("display_key") or "",
        "color_key_before": draft.selector_before.get("color_key") or "",
        "color_key_after": draft.selector_after.get("color_key") or "",
        "removed_data_cleaned": bool(removed_data_cleaned),
        "records_total": int(draft.stats.get("records_total") or 0),
        "records_touched_by_rename": int(draft.stats.get("records_touched_by_rename") or 0),
        "records_touched_by_remove": int(removed_records_count or 0),
        "custom_field_count_before": len(draft.old_keys),
        "custom_field_count_after": len(draft.new_keys),
    }

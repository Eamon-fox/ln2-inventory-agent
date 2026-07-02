"""
YAML file operations for LN2 inventory.

This module is the stable facade for inventory YAML I/O. It owns the load/write
core, caches, instance-identity guard, integrity validation, rollback and the
runtime legacy-migration entry points. Cohesive sub-concerns have been split
into sibling modules and are re-exported here so that every existing
``from lib.yaml_ops import X`` import keeps working unchanged:

- ``yaml_ops_paths``    -> path helpers (``_abs_path``, backup/audit dirs)
- ``yaml_ops_mojibake`` -> 乱码 (mojibake) repair on load
- ``yaml_ops_stats``    -> occupancy stats + capacity/size warnings
- ``yaml_ops_audit``    -> audit log read/append + audit-seq numbering
- ``yaml_ops_backup``   -> timestamped backup create/list/throttle/retention
"""
import contextvars
import os
import shutil
import sys
import threading
import uuid
from contextlib import contextmanager, suppress
from copy import deepcopy
from datetime import datetime
from typing import Any

import yaml
from .config import (
    YAML_PATH,
)
from .inventory_paths import (
    assert_allowed_inventory_yaml_path,
)
from .legacy_field_policy import canonicalize_legacy_document
from .schema_aliases import (
    canonicalize_inventory_document,
    expand_document_structural_aliases,
)
from .validators import format_validation_errors, validate_inventory

# ── Re-exported sub-concern APIs (import paths must stay stable) ───────────
from .yaml_ops_paths import (  # noqa: F401 - re-exported for stable import paths
    _abs_path,
    _normalize_path_for_guard,
    get_instance_audit_path,
    get_instance_backup_dir,
)
from .yaml_ops_mojibake import (  # noqa: F401 - re-exported for stable import paths
    _repair_mojibake_values,
)
from .yaml_ops_stats import (  # noqa: F401 - re-exported for stable import paths
    collect_inventory_stats,
    compute_occupancy,
    emit_capacity_warnings,
    emit_yaml_size_warning,
    get_capacity_warnings,
    get_yaml_size_warning,
)
from .yaml_ops_audit import (  # noqa: F401 - re-exported for stable import paths
    append_audit_event,
    coerce_audit_seq,
    get_audit_log_path,
    get_audit_log_paths,
    iter_audit_events_reverse,
    read_audit_events,
)
from .yaml_ops_backup import (  # noqa: F401 - re-exported for stable import paths
    create_yaml_backup,
    list_alternative_backups,
    list_yaml_backups,
)

# ── Preflight I/O cache (populated by plan_executor) ──────────────
# key = normcase(normpath(abspath(path)))
# value = deep-copied inventory data dict
# When a path is present here, load_yaml returns deepcopy(cached),
# and write_yaml updates the cache instead of writing to disk.
_preflight_cache: dict = {}

# Sentinel distinguishing "caller passed before_data=None" from "not provided".
_UNSET = object()

# ── Write-through cache (populated by plan_executor during execute) ───
# Same key scheme as _preflight_cache.
# Reads serve from cache; writes go to disk AND update cache.
_write_through_cache: dict = {}

# Read snapshot cache for batch read cycles.  A caller can wrap a group of
# read-only tool calls in ``read_snapshot_context(trace_id)``; all threads that
# enter with the same snapshot id share one loaded YAML document per path.
_read_snapshot_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "snowfox_read_snapshot_id",
    default=None,
)
_read_snapshot_caches: dict[str, dict[str, Any]] = {}
_read_snapshot_lock = threading.Lock()


def _safe_log_event(event, **fields):
    """Best-effort diagnostics logging that never breaks the caller.

    Diagnostics are optional; import or emission failures must not abort YAML
    load/write. Failures are surfaced on stderr (matching the stderr pattern
    used elsewhere in this module) instead of being silently swallowed.
    """
    try:
        from .diagnostics import log_event

        log_event(event, **fields)
    except Exception as exc:  # noqa: BLE001 - diagnostics must never be fatal
        print(f"warning: diagnostics log_event({event!r}) failed: {exc}", file=sys.stderr)


def _yaml_cache_key(path):
    return os.path.normcase(os.path.normpath(_abs_path(path)))


@contextmanager
def read_snapshot_context(snapshot_id=None):
    """Share read-only YAML loads within a batch read cycle."""

    sid = str(snapshot_id or "").strip() or f"snapshot-{uuid.uuid4().hex}"
    token = _read_snapshot_id.set(sid)
    try:
        yield sid
    finally:
        _read_snapshot_id.reset(token)


def clear_read_snapshot(snapshot_id=None):
    sid = str(snapshot_id or "").strip()
    if not sid:
        sid = _read_snapshot_id.get()
    if not sid:
        return
    with _read_snapshot_lock:
        _read_snapshot_caches.pop(sid, None)


def current_read_snapshot_id():
    """Return the active read snapshot id, if any."""

    return _read_snapshot_id.get()


def _get_read_snapshot(cache_key, *, readonly=False):
    sid = _read_snapshot_id.get()
    if not sid:
        return None, False
    with _read_snapshot_lock:
        cache = _read_snapshot_caches.get(sid) or {}
        if cache_key not in cache:
            return None, False
        cached = cache[cache_key]
        return (cached if readonly else deepcopy(cached)), True


def _put_read_snapshot(cache_key, data):
    sid = _read_snapshot_id.get()
    if not sid:
        return
    with _read_snapshot_lock:
        cache = _read_snapshot_caches.setdefault(sid, {})
        cache[cache_key] = deepcopy(data)


_VALIDATION_SCOPES = {"full", "meta_only"}


def _ensure_inventory_integrity(data, prefix="Integrity validation failed", validation_scope="full"):
    """Raise ValueError when inventory invariants are broken."""
    scope = str(validation_scope or "full").strip().lower()
    if scope not in _VALIDATION_SCOPES:
        raise ValueError(
            f"invalid validation_scope={validation_scope!r}; expected one of {sorted(_VALIDATION_SCOPES)}"
        )

    data, alias_errors = canonicalize_inventory_document(data)
    if alias_errors:
        raise ValueError(format_validation_errors(alias_errors, prefix=prefix))

    if scope == "meta_only":
        from .import_validation_core import validate_inventory_document

        errors, _warnings = validate_inventory_document(
            data,
            skip_record_validation=True,
        )
    else:
        errors, _warnings = validate_inventory(data)
    if errors:
        raise ValueError(format_validation_errors(errors, prefix=prefix))


def resolve_instance_id(yaml_path, mode="read"):
    """Resolve or create unique instance ID for a YAML file.

    The instance ID is stored in the YAML's meta.inventory_instance_id field.
    This allows tracking inventory identity even when files are moved/renamed.

    Args:
        yaml_path: Path to the YAML file
        mode: "read" or "write". In write mode, creates ID if missing.

    Returns:
        str: The instance ID (UUID format)

    Raises:
        FileNotFoundError: If file doesn't exist in write mode
    """
    yaml_abs = _abs_path(yaml_path)
    yaml_abs = assert_allowed_inventory_yaml_path(
        yaml_abs,
        must_exist=(mode in {"read", "write"}),
    )

    if mode == "read":
        if not os.path.exists(yaml_abs):
            raise FileNotFoundError(f"YAML not found: {yaml_abs}")
        try:
            # readonly: only reads meta.inventory_instance_id, never mutates.
            data = load_yaml(yaml_abs, readonly=True)
            instance_id = (data or {}).get("meta", {}).get("inventory_instance_id")
            if instance_id:
                return instance_id
            return None
        except Exception:
            return None

    elif mode == "write":
        if not os.path.exists(yaml_abs):
            raise FileNotFoundError(f"YAML not found: {yaml_abs}")

        data = load_yaml(yaml_abs)
        if not isinstance(data, dict):
            data = {"meta": {}, "inventory": []}

        meta = data.get("meta", {})
        if not isinstance(meta, dict):
            meta = {}

        instance_id = meta.get("inventory_instance_id")
        if not instance_id:
            instance_id = str(uuid.uuid4())
            meta["inventory_instance_id"] = instance_id
            data["meta"] = meta
            with open(yaml_abs, "w", encoding="utf-8") as f:
                canonical_data, _alias_errors = canonicalize_inventory_document(data)
                yaml.safe_dump(canonical_data, f, allow_unicode=True, sort_keys=False, width=120)

        return instance_id

    raise ValueError(f"Invalid mode: {mode}. Use 'read' or 'write'.")


def _apply_instance_guard(meta, current_path):
    """Apply copy/rename guard to instance identity metadata.

    Returns:
        tuple: (updated_meta, guard_info)
    """
    current_abs = _abs_path(current_path)
    current_norm = _normalize_path_for_guard(current_abs)

    updated_meta = dict(meta or {})
    raw_instance_id = str(updated_meta.get("inventory_instance_id") or "").strip()
    old_instance_id = raw_instance_id or None

    raw_origin = str(updated_meta.get("instance_origin_path") or "").strip()
    origin_abs = _abs_path(raw_origin) if raw_origin else ""
    origin_norm = _normalize_path_for_guard(origin_abs) if origin_abs else ""

    decision = "stable"
    new_instance_id = old_instance_id
    origin_before = os.path.realpath(origin_abs) if origin_abs else ""
    origin_after = os.path.realpath(current_abs)

    if not old_instance_id:
        new_instance_id = str(uuid.uuid4())
        updated_meta["inventory_instance_id"] = new_instance_id
        updated_meta["instance_origin_path"] = current_abs
    elif not origin_abs:
        # Legacy metadata without origin path: backfill from current path.
        updated_meta["instance_origin_path"] = current_abs
    elif origin_norm == current_norm:
        # Keep stored path fresh even if case/separator changed.
        updated_meta["instance_origin_path"] = current_abs
    else:
        if os.path.exists(origin_abs):
            # Source still exists -> treat as copied dataset and fork identity.
            decision = "forked_copy"
            new_instance_id = str(uuid.uuid4())
            updated_meta["inventory_instance_id"] = new_instance_id
            updated_meta["instance_origin_path"] = current_abs
        else:
            # Source missing -> treat as rename/move and keep identity.
            decision = "adopted_rename"
            updated_meta["instance_origin_path"] = current_abs

    updated_meta["instance_last_seen_at"] = datetime.now().isoformat(timespec="seconds")

    guard_info = {
        "decision": decision,
        "old_instance_id": old_instance_id or "",
        "new_instance_id": str(new_instance_id or ""),
        "origin_before": origin_before,
        "origin_after": origin_after,
    }
    return updated_meta, guard_info


def load_yaml(path=YAML_PATH, *, readonly=False):
    """Load YAML file and return data.

    Args:
        path: YAML file path.
        readonly: When ``True``, cache-served results (preflight / write-through
            / read-snapshot caches) return the *shared* in-memory document
            instead of a fresh ``deepcopy``. This avoids copying the whole
            document on hot read paths.

            CONTRACT: callers passing ``readonly=True`` MUST treat the returned
            object (and everything reachable from it) as immutable. Mutating a
            readonly result corrupts the shared cache for every other reader.
            Use the default (``readonly=False``) whenever the document will be
            edited before writing. The freshly-parsed disk path always returns a
            caller-owned object regardless of this flag.
    """
    abs_path = _abs_path(path)
    # Preflight cache: serve from memory if path is cached
    cache_key = os.path.normcase(os.path.normpath(abs_path))
    if cache_key in _preflight_cache:
        _safe_log_event("yaml.load", yaml_path=abs_path, source="preflight_cache")
        cached = _preflight_cache[cache_key]
        return cached if readonly else deepcopy(cached)
    if cache_key in _write_through_cache:
        _safe_log_event("yaml.load", yaml_path=abs_path, source="write_through_cache")
        cached = _write_through_cache[cache_key]
        return cached if readonly else deepcopy(cached)

    cached, hit = _get_read_snapshot(cache_key, readonly=readonly)
    if hit:
        _safe_log_event("yaml.load", yaml_path=abs_path, source="read_snapshot_cache")
        return cached

    try:
        from .diagnostics import span
    except Exception:
        span = None

    if span is None:
        with open(abs_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        data = _repair_mojibake_values(data)
        data = expand_document_structural_aliases(data)
        _put_read_snapshot(cache_key, data)
        return data

    with span("yaml.load", yaml_path=abs_path, source="disk"):
        with open(abs_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        data = _repair_mojibake_values(data)
        data = expand_document_structural_aliases(data)
    _put_read_snapshot(cache_key, data)
    return data


def load_yaml_raw(path=YAML_PATH):
    """Load one YAML file without expanding runtime alias views."""
    abs_path = _abs_path(path)
    with open(abs_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return _repair_mojibake_values(data)


def inspect_runtime_dataset_migration(path=YAML_PATH):
    """Inspect whether one managed dataset needs legacy auto-migration."""
    yaml_abs = assert_allowed_inventory_yaml_path(_abs_path(path), must_exist=True)
    original = load_yaml_raw(yaml_abs)
    canonical_data, alias_errors = canonicalize_inventory_document(original)
    if alias_errors:
        return {
            "ok": False,
            "path": yaml_abs,
            "error_code": "legacy_structural_alias_conflict",
            "message": format_validation_errors(
                alias_errors,
                prefix="Legacy dataset auto-migration failed",
            ),
            "data": None,
            "changed": False,
            "summary": {},
        }

    legacy_result = canonicalize_legacy_document(canonical_data)
    if not legacy_result.get("ok"):
        return {
            "ok": False,
            "path": yaml_abs,
            "error_code": str(legacy_result.get("error_code") or "legacy_migration_failed"),
            "message": str(legacy_result.get("message") or "Legacy dataset auto-migration failed."),
            "data": None,
            "changed": False,
            "summary": {},
        }

    migrated = legacy_result.get("data")
    summary = dict(legacy_result.get("summary") or {})
    summary["structural_alias_changed"] = bool(canonical_data != original)
    changed = bool(canonical_data != original or legacy_result.get("changed"))
    return {
        "ok": True,
        "path": yaml_abs,
        "data": migrated,
        "changed": changed,
        "summary": summary,
    }


def ensure_runtime_dataset_canonical(
    path=YAML_PATH,
    *,
    source="runtime.dataset_open",
):
    """Auto-migrate one managed dataset in-place before steady-state runtime use."""
    yaml_abs = assert_allowed_inventory_yaml_path(_abs_path(path), must_exist=True)
    inspection = inspect_runtime_dataset_migration(yaml_abs)
    if not inspection.get("ok"):
        raise ValueError(str(inspection.get("message") or "Legacy dataset auto-migration failed."))

    if not inspection.get("changed"):
        return {
            "path": yaml_abs,
            "changed": False,
            "backup_path": None,
            "summary": dict(inspection.get("summary") or {}),
        }

    backup_path = create_yaml_backup(yaml_abs)
    if not backup_path:
        raise RuntimeError(f"Failed to create backup before auto-migrating dataset: {yaml_abs}")

    summary = dict(inspection.get("summary") or {})
    with suppress(Exception):
        append_backup_event(
            yaml_path=yaml_abs,
            backup_path=backup_path,
            source=str(source or "runtime.dataset_open"),
            details={
                "kind": "legacy_auto_migration",
                "migration_action": "backup_before_canonicalize",
            },
        )

    audit_details = {
        "kind": "legacy_auto_migration",
        "backup_path": os.path.abspath(str(backup_path)),
        "alias_records_changed": int(summary.get("alias_records_changed") or 0),
        "alias_conflict_count": int(summary.get("alias_conflict_count") or 0),
        "structural_alias_changed": bool(summary.get("structural_alias_changed")),
        "custom_field_alias_changes": list(summary.get("custom_field_alias_changes") or []),
    }
    changed_ids = list(summary.get("alias_changed_record_ids") or [])
    if changed_ids:
        audit_details["alias_changed_record_ids"] = changed_ids

    write_yaml(
        inspection.get("data"),
        path=yaml_abs,
        auto_backup=False,
        backup_path=backup_path,
        audit_meta={
            "action": "dataset_auto_migrate_legacy",
            "source": str(source or "runtime.dataset_open"),
            "details": audit_details,
        },
    )
    return {
        "path": yaml_abs,
        "changed": True,
        "backup_path": os.path.abspath(str(backup_path)),
        "summary": summary,
    }


def append_backup_event(
    yaml_path,
    backup_path,
    source="lib.tool_api_write_validation.resolve_request_backup_path",
    details=None,
):
    backup_abs = str(backup_path or "").strip()
    if not backup_abs:
        raise ValueError("backup_path is required for append_backup_event")
    backup_abs = _abs_path(backup_abs)

    current_data = None
    try:
        # readonly: consumed only as audit before/after snapshot (meta reads).
        current_data = load_yaml(yaml_path, readonly=True)
    except Exception:
        current_data = None

    meta = {
        "action": "backup",
        "source": str(source or "backup"),
    }
    detail_payload = {"kind": "request_backup"}
    if isinstance(details, dict):
        detail_payload.update({str(k): v for k, v in details.items()})
    meta["details"] = detail_payload

    return append_audit_event(
        yaml_path=yaml_path,
        before_data=current_data,
        after_data=current_data,
        backup_path=backup_abs,
        warnings=[],
        audit_meta=meta,
    )


def write_yaml(
    data,
    path=YAML_PATH,
    auto_backup=True,
    backup_path=None,
    audit_meta=None,
    validation_scope="full",
    before_data=_UNSET,
):
    """Write data to YAML file.

    Args:
        data: Inventory data dict
        path: YAML output path
        auto_backup: Whether to create backup before overwrite
        backup_path: Optional pre-created backup path reference. When provided,
            no new backup is created by this function and this path is returned
            to caller as the effective backup reference.
        audit_meta: Optional dict for audit fields.
            Common keys: action/source/details, plus session_id, trace_id,
            tool_name, tool_input, status, error.
        validation_scope: ``"full"`` (default) validates full record invariants;
            ``"meta_only"`` validates metadata/schema and undeclared-field
            constraints while skipping per-record value checks.
        before_data: Optional pre-write snapshot the caller already loaded.
            When provided, ``write_yaml`` skips reloading the previous document
            from disk. The snapshot is consumed read-only: only
            ``meta.inventory_instance_id`` is read from it and it is forwarded to
            the audit event (which likewise only reads meta), so passing an
            already-normalized in-memory copy keeps backup/audit behavior
            identical while avoiding a duplicate disk load.
    """
    yaml_abs = assert_allowed_inventory_yaml_path(_abs_path(path))
    canonical_data, alias_errors = canonicalize_inventory_document(data)
    if alias_errors:
        raise ValueError(
            format_validation_errors(alias_errors, prefix="Integrity validation failed")
        )
    data = canonical_data
    legacy_result = canonicalize_legacy_document(data)
    if not legacy_result.get("ok"):
        raise ValueError(str(legacy_result.get("message") or "Failed to canonicalize legacy fields"))
    data = legacy_result.get("data")

    # Preflight cache: store in memory instead of writing to disk
    cache_key = os.path.normcase(os.path.normpath(yaml_abs))
    if cache_key in _preflight_cache:
        _preflight_cache[cache_key] = deepcopy(data)
        _safe_log_event(
            "yaml.write",
            yaml_path=yaml_abs,
            source="preflight_cache",
            auto_backup=bool(auto_backup),
            validation_scope=validation_scope,
        )
        return None
    _ensure_inventory_integrity(
        data,
        prefix="Integrity validation failed",
        validation_scope=validation_scope,
    )

    existing_instance_id = None
    if before_data is _UNSET:
        before_data = None
        if os.path.exists(yaml_abs):
            try:
                # readonly: only meta.inventory_instance_id + audit meta reads.
                before_data = load_yaml(yaml_abs, readonly=True)
            except Exception as exc:
                print(f"warning: failed to load existing YAML before write: {exc}", file=sys.stderr)
    existing_instance_id = (
        (before_data or {}).get("meta", {}).get("inventory_instance_id")
        if isinstance(before_data, dict)
        else None
    )

    if not isinstance(data, dict):
        data = {"meta": {}, "inventory": []}
    meta = data.get("meta", {})
    if not isinstance(meta, dict):
        meta = {}

    # Prefer identity from current file on disk when present; this keeps normal
    # in-place writes stable even if caller omitted metadata.
    if existing_instance_id and not str(meta.get("inventory_instance_id") or "").strip():
        meta["inventory_instance_id"] = str(existing_instance_id)

    meta, guard_info = _apply_instance_guard(meta, yaml_abs)
    data["meta"] = meta
    instance_id = str(meta.get("inventory_instance_id") or "").strip()

    effective_backup_path = None
    raw_backup = str(backup_path or "").strip()
    if raw_backup:
        effective_backup_path = _abs_path(raw_backup)
    elif auto_backup:
        try:
            effective_backup_path = create_yaml_backup(
                yaml_abs,
                instance_id_override=instance_id,
            )
            if effective_backup_path:
                print(f"backup created: {effective_backup_path}")
        except Exception as exc:
            print(f"warning: failed to create backup: {exc}", file=sys.stderr)

    try:
        from .diagnostics import span
    except Exception:
        span = None

    if span is None:
        with open(yaml_abs, "w", encoding="utf-8") as f:
            yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False, width=120)
    else:
        with span(
            "yaml.write",
            yaml_path=yaml_abs,
            source="disk",
            auto_backup=bool(auto_backup),
            validation_scope=validation_scope,
        ):
            with open(yaml_abs, "w", encoding="utf-8") as f:
                yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False, width=120)

    # Update write-through cache if active
    if cache_key in _write_through_cache:
        _write_through_cache[cache_key] = deepcopy(data)

    warnings = []
    warnings.extend(emit_capacity_warnings(data))
    size_warning = emit_yaml_size_warning(path=yaml_abs)
    if size_warning:
        warnings.append(size_warning)

    effective_audit_meta = dict(audit_meta or {})
    if guard_info.get("decision") in {"forked_copy", "adopted_rename"}:
        details = dict(effective_audit_meta.get("details") or {})
        details.update(
            {
                "instance_guard_decision": guard_info.get("decision"),
                "instance_guard_old_id": guard_info.get("old_instance_id"),
                "instance_guard_new_id": guard_info.get("new_instance_id"),
                "instance_guard_origin_path_before": guard_info.get("origin_before"),
                "instance_guard_origin_path_after": guard_info.get("origin_after"),
            }
        )
        effective_audit_meta["details"] = details

    try:
        append_audit_event(
            yaml_path=yaml_abs,
            before_data=before_data,
            after_data=data,
            backup_path=None,
            warnings=warnings,
            audit_meta=effective_audit_meta,
        )
    except Exception as exc:
        print(f"warning: failed to append audit log: {exc}", file=sys.stderr)

    return effective_backup_path


def validate_backup_file(backup_path: str) -> dict:
    """Validate a backup file for rollback readiness.

    Checks file existence, readability, non-empty content, valid YAML
    structure, and inventory integrity constraints.

    Returns:
        dict with keys:
            valid (bool): True if backup passes all checks.
            error (str|None): Human-readable error when invalid.
            error_code (str|None): Machine-readable code when invalid.
            data (dict|None): Parsed YAML data when valid.
    """
    abs_path = _abs_path(backup_path)

    if not os.path.exists(abs_path):
        return {
            "valid": False,
            "error": f"Backup file not found: {abs_path}",
            "error_code": "backup_not_found",
            "data": None,
        }

    if not os.path.isfile(abs_path):
        return {
            "valid": False,
            "error": f"Backup path is not a file: {abs_path}",
            "error_code": "backup_not_file",
            "data": None,
        }

    try:
        file_size = os.path.getsize(abs_path)
    except OSError as exc:
        return {
            "valid": False,
            "error": f"Cannot read backup file: {exc}",
            "error_code": "backup_unreadable",
            "data": None,
        }

    if file_size == 0:
        return {
            "valid": False,
            "error": f"Backup file is empty (0 bytes): {os.path.basename(abs_path)}",
            "error_code": "backup_empty",
            "data": None,
        }

    try:
        data = load_yaml(abs_path)
    except Exception as exc:
        return {
            "valid": False,
            "error": f"Backup file is not valid YAML: {exc}",
            "error_code": "backup_parse_failed",
            "data": None,
        }

    if not isinstance(data, dict):
        return {
            "valid": False,
            "error": f"Backup file does not contain a YAML mapping (got {type(data).__name__})",
            "error_code": "backup_invalid_structure",
            "data": None,
        }

    if "inventory" not in data:
        return {
            "valid": False,
            "error": "Backup file missing required 'inventory' key",
            "error_code": "backup_missing_inventory",
            "data": None,
        }

    try:
        legacy_result = canonicalize_legacy_document(data)
        if not legacy_result.get("ok"):
            raise ValueError(str(legacy_result.get("message") or "Failed to canonicalize legacy fields"))
        data = legacy_result.get("data")
        _ensure_inventory_integrity(
            data,
            prefix=f"Backup integrity check failed ({os.path.basename(abs_path)})",
        )
    except ValueError as exc:
        return {
            "valid": False,
            "error": str(exc),
            "error_code": "backup_integrity_failed",
            "data": None,
        }

    return {"valid": True, "error": None, "error_code": None, "data": data}


def rollback_yaml(
    path=YAML_PATH,
    backup_path=None,
    request_backup_path=None,
    audit_meta=None,
):
    """Rollback YAML to latest (or specified) backup.

    Returns:
        dict: restored_from, snapshot_before_rollback
    """
    yaml_abs = assert_allowed_inventory_yaml_path(_abs_path(path), must_exist=True)
    if not os.path.exists(yaml_abs):
        raise FileNotFoundError(f"YAML not found: {yaml_abs}")

    backups = list_yaml_backups(yaml_abs)
    if backup_path is not None:
        target_backup = _abs_path(backup_path)
    else:
        if not backups:
            raise RuntimeError("没有可用备份可回滚")
        target_backup = backups[0]

    # Validate backup file before attempting rollback
    validation = validate_backup_file(target_backup)
    if not validation["valid"]:
        alternatives = list_alternative_backups(yaml_abs, exclude_path=target_backup)
        error_msg = validation["error"]
        if alternatives:
            alt_names = [os.path.basename(a["path"]) for a in alternatives[:3]]
            error_msg += f" | Available alternatives: {', '.join(alt_names)}"
        raise RuntimeError(error_msg)

    backup_data = validation["data"]

    # readonly: before_data is only consumed as an audit snapshot (meta reads).
    before_data = load_yaml(yaml_abs, readonly=True)

    pre_rollback_snapshot = str(request_backup_path or "").strip() or None
    if pre_rollback_snapshot:
        pre_rollback_snapshot = _abs_path(pre_rollback_snapshot)
    shutil.copy2(target_backup, yaml_abs)

    after_data = deepcopy(backup_data)
    cache_key = os.path.normcase(os.path.normpath(yaml_abs))
    if cache_key in _write_through_cache:
        _write_through_cache[cache_key] = deepcopy(after_data)
    if cache_key in _preflight_cache:
        _preflight_cache[cache_key] = deepcopy(after_data)

    warnings = []
    warnings.extend(emit_capacity_warnings(after_data))
    size_warning = emit_yaml_size_warning(path=yaml_abs)
    if size_warning:
        warnings.append(size_warning)

    meta = dict(audit_meta or {})
    meta.setdefault("action", "rollback")
    meta.setdefault("source", "lib.yaml_ops.rollback_yaml")
    details = dict(meta.get("details") or {})
    details.update(
        {
            "restored_from": target_backup,
            "snapshot_before_rollback": pre_rollback_snapshot,
        }
    )
    meta["details"] = details

    append_audit_event(
        yaml_path=yaml_abs,
        before_data=before_data,
        after_data=after_data,
        backup_path=pre_rollback_snapshot,
        warnings=warnings,
        audit_meta=meta,
    )

    return {
        "restored_from": target_backup,
        "snapshot_before_rollback": pre_rollback_snapshot,
    }

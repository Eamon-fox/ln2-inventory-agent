"""
YAML file operations for LN2 inventory
"""
import getpass
import hashlib
import json
import os
import shutil
import socket
import sys
import uuid
from contextlib import suppress
from datetime import datetime
from typing import Any

import yaml
from .config import (
    AUDIT_DIR,
    AUDIT_LOG_FILE,
    BACKUP_DIR,
    BACKUP_DIR_NAME,
    BACKUP_KEEP_COUNT,
    BOX_EMPTY_WARNING_THRESHOLD,
    TOTAL_EMPTY_WARNING_THRESHOLD,
    YAML_PATH,
    YAML_SIZE_WARNING_MB,
)
from .position_fmt import get_box_numbers, get_total_slots
from .validators import format_validation_errors, validate_inventory

_COMMON_CJK_CHARS = set(
    "\u7684\u4e00\u662f\u5728\u4e0d\u4e86\u6709\u548c\u4eba\u8fd9\u4e2d\u5927\u4e0a\u4e2a\u56fd"
    "\u6211\u4ee5\u8981\u4ed6\u65f6\u6765\u7528\u4eec\u5230\u4f5c\u5730\u4e8e\u51fa\u5c31\u5206\u5bf9"
    "\u6210\u4f1a\u53ef\u4e3b\u53d1\u5e74\u52a8\u540c\u5de5\u4e5f\u80fd\u4e0b\u8fc7\u5b50\u8bf4\u4ea7"
    "\u79cd\u9762\u800c\u65b9\u540e\u591a\u5b9a\u884c\u5b66\u6cd5\u6240\u6c11\u5f97\u7ecf"
)

_MOJIBAKE_SOURCE_ENCODINGS = ("gb18030", "gbk", "cp936")
_MOJIBAKE_MARKER_CHARS = set("\u95c4\u7039\u951b\u9350\u93b4\u935a\u7ec9\u93bf\u7481\u9286\u93c4\u9225\u7f01\u9428\u5a13\u9359\u5bee\u6fb6\u6d63")
_AUDIT_SCHEMA_VERSION = "trace-session-v1"
_AUDIT_SCHEMA_MARKER_FILE = os.path.join(AUDIT_DIR, ".audit_schema_version")
_AUDIT_SCHEMA_READY = False


def _ensure_inventory_integrity(data, prefix="完整性校验失败"):
    """Raise ValueError when inventory invariants are broken."""
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
    
    if mode == "read":
        if not os.path.exists(yaml_abs):
            raise FileNotFoundError(f"YAML not found: {yaml_abs}")
        try:
            data = load_yaml(yaml_abs)
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
                yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False, width=120)
        
        return instance_id
    
    raise ValueError(f"Invalid mode: {mode}. Use 'read' or 'write'.")


def get_instance_backup_dir(yaml_path):
    """Return the backup directory for a specific inventory instance.
    
    Returns:
        str: Path like <BACKUP_DIR>/<instance_id>/
    """
    yaml_abs = _abs_path(yaml_path)
    instance_id = resolve_instance_id(yaml_abs, mode="read")
    if instance_id:
        return os.path.join(BACKUP_DIR, instance_id)
    
    stem = os.path.splitext(os.path.basename(yaml_abs))[0] or "inventory"
    return os.path.join(BACKUP_DIR, f"legacy-{stem}")


def get_instance_audit_path(yaml_path):
    """Return the audit log path for a specific inventory instance.
    
    Returns:
        str: Path like <AUDIT_DIR>/<instance_id>.audit.jsonl
    """
    yaml_abs = _abs_path(yaml_path)
    instance_id = resolve_instance_id(yaml_abs, mode="read")
    if instance_id:
        return os.path.join(AUDIT_DIR, f"{instance_id}.audit.jsonl")

    # Legacy files without instance_id can collide by stem (e.g. many
    # inventory.yaml files in different directories). Use a stable path hash to
    # keep per-dataset isolation while still supporting reads from old stem-only
    # paths.
    stem = os.path.splitext(os.path.basename(yaml_abs))[0] or "inventory"
    digest = hashlib.sha1(yaml_abs.encode("utf-8")).hexdigest()[:10]
    return os.path.join(AUDIT_DIR, f"legacy-{stem}-{digest}.audit.jsonl")


def _abs_path(path):
    """Return absolute filesystem path."""
    return os.path.abspath(os.fspath(path if path is not None else YAML_PATH))


def _normalize_path_for_guard(path):
    """Normalize path for guard comparisons across case/slash variants."""
    return os.path.normcase(os.path.normpath(_abs_path(path)))


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
    origin_before = origin_abs or ""
    origin_after = current_abs

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


def _text_readability_score(text: str) -> float:
    if not text:
        return float("-inf")

    common = 0
    cjk_basic = 0
    cjk_rare = 0
    private_use = 0
    ascii_printable = 0
    chinese_punct = 0
    question_marks = 0

    for ch in text:
        code = ord(ch)
        if 0x4E00 <= code <= 0x9FFF:
            cjk_basic += 1
            if ch in _COMMON_CJK_CHARS:
                common += 1
        elif 0x3400 <= code <= 0x4DBF or 0x20000 <= code <= 0x2FA1F:
            cjk_rare += 1
        elif 0xE000 <= code <= 0xF8FF:
            private_use += 1
        elif 0x20 <= code <= 0x7E:
            ascii_printable += 1
        elif ch in "，。！？：；、“”‘’（）《》【】—…":
            chinese_punct += 1

        if ch == "?":
            question_marks += 1

    return (
        common * 3.0
        + cjk_basic * 0.45
        + ascii_printable * 0.12
        + chinese_punct * 0.35
        - cjk_rare * 1.9
        - private_use * 2.4
        - question_marks * 0.8
    )


def _marker_count(text: str) -> int:
    return sum(1 for ch in (text or "") if ch in _MOJIBAKE_MARKER_CHARS)


def _is_probable_mojibake_upgrade(source: str, candidate: str, source_score: float, candidate_score: float) -> bool:
    src_markers = _marker_count(source)
    if src_markers <= 0:
        return False

    cand_markers = _marker_count(candidate)
    # Candidate should remove at least one suspicious marker and not make readability much worse.
    if cand_markers >= src_markers:
        return False
    return candidate_score >= source_score - 0.6


def _repair_mojibake_text(value: str) -> str:
    text = str(value or "")
    if not text:
        return text
    if len(text) < 4:
        return text
    if all(ord(ch) < 128 for ch in text):
        return text

    best = text
    best_score = _text_readability_score(text)

    for _ in range(2):
        improved = False
        for enc in _MOJIBAKE_SOURCE_ENCODINGS:
            try:
                raw = best.encode(enc)
                candidate = raw.decode("utf-8")
            except UnicodeError:
                continue
            if not candidate or candidate == best:
                continue

            candidate_score = _text_readability_score(candidate)
            # Require a small margin to avoid rewriting already-good strings.
            # For true UTF8->GBK mojibake, candidate existence is already a strong signal.
            if (
                candidate_score > best_score + 0.35
                or _is_probable_mojibake_upgrade(best, candidate, best_score, candidate_score)
            ):
                best = candidate
                best_score = candidate_score
                improved = True

        if not improved:
            break

    return best


def _repair_mojibake_values(node: Any) -> Any:
    if isinstance(node, dict):
        return {key: _repair_mojibake_values(value) for key, value in node.items()}
    if isinstance(node, list):
        return [_repair_mojibake_values(value) for value in node]
    if isinstance(node, str):
        return _repair_mojibake_text(node)
    return node


def load_yaml(path=YAML_PATH):
    """Load YAML file and return data."""
    abs_path = _abs_path(path)
    with open(abs_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return _repair_mojibake_values(data)


def _backup_dir(yaml_path, instance_id_override=None):
    """Return the backup directory for a YAML file (instance-based)."""
    if instance_id_override:
        return os.path.join(BACKUP_DIR, str(instance_id_override))
    return get_instance_backup_dir(yaml_path)


def list_yaml_backups(yaml_path=YAML_PATH, limit=None):
    """List backups for a YAML file, newest first.
    
    Searches in the instance-based backup directory. Also checks legacy
    backup locations (both old per-file and new centralized) for backward compatibility.
    """
    yaml_abs = _abs_path(yaml_path)
    
    backups = []
    instance_id = resolve_instance_id(yaml_abs, mode="read")
    
    if instance_id:
        backup_dir = get_instance_backup_dir(yaml_abs)
        if os.path.isdir(backup_dir):
            for name in os.listdir(backup_dir):
                if name.endswith(".bak"):
                    backups.append(os.path.join(backup_dir, name))
    else:
        legacy_stem_dir = get_instance_backup_dir(yaml_abs)
        if os.path.isdir(legacy_stem_dir):
            for name in os.listdir(legacy_stem_dir):
                if name.endswith(".bak"):
                    backups.append(os.path.join(legacy_stem_dir, name))
    
    legacy_dir = os.path.join(os.path.dirname(yaml_abs), BACKUP_DIR_NAME)
    if os.path.isdir(legacy_dir):
        base = os.path.basename(yaml_abs)
        for name in os.listdir(legacy_dir):
            if name.startswith(f"{base}.") and name.endswith(".bak"):
                backups.append(os.path.join(legacy_dir, name))

    backups.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    if limit is not None:
        return backups[: max(0, int(limit))]
    return backups


def create_yaml_backup(yaml_path=YAML_PATH, keep=BACKUP_KEEP_COUNT, instance_id_override=None):
    """Create timestamped backup for current YAML file.

    Returns:
        str|None: backup path if source exists, else None
    """
    src = _abs_path(yaml_path)
    if not os.path.exists(src):
        return None

    backup_dir = _backup_dir(src, instance_id_override=instance_id_override)
    os.makedirs(backup_dir, exist_ok=True)

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    base = os.path.basename(src)
    backup_path = os.path.join(backup_dir, f"{base}.{stamp}.bak")

    i = 1
    while os.path.exists(backup_path):
        backup_path = os.path.join(backup_dir, f"{base}.{stamp}.{i}.bak")
        i += 1

    shutil.copy2(src, backup_path)

    if keep is not None and keep > 0:
        old_backups = list_yaml_backups(src)
        for old in old_backups[keep:]:
            with suppress(OSError):
                os.remove(old)

    return backup_path


def _audit_log_path(yaml_path):
    return get_audit_log_path(yaml_path)


def _ensure_audit_schema_ready():
    """Hard-cut audit schema and clear legacy rows when version changes."""
    global _AUDIT_SCHEMA_READY
    if _AUDIT_SCHEMA_READY:
        return

    os.makedirs(AUDIT_DIR, exist_ok=True)

    existing_version = ""
    with suppress(OSError, UnicodeDecodeError):
        with open(_AUDIT_SCHEMA_MARKER_FILE, "r", encoding="utf-8") as f:
            existing_version = str(f.read() or "").strip()

    if existing_version != _AUDIT_SCHEMA_VERSION:
        with suppress(OSError):
            for entry in os.listdir(AUDIT_DIR):
                candidate = os.path.join(AUDIT_DIR, entry)
                if not os.path.isfile(candidate):
                    continue
                if entry.endswith(".audit.jsonl") or entry == AUDIT_LOG_FILE:
                    with suppress(OSError):
                        os.remove(candidate)
        with suppress(OSError):
            with open(_AUDIT_SCHEMA_MARKER_FILE, "w", encoding="utf-8") as f:
                f.write(_AUDIT_SCHEMA_VERSION)

    _AUDIT_SCHEMA_READY = True


def get_audit_log_path(yaml_path=YAML_PATH):
    """Return per-inventory audit log path in centralized audit directory."""
    _ensure_audit_schema_ready()
    return get_instance_audit_path(yaml_path)


def get_audit_log_paths(yaml_path=YAML_PATH):
    """Return canonical audit log path list for the active schema."""
    return [get_audit_log_path(yaml_path)]


def read_audit_events(yaml_path=YAML_PATH, limit=None):
    """Read audit events for a YAML file from the active schema path."""
    yaml_abs = _abs_path(yaml_path)

    events = []
    path = get_audit_log_path(yaml_abs)
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        event = json.loads(line)
                    except Exception:
                        continue
                    event_yaml = event.get("yaml_path")
                    if isinstance(event_yaml, str) and event_yaml.strip():
                        try:
                            if _abs_path(event_yaml) != yaml_abs:
                                continue
                        except Exception:
                            continue
                    events.append(event)
        except Exception:
            pass

    # Keep chronological order so callers can reliably use events[-1] as latest.
    events.sort(key=lambda e: str(e.get("timestamp", "")))
    if limit is not None:
        return events[: max(0, int(limit))]
    return events


def compute_occupancy(records):
    """
    Compute occupied positions from inventory records.

    Args:
        records: List of inventory records

    Returns:
        Dict mapping box number (as string) to sorted list of occupied positions
    """
    occupied = {}
    for rec in records:
        box = rec.get("box")
        if box is None:
            continue
        box = str(box)
        occupied.setdefault(box, set())
        position = rec.get("position")
        if position is not None:
            occupied[box].add(int(position))
    return {k: sorted(v) for k, v in sorted(occupied.items(), key=lambda x: int(x[0]))}


def collect_inventory_stats(data):
    """Collect compact occupancy stats for warnings/audit."""
    records = (data or {}).get("inventory", []) if isinstance(data, dict) else []
    layout = (data or {}).get("meta", {}).get("box_layout", {})
    per_box_total = get_total_slots(layout)
    box_numbers = get_box_numbers(layout)
    total_slots = per_box_total * len(box_numbers)

    occupancy = compute_occupancy(records)
    boxes = {}
    total_occupied = 0

    for box_num in box_numbers:
        key = str(box_num)
        occupied = len(occupancy.get(key, []))
        empty = max(per_box_total - occupied, 0)
        boxes[key] = {"occupied": occupied, "empty": empty, "total": per_box_total}
        total_occupied += occupied

    total_empty = max(total_slots - total_occupied, 0)

    return {
        "record_count": len(records),
        "total_slots": total_slots,
        "total_occupied": total_occupied,
        "total_empty": total_empty,
        "boxes": boxes,
    }


def get_capacity_warnings(
    data,
    total_empty_threshold=TOTAL_EMPTY_WARNING_THRESHOLD,
    box_empty_threshold=BOX_EMPTY_WARNING_THRESHOLD,
):
    """Return capacity warning messages based on thresholds."""
    stats = collect_inventory_stats(data)
    warnings = []

    total_empty = stats["total_empty"]
    if total_empty <= int(total_empty_threshold):
        warnings.append(
            f"容量预警: 全罐仅剩 {total_empty} 个空位 (阈值 {total_empty_threshold})"
        )

    for box_key, box_stats in stats["boxes"].items():
        box_empty = box_stats["empty"]
        if box_empty <= int(box_empty_threshold):
            warnings.append(
                f"容量预警: 盒子 {box_key} 仅剩 {box_empty} 个空位 (阈值 {box_empty_threshold})"
            )

    return warnings


def emit_capacity_warnings(
    data,
    total_empty_threshold=TOTAL_EMPTY_WARNING_THRESHOLD,
    box_empty_threshold=BOX_EMPTY_WARNING_THRESHOLD,
):
    """Print capacity warnings and return warning strings."""
    warnings = get_capacity_warnings(
        data,
        total_empty_threshold=total_empty_threshold,
        box_empty_threshold=box_empty_threshold,
    )
    for msg in warnings:
        print(f"[WARN] {msg}")
    return warnings


def get_yaml_size_warning(path=YAML_PATH, warn_mb=YAML_SIZE_WARNING_MB):
    """Return file-size warning message if YAML grows too large."""
    yaml_abs = _abs_path(path)
    if not os.path.exists(yaml_abs):
        return None

    size_bytes = os.path.getsize(yaml_abs)
    size_mb = size_bytes / (1024 * 1024)
    threshold = float(warn_mb)

    if size_mb < threshold:
        return None

    return (
        f"文件体积预警: {os.path.basename(yaml_abs)} 当前 {size_mb:.2f} MB "
        f"(阈值 {threshold:.1f} MB)，建议归档长期不活动记录"
    )


def emit_yaml_size_warning(path=YAML_PATH, warn_mb=YAML_SIZE_WARNING_MB):
    """Print file-size warning and return warning string or None."""
    warning = get_yaml_size_warning(path=path, warn_mb=warn_mb)
    if warning:
        print(f"⚠️  {warning}")
    return warning


def _serialize_record(rec):
    return json.dumps(rec, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _sorted_ids(values):
    return sorted(values, key=lambda v: str(v))


def _diff_record_ids(before_records, after_records):
    before = {}
    for rec in before_records or []:
        rec_id = rec.get("id")
        if rec_id is not None:
            before[rec_id] = _serialize_record(rec)

    after = {}
    for rec in after_records or []:
        rec_id = rec.get("id")
        if rec_id is not None:
            after[rec_id] = _serialize_record(rec)

    before_ids = set(before.keys())
    after_ids = set(after.keys())

    added = _sorted_ids(after_ids - before_ids)
    removed = _sorted_ids(before_ids - after_ids)
    updated = _sorted_ids(
        rec_id for rec_id in (before_ids & after_ids) if before[rec_id] != after[rec_id]
    )

    return {
        "added": added,
        "removed": removed,
        "updated": updated,
    }


def _delta_stats(before_stats, after_stats):
    if not before_stats or not after_stats:
        return None
    return {
        "record_count": after_stats["record_count"] - before_stats["record_count"],
        "total_occupied": after_stats["total_occupied"] - before_stats["total_occupied"],
        "total_empty": after_stats["total_empty"] - before_stats["total_empty"],
    }


def _append_audit_event(yaml_path, event):
    log_path = _audit_log_path(yaml_path)
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False, sort_keys=True))
        f.write("\n")
    return log_path


def _build_audit_event(
    yaml_path,
    before_data,
    after_data,
    backup_path,
    warnings,
    audit_meta,
):
    before_stats = collect_inventory_stats(before_data) if isinstance(before_data, dict) else None
    after_stats = collect_inventory_stats(after_data) if isinstance(after_data, dict) else None
    before_records = before_data.get("inventory", []) if isinstance(before_data, dict) else []
    after_records = after_data.get("inventory", []) if isinstance(after_data, dict) else []
    changed_ids = _diff_record_ids(before_records, after_records)

    yaml_abs = _abs_path(yaml_path)
    size_bytes = os.path.getsize(yaml_abs) if os.path.exists(yaml_abs) else None
    size_mb = (size_bytes / (1024 * 1024)) if size_bytes is not None else None

    meta = dict(audit_meta or {})
    details = meta.get("details")
    after_meta = after_data.get("meta", {}) if isinstance(after_data, dict) else {}
    before_meta = before_data.get("meta", {}) if isinstance(before_data, dict) else {}
    inventory_instance_id = (
        (after_meta.get("inventory_instance_id") if isinstance(after_meta, dict) else None)
        or (before_meta.get("inventory_instance_id") if isinstance(before_meta, dict) else None)
    )

    session_id = meta.get("session_id") or f"session-{datetime.now().strftime('%Y%m%d%H%M%S')}"
    trace_id = meta.get("trace_id") or f"trace-{uuid.uuid4().hex}"
    tool_name = meta.get("tool_name")
    tool_input = meta.get("tool_input")
    status = meta.get("status") or "success"
    error = meta.get("error")

    event = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "user": getpass.getuser(),
        "host": socket.gethostname(),
        "action": meta.get("action", "write_yaml"),
        "source": meta.get("source", "lib.yaml_ops.write_yaml"),
        "session_id": session_id,
        "trace_id": trace_id,
        "inventory_instance_id": inventory_instance_id,
        "tool_name": tool_name,
        "tool_input": tool_input,
        "status": status,
        "error": error,
        "yaml_path": yaml_abs,
        "backup_path": backup_path,
        "size_bytes": size_bytes,
        "size_mb": round(size_mb, 4) if size_mb is not None else None,
        "warnings": warnings or [],
        "before": before_stats,
        "after": after_stats,
        "delta": _delta_stats(before_stats, after_stats),
        "changed_ids": changed_ids,
        "details": details,
    }
    return event


def append_audit_event(
    yaml_path,
    before_data=None,
    after_data=None,
    backup_path=None,
    warnings=None,
    audit_meta=None,
):
    """Append one audit event and return the audit log path."""
    event = _build_audit_event(
        yaml_path=yaml_path,
        before_data=before_data,
        after_data=after_data,
        backup_path=backup_path,
        warnings=warnings,
        audit_meta=audit_meta,
    )
    return _append_audit_event(yaml_path, event)


def write_yaml(
    data,
    path=YAML_PATH,
    auto_backup=True,
    backup_path=None,
    audit_meta=None,
):
    """Write data to YAML file.

    Args:
        data: Inventory data dict
        path: YAML output path
        auto_backup: Whether to create backup before overwrite
        backup_path: Optional pre-created backup path reference. When provided,
            no new backup is created by this function and this path is attached
            to audit events/return payload.
        audit_meta: Optional dict for audit fields.
            Common keys: action/source/details, plus session_id, trace_id,
            tool_name, tool_input, status, error.
    """
    yaml_abs = _abs_path(path)

    _ensure_inventory_integrity(data, prefix="完整性校验失败")

    existing_instance_id = None
    before_data = None
    if os.path.exists(yaml_abs):
        try:
            before_data = load_yaml(yaml_abs)
            existing_instance_id = (before_data or {}).get("meta", {}).get("inventory_instance_id")
        except Exception as exc:
            print(f"warning: failed to load existing YAML before write: {exc}", file=sys.stderr)

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

    with open(yaml_abs, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False, width=120)

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
            backup_path=effective_backup_path,
            warnings=warnings,
            audit_meta=effective_audit_meta,
        )
    except Exception as exc:
        print(f"warning: failed to append audit log: {exc}", file=sys.stderr)

    return effective_backup_path


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
    yaml_abs = _abs_path(path)
    if not os.path.exists(yaml_abs):
        raise FileNotFoundError(f"YAML not found: {yaml_abs}")

    backups = list_yaml_backups(yaml_abs)
    if backup_path is not None:
        target_backup = _abs_path(backup_path)
    else:
        if not backups:
            raise RuntimeError("没有可用备份可回滚")
        target_backup = backups[0]

    if not os.path.exists(target_backup):
        raise FileNotFoundError(f"备份不存在: {target_backup}")

    backup_data = load_yaml(target_backup)
    _ensure_inventory_integrity(
        backup_data,
        prefix=f"回滚被阻止：目标备份不满足完整性约束 ({os.path.basename(target_backup)})",
    )

    before_data = load_yaml(yaml_abs)

    pre_rollback_snapshot = str(request_backup_path or "").strip() or None
    if pre_rollback_snapshot:
        pre_rollback_snapshot = _abs_path(pre_rollback_snapshot)
    shutil.copy2(target_backup, yaml_abs)

    after_data = load_yaml(yaml_abs)

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

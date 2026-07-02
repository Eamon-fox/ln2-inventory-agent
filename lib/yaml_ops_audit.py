"""Audit log read/append and audit-sequence numbering.

Owns the append-only audit event log for each managed dataset: locating the
log path, reading events (forward and reverse), computing the next monotonic
``audit_seq``, and building/appending event payloads. These helpers are
self-contained and never load the inventory YAML itself; callers that need a
before/after snapshot pass it in (see ``lib.yaml_ops.append_backup_event``).
"""
import json
import os
import uuid
from datetime import datetime

from .config import YAML_PATH
from .inventory_paths import assert_allowed_inventory_yaml_path
from .yaml_ops_paths import _abs_path, get_instance_audit_path


def _audit_log_path(yaml_path):
    return get_audit_log_path(yaml_path)


def get_audit_log_path(yaml_path=YAML_PATH):
    """Return per-inventory audit log path in dataset-local audit directory."""
    managed_yaml = assert_allowed_inventory_yaml_path(yaml_path)
    return get_instance_audit_path(managed_yaml)


def get_audit_log_paths(yaml_path=YAML_PATH):
    """Return canonical audit log path list for the active schema."""
    return [get_audit_log_path(yaml_path)]


def read_audit_events(yaml_path=YAML_PATH, limit=None):
    """Read audit events for a YAML file from the active schema path."""
    yaml_abs = _abs_path(yaml_path)
    yaml_abs = assert_allowed_inventory_yaml_path(yaml_abs)

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

    # Keep file append order so callers can reliably use events[-1] as latest.
    if limit is not None:
        return events[: max(0, int(limit))]
    return events


def _iter_jsonl_lines_reverse(path, chunk_size=64 * 1024):
    """Yield non-empty JSONL lines from the end of a file without loading it all."""
    if not os.path.exists(path):
        return

    try:
        with open(path, "rb") as handle:
            handle.seek(0, os.SEEK_END)
            position = handle.tell()
            pending = b""

            while position > 0:
                read_size = min(int(chunk_size), position)
                position -= read_size
                handle.seek(position)
                pending = handle.read(read_size) + pending
                lines = pending.split(b"\n")
                pending = lines[0]
                for raw_line in reversed(lines[1:]):
                    raw_line = raw_line.strip()
                    if raw_line:
                        yield raw_line.decode("utf-8", errors="replace")

            pending = pending.strip()
            if pending:
                yield pending.decode("utf-8", errors="replace")
    except Exception:
        return


def iter_audit_events_reverse(yaml_path=YAML_PATH):
    """Yield audit events newest-first from the active schema path."""
    yaml_abs = _abs_path(yaml_path)
    yaml_abs = assert_allowed_inventory_yaml_path(yaml_abs)
    path = get_audit_log_path(yaml_abs)
    if not os.path.exists(path):
        return

    for line in _iter_jsonl_lines_reverse(path):
        try:
            event = json.loads(line)
        except Exception:
            continue
        event_yaml = event.get("yaml_path") if isinstance(event, dict) else None
        if isinstance(event_yaml, str) and event_yaml.strip():
            try:
                if _abs_path(event_yaml) != yaml_abs:
                    continue
            except Exception:
                continue
        yield event


def coerce_audit_seq(value):
    try:
        seq = int(value)
    except Exception:
        return None
    if seq <= 0:
        return None
    return seq


def _next_audit_seq_full_scan(log_path):
    if not os.path.exists(log_path):
        return 1

    valid_count = 0
    max_seq = 0
    try:
        with open(log_path, "r", encoding="utf-8") as f:
            for line in f:
                text = str(line or "").strip()
                if not text:
                    continue
                try:
                    row = json.loads(text)
                except Exception:
                    continue
                if not isinstance(row, dict):
                    continue
                valid_count += 1
                seq = coerce_audit_seq(row.get("audit_seq"))
                if seq and seq > max_seq:
                    max_seq = seq
    except Exception:
        return 1

    return max(max_seq, valid_count) + 1


def _next_audit_seq(log_path):
    if not os.path.exists(log_path):
        return 1

    valid_event_without_seq_seen = False
    for line in _iter_jsonl_lines_reverse(log_path):
        try:
            row = json.loads(line)
        except Exception:
            continue
        if not isinstance(row, dict):
            continue
        seq = coerce_audit_seq(row.get("audit_seq"))
        if seq is not None:
            if valid_event_without_seq_seen:
                return _next_audit_seq_full_scan(log_path)
            return seq + 1
        valid_event_without_seq_seen = True

    return _next_audit_seq_full_scan(log_path)


def _append_audit_event(yaml_path, event):
    log_path = _audit_log_path(yaml_path)
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    payload = dict(event or {})
    seq = coerce_audit_seq(payload.get("audit_seq"))
    if seq is None:
        seq = _next_audit_seq(log_path)
    payload["audit_seq"] = seq
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False, sort_keys=True))
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
    yaml_abs = _abs_path(yaml_path)

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
        "warnings": warnings or [],
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

"""
YAML file operations for LN2 inventory
"""
import getpass
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
from datetime import datetime

import yaml
from .config import (
    AUDIT_LOG_FILE,
    BACKUP_DIR_NAME,
    BACKUP_KEEP_COUNT,
    BOX_EMPTY_WARNING_THRESHOLD,
    BOX_RANGE,
    PREVIEW_HOST,
    PREVIEW_MAX_PORT_SCAN,
    PREVIEW_PREFERRED_PORT,
    PREVIEW_SERVER_STATE_FILE,
    TOTAL_EMPTY_WARNING_THRESHOLD,
    YAML_PATH,
    YAML_SIZE_WARNING_MB,
)


_SERVER_PROCS = {}


def _abs_path(path):
    """Return absolute filesystem path."""
    return os.path.abspath(os.fspath(path if path is not None else YAML_PATH))


def load_yaml(path=YAML_PATH):
    """Load YAML file and return data."""
    abs_path = _abs_path(path)
    with open(abs_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _server_state_path(directory):
    return os.path.join(directory, PREVIEW_SERVER_STATE_FILE)


def _load_server_state(directory):
    path = _server_state_path(directory)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            state = json.load(f)
        if not isinstance(state, dict):
            return None
        return state
    except Exception:
        return None


def _save_server_state(directory, pid, host, port):
    path = _server_state_path(directory)
    state = {"pid": int(pid), "host": str(host), "port": int(port)}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f)


def _is_pid_alive(pid):
    try:
        os.kill(int(pid), 0)
        return True
    except (ProcessLookupError, ValueError, OSError):
        return False


def _is_port_open(host, port, timeout=0.2):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.settimeout(timeout)
        return sock.connect_ex((host, int(port))) == 0
    finally:
        sock.close()


def _find_available_port(host, preferred_port, max_scan=PREVIEW_MAX_PORT_SCAN):
    start = int(preferred_port)
    for candidate in range(start, start + int(max_scan)):
        if not _is_port_open(host, candidate):
            return candidate
    return None


def ensure_http_server(
    directory,
    html_name="ln2_inventory.html",
    host=PREVIEW_HOST,
    preferred_port=PREVIEW_PREFERRED_PORT,
):
    """Ensure a local file server is available for browser preview.

    Returns:
        tuple[str, bool]: (preview_url, started_now)
    """
    root = os.path.abspath(directory)
    state = _load_server_state(root)
    if state:
        state_pid = state.get("pid")
        state_host = state.get("host")
        state_port = state.get("port")
        if (
            isinstance(state_pid, int)
            and isinstance(state_port, int)
            and state_host == host
            and _is_pid_alive(state_pid)
            and _is_port_open(host, state_port)
        ):
            return f"http://{host}:{state_port}/{html_name}", False
        try:
            os.remove(_server_state_path(root))
        except OSError:
            pass

    port = _find_available_port(host, preferred_port, max_scan=PREVIEW_MAX_PORT_SCAN)
    if port is None:
        raise RuntimeError(f"no available preview port near {preferred_port}")

    cmd = [
        sys.executable,
        "-m",
        "http.server",
        str(port),
        "--bind",
        host,
        "--directory",
        root,
    ]
    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        close_fds=True,
    )

    for _ in range(20):
        if _is_port_open(host, port):
            _SERVER_PROCS[root] = proc
            _save_server_state(root, proc.pid, host, port)
            return f"http://{host}:{port}/{html_name}", True
        time.sleep(0.1)

    raise RuntimeError("preview server failed to start")


def stop_http_server(directory):
    """Best-effort stop for the managed preview server."""
    root = os.path.abspath(directory)
    state = _load_server_state(root)
    if not state:
        return False

    pid = state.get("pid")
    proc = _SERVER_PROCS.pop(root, None)

    if proc is not None:
        try:
            proc.terminate()
            proc.wait(timeout=1.0)
        except Exception:
            try:
                proc.kill()
                proc.wait(timeout=1.0)
            except Exception:
                pass

    try:
        if isinstance(pid, int) and _is_pid_alive(pid):
            os.kill(pid, signal.SIGTERM)
            for _ in range(10):
                if not _is_pid_alive(pid):
                    break
                time.sleep(0.05)
            if _is_pid_alive(pid):
                os.kill(pid, signal.SIGKILL)
    except OSError:
        pass

    try:
        os.remove(_server_state_path(root))
    except OSError:
        pass

    return True


def _backup_dir(yaml_path):
    yaml_abs = _abs_path(yaml_path)
    return os.path.join(os.path.dirname(yaml_abs), BACKUP_DIR_NAME)


def list_yaml_backups(yaml_path=YAML_PATH, limit=None):
    """List backups for a YAML file, newest first."""
    yaml_abs = _abs_path(yaml_path)
    backup_dir = _backup_dir(yaml_abs)
    if not os.path.isdir(backup_dir):
        return []

    base = os.path.basename(yaml_abs)
    backups = []
    for name in os.listdir(backup_dir):
        if name.startswith(f"{base}.") and name.endswith(".bak"):
            backups.append(os.path.join(backup_dir, name))

    backups.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    if limit is not None:
        return backups[: max(0, int(limit))]
    return backups


def create_yaml_backup(yaml_path=YAML_PATH, keep=BACKUP_KEEP_COUNT):
    """Create timestamped backup for current YAML file.

    Returns:
        str|None: backup path if source exists, else None
    """
    src = _abs_path(yaml_path)
    if not os.path.exists(src):
        return None

    backup_dir = _backup_dir(src)
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
            try:
                os.remove(old)
            except OSError:
                pass

    return backup_path


def _audit_log_path(yaml_path):
    yaml_abs = _abs_path(yaml_path)
    return os.path.join(os.path.dirname(yaml_abs), AUDIT_LOG_FILE)


def _inventory_box_total(data):
    layout = (data or {}).get("meta", {}).get("box_layout", {}) if isinstance(data, dict) else {}
    rows = int(layout.get("rows", 9))
    cols = int(layout.get("cols", 9))
    return rows * cols


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
        for p in rec.get("positions") or []:
            occupied[box].add(int(p))
    return {k: sorted(v) for k, v in sorted(occupied.items(), key=lambda x: int(x[0]))}


def collect_inventory_stats(data):
    """Collect compact occupancy stats for warnings/audit."""
    records = (data or {}).get("inventory", []) if isinstance(data, dict) else []
    per_box_total = _inventory_box_total(data)
    box_count = BOX_RANGE[1] - BOX_RANGE[0] + 1
    total_slots = per_box_total * box_count

    occupancy = compute_occupancy(records)
    boxes = {}
    total_occupied = 0

    for box_num in range(BOX_RANGE[0], BOX_RANGE[1] + 1):
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
        print(f"⚠️  {msg}")
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
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False, sort_keys=True))
        f.write("\n")
    return log_path


def _build_audit_event(
    yaml_path,
    before_data,
    after_data,
    backup_path,
    preview_url,
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

    event = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "user": getpass.getuser(),
        "host": socket.gethostname(),
        "action": meta.get("action", "write_yaml"),
        "source": meta.get("source", "lib.yaml_ops.write_yaml"),
        "yaml_path": yaml_abs,
        "backup_path": backup_path,
        "preview_url": preview_url,
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


def write_html_snapshot(data, yaml_path=YAML_PATH, output_path=None):
    """Render and write the HTML inventory snapshot.

    Args:
        data: Inventory data dict
        yaml_path: Source YAML path (used to derive default HTML output path)
        output_path: Optional explicit HTML output path

    Returns:
        str: Written HTML file path
    """
    # Lazy import to avoid import cycles at module import time.
    from scripts.generate_html import generate_html

    html_path = output_path or os.path.join(os.path.dirname(_abs_path(yaml_path)), "ln2_inventory.html")
    html = generate_html(data)
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)
    return html_path


def write_yaml(
    data,
    path=YAML_PATH,
    auto_html=True,
    auto_server=True,
    auto_backup=True,
    audit_meta=None,
):
    """Write data to YAML file.

    Args:
        data: Inventory data dict
        path: YAML output path
        auto_html: Whether to refresh HTML snapshot after writing YAML
        auto_server: Whether to ensure local HTTP preview server is running
        auto_backup: Whether to create backup before overwrite
        audit_meta: Optional dict for audit fields: action/source/details
    """
    yaml_abs = _abs_path(path)

    before_data = None
    if os.path.exists(yaml_abs):
        try:
            before_data = load_yaml(yaml_abs)
        except Exception as exc:
            print(f"warning: failed to load existing YAML before write: {exc}", file=sys.stderr)

    backup_path = None
    if auto_backup:
        try:
            backup_path = create_yaml_backup(yaml_abs)
            if backup_path:
                print(f"backup created: {backup_path}")
        except Exception as exc:
            print(f"warning: failed to create backup: {exc}", file=sys.stderr)

    with open(yaml_abs, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False, width=120)

    html_path = None
    if auto_html:
        try:
            html_path = write_html_snapshot(data, yaml_path=yaml_abs)
        except Exception as exc:
            # Keep YAML write as the source-of-truth operation.
            print(f"warning: failed to refresh HTML snapshot: {exc}", file=sys.stderr)

    preview_url = None
    if auto_server and html_path:
        try:
            html_name = os.path.basename(html_path)
            preview_dir = os.path.dirname(os.path.abspath(html_path))
            preview_url, started_now = ensure_http_server(preview_dir, html_name=html_name)
            status = "started" if started_now else "running"
            print(f"preview server {status}: {preview_url}")
        except Exception as exc:
            print(f"warning: failed to start preview server: {exc}", file=sys.stderr)

    warnings = []
    warnings.extend(emit_capacity_warnings(data))
    size_warning = emit_yaml_size_warning(path=yaml_abs)
    if size_warning:
        warnings.append(size_warning)

    try:
        event = _build_audit_event(
            yaml_path=yaml_abs,
            before_data=before_data,
            after_data=data,
            backup_path=backup_path,
            preview_url=preview_url,
            warnings=warnings,
            audit_meta=audit_meta,
        )
        _append_audit_event(yaml_abs, event)
    except Exception as exc:
        print(f"warning: failed to append audit log: {exc}", file=sys.stderr)


def rollback_yaml(
    path=YAML_PATH,
    backup_path=None,
    auto_html=True,
    auto_server=True,
    audit_meta=None,
):
    """Rollback YAML to latest (or specified) backup.

    Returns:
        dict: restored_from, snapshot_before_rollback, preview_url
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

    before_data = load_yaml(yaml_abs)

    # Backup current file again before rollback for safety.
    pre_rollback_snapshot = create_yaml_backup(yaml_abs)
    shutil.copy2(target_backup, yaml_abs)

    after_data = load_yaml(yaml_abs)

    html_path = None
    if auto_html:
        html_path = write_html_snapshot(after_data, yaml_path=yaml_abs)

    preview_url = None
    if auto_server and html_path:
        html_name = os.path.basename(html_path)
        preview_dir = os.path.dirname(os.path.abspath(html_path))
        preview_url, started_now = ensure_http_server(preview_dir, html_name=html_name)
        status = "started" if started_now else "running"
        print(f"preview server {status}: {preview_url}")

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

    event = _build_audit_event(
        yaml_path=yaml_abs,
        before_data=before_data,
        after_data=after_data,
        backup_path=pre_rollback_snapshot,
        preview_url=preview_url,
        warnings=warnings,
        audit_meta=meta,
    )
    _append_audit_event(yaml_abs, event)

    return {
        "restored_from": target_backup,
        "snapshot_before_rollback": pre_rollback_snapshot,
        "preview_url": preview_url,
    }

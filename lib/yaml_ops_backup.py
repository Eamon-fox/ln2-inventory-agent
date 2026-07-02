"""Timestamped backup creation, listing, throttling and retention.

Owns the dataset-local ``backups/`` directory: creating throttled/hash-deduped
copies of the inventory YAML, enumerating existing backups, and selecting
alternatives for rollback. These helpers do not load or validate inventory
content themselves; rollback-readiness validation lives with ``rollback_yaml``
in ``lib.yaml_ops`` because it depends on the load/integrity core.
"""
import hashlib
import json
import os
import shutil
import time
import uuid
from contextlib import suppress
from datetime import datetime

from .config import BACKUP_KEEP_COUNT, YAML_PATH
from .inventory_paths import assert_allowed_inventory_yaml_path
from .yaml_ops_paths import _abs_path, get_instance_backup_dir

_BACKUP_THROTTLE_ENV = "LN2_BACKUP_THROTTLE_SECONDS"
_BACKUP_THROTTLE_DEFAULT_SEC = 30
_BACKUP_STATE_FILENAME = ".last_backup.json"


def _backup_dir(yaml_path, instance_id_override=None):
    """Return the dataset-local backup directory for a YAML file."""
    _ = instance_id_override
    return get_instance_backup_dir(yaml_path)


def list_yaml_backups(yaml_path=YAML_PATH, limit=None):
    """List backups for a YAML file, newest first.

    Searches in the dataset-local backup directory.
    """
    yaml_abs = _abs_path(yaml_path)
    yaml_abs = assert_allowed_inventory_yaml_path(yaml_abs)

    backups = []
    backup_dir = get_instance_backup_dir(yaml_abs)
    if os.path.isdir(backup_dir):
        for name in os.listdir(backup_dir):
            if name.endswith(".bak"):
                backups.append(os.path.join(backup_dir, name))

    backups.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    if limit is not None:
        return backups[: max(0, int(limit))]
    return backups


def _backup_throttle_seconds():
    """Read the backup throttle window (seconds). 0/negative disables throttling."""
    raw = os.environ.get(_BACKUP_THROTTLE_ENV)
    if raw is None:
        return _BACKUP_THROTTLE_DEFAULT_SEC
    try:
        return max(0, int(raw))
    except (TypeError, ValueError):
        return _BACKUP_THROTTLE_DEFAULT_SEC


def _file_sha256(path):
    try:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 16), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def _read_backup_state(state_path):
    try:
        with open(state_path, "r", encoding="utf-8") as f:
            payload = json.load(f)
        if isinstance(payload, dict):
            return payload
    except (OSError, ValueError):
        pass
    return {}


def _write_backup_state(state_path, payload):
    """Atomic write so a crash mid-update can't corrupt the state file."""
    tmp_path = f"{state_path}.tmp-{os.getpid()}-{uuid.uuid4().hex[:6]}"
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
        os.replace(tmp_path, state_path)
    except OSError:
        with suppress(OSError):
            os.remove(tmp_path)


def create_yaml_backup(
    yaml_path=YAML_PATH,
    keep=BACKUP_KEEP_COUNT,
    instance_id_override=None,
    *,
    throttle_seconds=None,
    force=False,
):
    """Create timestamped backup for current YAML file.

    The backup is skipped when either
      - the content hash matches the previous backup's hash, or
      - the previous backup happened within ``throttle_seconds`` ago.
    Set ``force=True`` or ``throttle_seconds=0`` to bypass throttling.
    The per-directory state lives in ``.last_backup.json`` and records
    ``{"hash": <sha256>, "path": <backup_path>, "mtime": <epoch>}``.

    Returns:
        str|None: backup path if a new backup was written, otherwise the
        most recent existing backup path (when throttled but we still want
        the caller to have a valid restore point) or None if no source.
    """
    src = _abs_path(yaml_path)
    src = assert_allowed_inventory_yaml_path(src)
    if not os.path.exists(src):
        return None

    backup_dir = _backup_dir(src, instance_id_override=instance_id_override)
    os.makedirs(backup_dir, exist_ok=True)

    window = _backup_throttle_seconds() if throttle_seconds is None else max(
        0, int(throttle_seconds)
    )
    state_path = os.path.join(backup_dir, _BACKUP_STATE_FILENAME)
    state = {} if force else _read_backup_state(state_path)

    src_hash = _file_sha256(src) if not force else None
    now = time.time()
    last_hash = str(state.get("hash") or "") if state else ""
    last_mtime = state.get("mtime") if state else None
    last_path = state.get("path") if state else None

    if (
        not force
        and src_hash
        and last_hash == src_hash
        and isinstance(last_path, str)
        and os.path.exists(last_path)
    ):
        return last_path

    if (
        not force
        and window > 0
        and isinstance(last_mtime, (int, float))
        and (now - float(last_mtime)) < window
        and isinstance(last_path, str)
        and os.path.exists(last_path)
    ):
        return last_path

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    base = os.path.basename(src)
    backup_path = os.path.join(backup_dir, f"{base}.{stamp}.bak")

    i = 1
    while os.path.exists(backup_path):
        backup_path = os.path.join(backup_dir, f"{base}.{stamp}.{i}.bak")
        i += 1

    shutil.copy2(src, backup_path)

    _write_backup_state(
        state_path,
        {"hash": src_hash or _file_sha256(backup_path) or "", "path": backup_path, "mtime": now},
    )

    if keep is not None and keep > 0:
        old_backups = list_yaml_backups(src)
        for old in old_backups[keep:]:
            with suppress(OSError):
                os.remove(old)

    return backup_path


def list_alternative_backups(
    yaml_path: str,
    exclude_path: str = None,
    limit: int = 5,
) -> list:
    """Return valid alternative backup paths, excluding a failed one.

    Each entry is a dict with ``path`` and ``mtime`` keys, sorted newest first.
    """
    all_backups = list_yaml_backups(yaml_path)
    exclude_norm = os.path.normcase(os.path.normpath(_abs_path(exclude_path))) if exclude_path else None

    alternatives = []
    for bp in all_backups:
        if exclude_norm and os.path.normcase(os.path.normpath(bp)) == exclude_norm:
            continue
        try:
            mtime = os.path.getmtime(bp)
        except OSError:
            continue
        alternatives.append({"path": bp, "mtime": datetime.fromtimestamp(mtime).isoformat(timespec="seconds")})
        if len(alternatives) >= limit:
            break
    return alternatives

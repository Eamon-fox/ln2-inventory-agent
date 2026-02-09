"""Unified Tool API shared by CLI, GUI, and AI agents."""

import getpass
import uuid
from copy import deepcopy
from collections import defaultdict
from datetime import datetime, timedelta

from .config import BOX_RANGE, POSITION_RANGE, VALID_CELL_LINES
from .operations import check_position_conflicts, find_record_by_id, get_next_id
from .thaw_parser import ACTION_LABEL, extract_events, normalize_action
from .validators import (
    format_validation_errors,
    normalize_date_arg,
    parse_date,
    validate_date,
    validate_inventory,
)
from .yaml_ops import compute_occupancy, list_yaml_backups, load_yaml, rollback_yaml, write_yaml


_DEFAULT_SESSION_ID = f"session-{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:8]}"


def build_actor_context(
    actor_type="human",
    channel="cli",
    actor_id=None,
    session_id=None,
    trace_id=None,
):
    """Build normalized actor context for unified audit records."""
    return {
        "actor_type": actor_type or "human",
        "actor_id": actor_id or getpass.getuser(),
        "channel": channel or "cli",
        "session_id": session_id or _DEFAULT_SESSION_ID,
        "trace_id": trace_id,
    }


def parse_batch_entries(entries_str):
    """Parse batch input format: ``id1:pos1,id2:pos2,...``."""
    result = []
    try:
        for entry in str(entries_str).split(","):
            entry = entry.strip()
            if not entry:
                continue
            record_id, position = entry.split(":")
            result.append((int(record_id), int(position)))
    except Exception as exc:
        raise ValueError(f"输入格式错误: {exc}. 正确格式示例: '182:23,183:41,184:43'")
    return result


def _build_audit_meta(action, source, tool_name, actor_context=None, details=None, tool_input=None):
    actor = dict(build_actor_context())
    actor.update(actor_context or {})
    if not actor.get("trace_id"):
        actor["trace_id"] = f"trace-{uuid.uuid4().hex}"
    if not actor.get("session_id"):
        actor["session_id"] = _DEFAULT_SESSION_ID
    if not actor.get("actor_id"):
        actor["actor_id"] = getpass.getuser()

    return {
        "action": action,
        "source": source,
        "tool_name": tool_name,
        "actor_type": actor.get("actor_type", "human"),
        "actor_id": actor.get("actor_id"),
        "channel": actor.get("channel", "cli"),
        "session_id": actor.get("session_id"),
        "trace_id": actor.get("trace_id"),
        "status": "success",
        "details": details,
        "tool_input": tool_input,
    }


def _validate_data_or_error(data, message_prefix="写入被阻止：完整性校验失败"):
    """Return structured validation error payload when data is invalid."""
    errors, _warnings = validate_inventory(data)
    if not errors:
        return None
    return {
        "ok": False,
        "error_code": "integrity_validation_failed",
        "message": format_validation_errors(errors, prefix=message_prefix),
        "errors": errors,
    }


def tool_add_entry(
    yaml_path,
    parent_cell_line,
    short_name,
    box,
    positions,
    frozen_at,
    plasmid_name=None,
    plasmid_id=None,
    note=None,
    dry_run=False,
    actor_context=None,
    source="tool_api",
    auto_html=True,
    auto_server=True,
    auto_backup=True,
):
    """Add a new frozen entry using the shared tool flow."""
    if VALID_CELL_LINES and parent_cell_line not in VALID_CELL_LINES:
        return {
            "ok": False,
            "error_code": "invalid_cell_line",
            "message": f"parent_cell_line 不在允许列表中: {parent_cell_line}",
            "allowed_cell_lines": list(VALID_CELL_LINES),
        }

    if not validate_date(frozen_at):
        return {
            "ok": False,
            "error_code": "invalid_date",
            "message": f"日期格式无效: {frozen_at}",
        }

    if box < BOX_RANGE[0] or box > BOX_RANGE[1]:
        return {
            "ok": False,
            "error_code": "invalid_box",
            "message": f"盒子编号必须在 {BOX_RANGE[0]}-{BOX_RANGE[1]} 之间",
        }

    if not positions:
        return {
            "ok": False,
            "error_code": "empty_positions",
            "message": "必须指定至少一个位置",
        }

    try:
        data = load_yaml(yaml_path)
    except Exception as exc:
        return {
            "ok": False,
            "error_code": "load_failed",
            "message": f"无法读取YAML文件: {exc}",
        }

    records = data.get("inventory", [])
    conflicts = check_position_conflicts(records, box, positions)
    if conflicts:
        return {
            "ok": False,
            "error_code": "position_conflict",
            "message": "位置冲突",
            "conflicts": conflicts,
        }

    new_id = get_next_id(records)
    new_record = {
        "id": new_id,
        "parent_cell_line": parent_cell_line,
        "short_name": short_name,
        "plasmid_name": plasmid_name,
        "plasmid_id": plasmid_id,
        "box": box,
        "positions": positions,
        "frozen_at": frozen_at,
        "thaw_log": None,
        "note": note,
    }

    preview = {
        "id": new_id,
        "parent_cell_line": parent_cell_line,
        "short_name": short_name,
        "plasmid_name": plasmid_name,
        "plasmid_id": plasmid_id,
        "box": box,
        "positions": list(positions),
        "frozen_at": frozen_at,
        "note": note,
    }

    if dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "preview": preview,
            "result": {"new_id": new_id, "record": new_record},
        }

    try:
        candidate_data = deepcopy(data)
        candidate_inventory = candidate_data.setdefault("inventory", [])
        if not isinstance(candidate_inventory, list):
            return _validate_data_or_error(candidate_data)
        candidate_inventory.append(new_record)
        validation_error = _validate_data_or_error(candidate_data)
        if validation_error:
            return validation_error

        write_yaml(
            candidate_data,
            yaml_path,
            auto_html=auto_html,
            auto_server=auto_server,
            auto_backup=auto_backup,
            audit_meta=_build_audit_meta(
                action="add_entry",
                source=source,
                tool_name="tool_add_entry",
                actor_context=actor_context,
                details={
                    "new_id": new_id,
                    "box": box,
                    "positions": list(positions),
                    "parent_cell_line": parent_cell_line,
                    "short_name": short_name,
                },
                tool_input={
                    "parent_cell_line": parent_cell_line,
                    "short_name": short_name,
                    "box": box,
                    "positions": list(positions),
                    "frozen_at": frozen_at,
                },
            ),
        )
    except Exception as exc:
        return {
            "ok": False,
            "error_code": "write_failed",
            "message": f"添加失败: {exc}",
        }

    return {
        "ok": True,
        "dry_run": False,
        "preview": preview,
        "result": {"new_id": new_id, "record": new_record},
    }


def tool_record_thaw(
    yaml_path,
    record_id,
    position,
    date_str,
    action="取出",
    note=None,
    dry_run=False,
    actor_context=None,
    source="tool_api",
    auto_html=True,
    auto_server=True,
    auto_backup=True,
):
    """Record one thaw/takeout/discard operation via shared tool flow."""
    if not validate_date(date_str):
        return {
            "ok": False,
            "error_code": "invalid_date",
            "message": f"日期格式无效: {date_str}",
        }

    if position < POSITION_RANGE[0] or position > POSITION_RANGE[1]:
        return {
            "ok": False,
            "error_code": "invalid_position",
            "message": f"位置编号必须在 {POSITION_RANGE[0]}-{POSITION_RANGE[1]} 之间",
        }

    action_en = normalize_action(action)
    if not action_en:
        return {
            "ok": False,
            "error_code": "invalid_action",
            "message": "操作类型必须是 取出/复苏/扔掉",
        }
    action_cn = ACTION_LABEL.get(action_en, action)

    try:
        data = load_yaml(yaml_path)
    except Exception as exc:
        return {
            "ok": False,
            "error_code": "load_failed",
            "message": f"无法读取YAML文件: {exc}",
        }

    records = data.get("inventory", [])
    idx, record = find_record_by_id(records, record_id)
    if record is None:
        return {
            "ok": False,
            "error_code": "record_not_found",
            "message": f"未找到 ID={record_id} 的记录",
        }

    positions = record.get("positions", [])
    if position not in positions:
        return {
            "ok": False,
            "error_code": "position_not_found",
            "message": f"位置 {position} 不在记录 #{record_id} 的现有位置中",
            "current_positions": positions,
        }

    new_positions = [p for p in positions if p != position]
    new_event = {"date": date_str, "action": action_en, "positions": [position]}
    if note:
        new_event["note"] = note

    preview = {
        "record_id": record_id,
        "parent_cell_line": record.get("parent_cell_line"),
        "short_name": record.get("short_name"),
        "box": record.get("box"),
        "action_en": action_en,
        "action_cn": action_cn,
        "position": position,
        "note": note,
        "date": date_str,
        "positions_before": positions,
        "positions_after": new_positions,
    }

    if dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "preview": preview,
        }

    try:
        candidate_data = deepcopy(data)
        candidate_records = candidate_data.get("inventory", [])
        if not isinstance(candidate_records, list):
            return _validate_data_or_error(candidate_data)
        candidate_records[idx]["positions"] = new_positions
        thaw_events = candidate_records[idx].get("thaw_events")
        if thaw_events is None:
            candidate_records[idx]["thaw_events"] = []
            thaw_events = candidate_records[idx]["thaw_events"]
        if not isinstance(thaw_events, list):
            return _validate_data_or_error(candidate_data)
        thaw_events.append(new_event)

        validation_error = _validate_data_or_error(candidate_data)
        if validation_error:
            return validation_error

        write_yaml(
            candidate_data,
            yaml_path,
            auto_html=auto_html,
            auto_server=auto_server,
            auto_backup=auto_backup,
            audit_meta=_build_audit_meta(
                action="record_thaw",
                source=source,
                tool_name="tool_record_thaw",
                actor_context=actor_context,
                details={
                    "record_id": record_id,
                    "box": record.get("box"),
                    "position": position,
                    "action": action_en,
                    "date": date_str,
                },
                tool_input={
                    "record_id": record_id,
                    "position": position,
                    "date": date_str,
                    "action": action,
                    "note": note,
                },
            ),
        )
    except Exception as exc:
        return {
            "ok": False,
            "error_code": "write_failed",
            "message": f"更新失败: {exc}",
        }

    return {
        "ok": True,
        "dry_run": False,
        "preview": preview,
        "result": {
            "record_id": record_id,
            "remaining_positions": new_positions,
        },
    }


def tool_batch_thaw(
    yaml_path,
    entries,
    date_str,
    action="取出",
    note=None,
    dry_run=False,
    actor_context=None,
    source="tool_api",
    auto_html=True,
    auto_server=True,
    auto_backup=True,
):
    """Record batch thaw/takeout/discard operations via shared tool flow."""
    if not validate_date(date_str):
        return {
            "ok": False,
            "error_code": "invalid_date",
            "message": f"日期格式无效: {date_str}",
        }

    if not entries:
        return {
            "ok": False,
            "error_code": "empty_entries",
            "message": "未指定任何操作",
        }

    action_en = normalize_action(action)
    if not action_en:
        return {
            "ok": False,
            "error_code": "invalid_action",
            "message": "操作类型必须是 取出/复苏/扔掉",
        }

    try:
        data = load_yaml(yaml_path)
    except Exception as exc:
        return {
            "ok": False,
            "error_code": "load_failed",
            "message": f"无法读取YAML文件: {exc}",
        }

    records = data.get("inventory", [])
    operations = []
    errors = []

    for record_id, position in entries:
        if position < POSITION_RANGE[0] or position > POSITION_RANGE[1]:
            errors.append(f"ID {record_id}: 位置编号 {position} 必须在 {POSITION_RANGE[0]}-{POSITION_RANGE[1]} 之间")
            continue

        idx, record = find_record_by_id(records, record_id)
        if record is None:
            errors.append(f"ID {record_id}: 未找到该记录")
            continue

        old_positions = record.get("positions", [])
        if position not in old_positions:
            errors.append(f"ID {record_id}: 位置 {position} 不在现有位置 {old_positions} 中")
            continue

        operations.append(
            {
                "idx": idx,
                "record_id": record_id,
                "record": record,
                "position": position,
                "old_positions": old_positions.copy(),
                "new_positions": [p for p in old_positions if p != position],
            }
        )

    if errors:
        return {
            "ok": False,
            "error_code": "validation_failed",
            "message": "批量操作参数校验失败",
            "errors": errors,
            "operations": operations,
        }

    preview = {
        "date": date_str,
        "action_en": action_en,
        "action_cn": ACTION_LABEL.get(action_en, action),
        "note": note,
        "count": len(operations),
        "operations": [
            {
                "record_id": op["record_id"],
                "parent_cell_line": op["record"].get("parent_cell_line"),
                "short_name": op["record"].get("short_name"),
                "box": op["record"].get("box"),
                "position": op["position"],
                "old_positions": op["old_positions"],
                "new_positions": op["new_positions"],
            }
            for op in operations
        ],
    }

    if dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "preview": preview,
        }

    try:
        candidate_data = deepcopy(data)
        candidate_records = candidate_data.get("inventory", [])
        if not isinstance(candidate_records, list):
            return _validate_data_or_error(candidate_data)

        for op in operations:
            idx = op["idx"]
            position = op["position"]
            candidate_records[idx]["positions"] = op["new_positions"]

            new_event = {
                "date": date_str,
                "action": action_en,
                "positions": [position],
            }
            if note:
                new_event["note"] = note
            thaw_events = candidate_records[idx].get("thaw_events")
            if thaw_events is None:
                candidate_records[idx]["thaw_events"] = []
                thaw_events = candidate_records[idx]["thaw_events"]
            if not isinstance(thaw_events, list):
                return _validate_data_or_error(candidate_data)
            thaw_events.append(new_event)

        validation_error = _validate_data_or_error(candidate_data)
        if validation_error:
            return validation_error

        write_yaml(
            candidate_data,
            yaml_path,
            auto_html=auto_html,
            auto_server=auto_server,
            auto_backup=auto_backup,
            audit_meta=_build_audit_meta(
                action="batch_thaw",
                source=source,
                tool_name="tool_batch_thaw",
                actor_context=actor_context,
                details={
                    "count": len(operations),
                    "action": action_en,
                    "date": date_str,
                    "record_ids": [op["record_id"] for op in operations],
                },
                tool_input={
                    "entries": list(entries),
                    "date": date_str,
                    "action": action,
                    "note": note,
                },
            ),
        )
    except Exception as exc:
        return {
            "ok": False,
            "error_code": "write_failed",
            "message": f"批量更新失败: {exc}",
        }

    return {
        "ok": True,
        "dry_run": False,
        "preview": preview,
        "result": {
            "count": len(operations),
            "record_ids": [op["record_id"] for op in operations],
        },
    }


def tool_list_backups(yaml_path):
    """List YAML backup files, newest first."""
    return list_yaml_backups(yaml_path)


def tool_rollback(
    yaml_path,
    backup_path=None,
    no_html=False,
    no_server=False,
    actor_context=None,
    source="tool_api",
):
    """Rollback inventory YAML using shared tool flow."""
    backups = list_yaml_backups(yaml_path)
    if not backups and not backup_path:
        return {
            "ok": False,
            "error_code": "no_backups",
            "message": "无可用备份，无法回滚",
        }

    target = backup_path or backups[0]
    try:
        backup_data = load_yaml(target)
    except Exception as exc:
        return {
            "ok": False,
            "error_code": "backup_load_failed",
            "message": f"无法读取备份文件: {exc}",
        }

    validation_error = _validate_data_or_error(
        backup_data,
        message_prefix="回滚被阻止：目标备份不满足完整性约束",
    )
    if validation_error:
        validation_error["error_code"] = "rollback_backup_invalid"
        validation_error["backup_path"] = target
        return validation_error

    try:
        result = rollback_yaml(
            path=yaml_path,
            backup_path=target,
            auto_html=not no_html,
            auto_server=not no_server,
            audit_meta=_build_audit_meta(
                action="rollback",
                source=source,
                tool_name="tool_rollback",
                actor_context=actor_context,
                details={"requested_backup": target},
                tool_input={
                    "backup_path": backup_path,
                    "no_html": bool(no_html),
                    "no_server": bool(no_server),
                },
            ),
        )
    except Exception as exc:
        return {
            "ok": False,
            "error_code": "rollback_failed",
            "message": f"回滚失败: {exc}",
        }

    return {
        "ok": True,
        "result": result,
    }


def _str_contains(value, query, case_sensitive=False):
    if value is None:
        return False
    if query is None:
        return False
    text = str(value)
    needle = str(query)
    if case_sensitive:
        return needle in text
    return needle.lower() in text.lower()


def _record_search_blob(rec, case_sensitive=False):
    fields = [
        "id",
        "parent_cell_line",
        "short_name",
        "plasmid_name",
        "plasmid_id",
        "note",
        "thaw_log",
        "box",
        "frozen_at",
    ]
    parts = []
    for field in fields:
        value = rec.get(field)
        if value is not None and value != "":
            parts.append(str(value))
    positions = rec.get("positions") or []
    if positions:
        parts.append(",".join(str(p) for p in positions))
    blob = " ".join(parts)
    return blob if case_sensitive else blob.lower()


def tool_query_inventory(
    yaml_path,
    cell=None,
    short=None,
    plasmid=None,
    plasmid_id=None,
    box=None,
    position=None,
):
    """Query inventory records with field filters."""
    try:
        data = load_yaml(yaml_path)
    except Exception as exc:
        return {
            "ok": False,
            "error_code": "load_failed",
            "message": f"无法读取YAML文件: {exc}",
        }

    records = data.get("inventory", [])
    matches = []
    for rec in records:
        if cell and not _str_contains(rec.get("parent_cell_line"), cell):
            continue
        if short and not _str_contains(rec.get("short_name"), short):
            continue
        if plasmid and not _str_contains(rec.get("plasmid_name"), plasmid):
            continue
        if plasmid_id and not _str_contains(rec.get("plasmid_id"), plasmid_id):
            continue
        if box is not None and rec.get("box") != box:
            continue
        if position is not None:
            positions = rec.get("positions") or []
            if position not in positions:
                continue
        matches.append(rec)

    return {
        "ok": True,
        "result": {
            "records": matches,
            "count": len(matches),
        },
    }


def tool_list_empty_positions(yaml_path, box=None):
    """List empty positions by box."""
    try:
        data = load_yaml(yaml_path)
    except Exception as exc:
        return {
            "ok": False,
            "error_code": "load_failed",
            "message": f"无法读取YAML文件: {exc}",
        }

    records = data.get("inventory", [])
    layout = data.get("meta", {}).get("box_layout", {})
    total_slots = int(layout.get("rows", 9)) * int(layout.get("cols", 9))
    all_positions = set(range(1, total_slots + 1))
    occupancy = compute_occupancy(records)

    if box is not None:
        if box < BOX_RANGE[0] or box > BOX_RANGE[1]:
            return {
                "ok": False,
                "error_code": "invalid_box",
                "message": f"盒子编号必须在 {BOX_RANGE[0]}-{BOX_RANGE[1]} 之间",
            }
        boxes = [str(box)]
    else:
        boxes = [str(i) for i in range(BOX_RANGE[0], BOX_RANGE[1] + 1)]

    items = []
    for box_key in boxes:
        used = set(occupancy.get(box_key, []))
        empty = sorted(all_positions - used)
        items.append(
            {
                "box": box_key,
                "total_slots": total_slots,
                "empty_count": len(empty),
                "empty_positions": empty,
            }
        )

    return {
        "ok": True,
        "result": {
            "boxes": items,
            "total_slots": total_slots,
        },
    }


def tool_search_records(
    yaml_path,
    query,
    mode="fuzzy",
    max_results=None,
    case_sensitive=False,
):
    """Search records by fuzzy/exact/keywords mode."""
    try:
        data = load_yaml(yaml_path)
    except Exception as exc:
        return {
            "ok": False,
            "error_code": "load_failed",
            "message": f"无法读取YAML文件: {exc}",
        }

    records = data.get("inventory", [])
    normalized_query = " ".join(str(query).split())
    keywords = normalized_query.split() if normalized_query else []
    q = normalized_query if case_sensitive else normalized_query.lower()

    if mode not in {"fuzzy", "exact", "keywords"}:
        return {
            "ok": False,
            "error_code": "invalid_mode",
            "message": "mode 必须是 fuzzy/exact/keywords",
        }

    matches = []
    for rec in records:
        blob = _record_search_blob(rec, case_sensitive=case_sensitive)
        if mode in {"fuzzy", "exact"}:
            if q and q in blob:
                matches.append(rec)
            continue

        # keywords (AND)
        ok = True
        for kw in keywords:
            kw_cmp = kw if case_sensitive else kw.lower()
            if kw_cmp not in blob:
                ok = False
                break
        if ok and keywords:
            matches.append(rec)

    total_count = len(matches)
    display_matches = matches[:max_results] if (max_results and max_results > 0) else matches

    suggestions = []
    if total_count == 0:
        suggestions.extend(
            [
                "尝试使用更短的关键词，如 'reporter' 或 '36'",
                "检查是否有拼写错误",
                "使用 keywords 模式尝试分词搜索",
            ]
        )
    elif total_count > 50:
        suggestions.extend(["结果较多，建议添加关键词进一步缩小范围"])

    return {
        "ok": True,
        "result": {
            "query": query,
            "normalized_query": normalized_query,
            "keywords": keywords,
            "mode": mode,
            "records": display_matches,
            "total_count": total_count,
            "display_count": len(display_matches),
            "suggestions": suggestions,
        },
    }


def tool_recent_frozen(yaml_path, days=None, count=None):
    """Query recently frozen records sorted by date desc."""
    try:
        data = load_yaml(yaml_path)
    except Exception as exc:
        return {
            "ok": False,
            "error_code": "load_failed",
            "message": f"无法读取YAML文件: {exc}",
        }

    records = data.get("inventory", [])
    valid = []
    for rec in records:
        frozen_at = rec.get("frozen_at")
        if not frozen_at:
            continue
        dt = parse_date(frozen_at)
        if not dt:
            continue
        valid.append((dt, rec))

    valid.sort(key=lambda x: x[0], reverse=True)
    if days is not None:
        cutoff = datetime.now() - timedelta(days=days)
        selected = [rec for dt, rec in valid if dt >= cutoff]
    elif count is not None:
        selected = [rec for _, rec in valid[:count]]
    else:
        selected = [rec for _, rec in valid[:10]]

    return {
        "ok": True,
        "result": {
            "records": selected,
            "count": len(selected),
            "days": days,
            "limit": count,
        },
    }


def tool_query_thaw_events(
    yaml_path,
    date=None,
    days=None,
    start_date=None,
    end_date=None,
    action=None,
    max_records=0,
):
    """Query thaw/takeout/discard events by date mode and action."""
    action_filter = normalize_action(action) if action else None
    if action and not action_filter:
        return {
            "ok": False,
            "error_code": "invalid_action",
            "message": "操作类型必须是 取出/复苏/扔掉 或 takeout/thaw/discard",
        }

    if days:
        end_dt = datetime.now()
        start_dt = end_dt - timedelta(days=days)
        mode = "days"
        target_dates = None
        date_range = (start_dt.strftime("%Y-%m-%d"), end_dt.strftime("%Y-%m-%d"))
    elif start_date and end_date:
        start = normalize_date_arg(start_date)
        end = normalize_date_arg(end_date)
        if not start or not end:
            return {
                "ok": False,
                "error_code": "invalid_date",
                "message": "日期格式无效，请使用 YYYY-MM-DD",
            }
        mode = "range"
        target_dates = None
        date_range = (start, end)
    else:
        target = normalize_date_arg(date)
        if not target:
            return {
                "ok": False,
                "error_code": "invalid_date",
                "message": "日期格式无效，请使用 YYYY-MM-DD",
            }
        mode = "single"
        target_dates = [target]
        date_range = None

    range_start, range_end = date_range if date_range else (None, None)

    try:
        data = load_yaml(yaml_path)
    except Exception as exc:
        return {
            "ok": False,
            "error_code": "load_failed",
            "message": f"无法读取YAML文件: {exc}",
        }

    records = data.get("inventory", [])
    matched = []
    total_events = 0
    for rec in records:
        events = extract_events(rec)
        if not events:
            continue

        if mode == "single":
            filtered = [
                ev
                for ev in events
                if ev.get("date") in target_dates and (not action_filter or ev.get("action") == action_filter)
            ]
        else:
            filtered = [
                ev
                for ev in events
                if ev.get("date")
                and range_start <= ev.get("date") <= range_end
                and (not action_filter or ev.get("action") == action_filter)
            ]

        if filtered:
            matched.append({"record": rec, "events": filtered})
            total_events += len(filtered)

    total_record_count = len(matched)
    if max_records and max_records > 0:
        records_to_return = matched[:max_records]
    else:
        records_to_return = matched

    return {
        "ok": True,
        "result": {
            "mode": mode,
            "target_dates": target_dates,
            "date_range": date_range,
            "action_filter": action_filter,
            "records": records_to_return,
            "record_count": total_record_count,
            "display_count": len(records_to_return),
            "event_count": total_events,
        },
    }


def _collect_timeline_events(records, days=None):
    timeline = defaultdict(lambda: {"frozen": [], "thaw": [], "takeout": [], "discard": []})
    cutoff_str = None
    if days:
        cutoff_str = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

    for rec in records:
        frozen_at = rec.get("frozen_at")
        if frozen_at and (not cutoff_str or frozen_at >= cutoff_str):
            timeline[frozen_at]["frozen"].append(rec)

    for rec in records:
        for ev in extract_events(rec):
            date = ev.get("date")
            if not date:
                continue
            if cutoff_str and date < cutoff_str:
                continue
            action = ev.get("action")
            if action not in {"thaw", "takeout", "discard"}:
                continue
            timeline[date][action].append({**ev, "record": rec})
    return timeline


def tool_collect_timeline(yaml_path, days=30, all_history=False):
    """Collect timeline events and summary stats."""
    try:
        data = load_yaml(yaml_path)
    except Exception as exc:
        return {
            "ok": False,
            "error_code": "load_failed",
            "message": f"无法读取YAML文件: {exc}",
        }

    records = data.get("inventory", [])
    timeline = _collect_timeline_events(records, days=None if all_history else days)

    total_frozen = 0
    total_thaw = 0
    total_takeout = 0
    total_discard = 0
    active_days = 0
    for _, events in timeline.items():
        frozen = len(events["frozen"])
        thaw = len(events["thaw"])
        takeout = len(events["takeout"])
        discard = len(events["discard"])
        total_frozen += frozen
        total_thaw += thaw
        total_takeout += takeout
        total_discard += discard
        if frozen + thaw + takeout + discard > 0:
            active_days += 1

    return {
        "ok": True,
        "result": {
            "timeline": dict(timeline),
            "sorted_dates": sorted(timeline.keys(), reverse=True),
            "summary": {
                "active_days": active_days,
                "total_ops": total_frozen + total_thaw + total_takeout + total_discard,
                "frozen": total_frozen,
                "thaw": total_thaw,
                "takeout": total_takeout,
                "discard": total_discard,
            },
        },
    }


def _get_box_total_slots(layout):
    rows = int(layout.get("rows", 9))
    cols = int(layout.get("cols", 9))
    return rows * cols


def _find_consecutive_slots(empty_positions, count):
    if not empty_positions or count <= 0:
        return []
    groups = []
    current = [empty_positions[0]]
    for i in range(1, len(empty_positions)):
        if empty_positions[i] == current[-1] + 1:
            current.append(empty_positions[i])
        else:
            if len(current) >= count:
                groups.append(current[:count])
            current = [empty_positions[i]]
    if len(current) >= count:
        groups.append(current[:count])
    return groups


def _find_same_row_slots(empty_positions, count, layout):
    cols = int(layout.get("cols", 9))
    row_groups = {}
    for pos in empty_positions:
        row = (pos - 1) // cols
        row_groups.setdefault(row, []).append(pos)

    groups = []
    for _, positions in sorted(row_groups.items()):
        if len(positions) < count:
            continue
        consecutive = _find_consecutive_slots(positions, count)
        if consecutive:
            groups.extend(consecutive)
        else:
            groups.append(sorted(positions)[:count])
    return groups


def tool_recommend_positions(yaml_path, count, box_preference=None, strategy="consecutive"):
    """Recommend positions for new samples."""
    if count <= 0:
        return {
            "ok": False,
            "error_code": "invalid_count",
            "message": "数量必须大于 0",
        }

    try:
        data = load_yaml(yaml_path)
    except Exception as exc:
        return {
            "ok": False,
            "error_code": "load_failed",
            "message": f"无法读取YAML文件: {exc}",
        }

    layout = data.get("meta", {}).get("box_layout", {})
    total_slots = _get_box_total_slots(layout)
    all_positions = set(range(1, total_slots + 1))
    occupancy = compute_occupancy(data.get("inventory", []))

    if box_preference:
        boxes_to_check = [str(box_preference)]
    else:
        boxes_to_check = []
        for box_num in range(BOX_RANGE[0], BOX_RANGE[1] + 1):
            key = str(box_num)
            boxes_to_check.append((key, len(occupancy.get(key, []))))
        boxes_to_check = [b for b, _ in sorted(boxes_to_check, key=lambda x: x[1])]

    recommendations = []
    for box_key in boxes_to_check:
        occupied = set(occupancy.get(box_key, []))
        empty = sorted(all_positions - occupied)
        if len(empty) < count:
            continue

        box_recs = []
        if strategy in {"consecutive", "any"}:
            for group in _find_consecutive_slots(empty, count)[:3]:
                box_recs.append({"box": box_key, "positions": group, "reason": "连续位置", "score": 100})

        if strategy == "same_row":
            for group in _find_same_row_slots(empty, count, layout)[:3]:
                box_recs.append({"box": box_key, "positions": group, "reason": "同一行", "score": 90})

        if not box_recs:
            box_recs.append({"box": box_key, "positions": empty[:count], "reason": "最早空位", "score": 50})

        recommendations.extend(box_recs)
        if len(recommendations) >= 5:
            break

    return {
        "ok": True,
        "result": {
            "count": count,
            "strategy": strategy,
            "recommendations": recommendations[:5],
        },
    }


def tool_generate_stats(yaml_path):
    """Generate inventory statistics and occupancy maps."""
    try:
        data = load_yaml(yaml_path)
    except Exception as exc:
        return {
            "ok": False,
            "error_code": "load_failed",
            "message": f"无法读取YAML文件: {exc}",
        }

    records = data.get("inventory", [])
    layout = data.get("meta", {}).get("box_layout", {})
    total_slots = _get_box_total_slots(layout)
    occupancy = compute_occupancy(records)
    total_boxes = BOX_RANGE[1] - BOX_RANGE[0] + 1

    total_occupied = sum(len(positions) for positions in occupancy.values())
    total_capacity = total_boxes * total_slots
    overall_rate = (total_occupied / total_capacity * 100) if total_capacity > 0 else 0

    box_stats = {}
    for box_num in range(BOX_RANGE[0], BOX_RANGE[1] + 1):
        key = str(box_num)
        occupied_count = len(occupancy.get(key, []))
        rate = (occupied_count / total_slots * 100) if total_slots > 0 else 0
        box_stats[key] = {
            "occupied": occupied_count,
            "empty": total_slots - occupied_count,
            "total": total_slots,
            "rate": rate,
        }

    cell_lines = defaultdict(int)
    for rec in records:
        if rec.get("positions"):
            cell_lines[rec.get("parent_cell_line", "Unknown")] += len(rec.get("positions", []))

    return {
        "ok": True,
        "result": {
            "data": data,
            "layout": layout,
            "occupancy": occupancy,
            "stats": {
                "overall": {
                    "total_occupied": total_occupied,
                    "total_empty": total_capacity - total_occupied,
                    "total_capacity": total_capacity,
                    "occupancy_rate": overall_rate,
                },
                "boxes": box_stats,
                "cell_lines": dict(sorted(cell_lines.items(), key=lambda x: x[1], reverse=True)),
            },
        },
    }


def tool_get_raw_entries(yaml_path, ids):
    """Return raw YAML entries for selected IDs."""
    try:
        data = load_yaml(yaml_path)
    except Exception as exc:
        return {
            "ok": False,
            "error_code": "load_failed",
            "message": f"无法读取YAML文件: {exc}",
        }

    inventory = data.get("inventory", [])
    id_set = set(ids)
    found = []
    found_ids = set()
    for entry in inventory:
        entry_id = entry.get("id")
        if entry_id in id_set:
            found.append(entry)
            found_ids.add(entry_id)
    found.sort(key=lambda x: x.get("id", 0))
    missing = sorted(id_set - found_ids)

    if not found:
        return {
            "ok": False,
            "error_code": "not_found",
            "message": f"未找到 ID: {', '.join(map(str, ids))}",
            "missing_ids": missing,
            "entries": [],
        }

    return {
        "ok": True,
        "result": {
            "entries": found,
            "missing_ids": missing,
            "requested_ids": list(ids),
        },
    }

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
    validate_box,
    validate_date,
    validate_inventory,
    validate_position,
)
from .yaml_ops import (
    append_audit_event,
    compute_occupancy,
    list_yaml_backups,
    load_yaml,
    rollback_yaml,
    write_yaml,
)


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
    """Parse batch input format.

    Supports:
    - ``id1:pos1,id2:pos2,...`` (takeout/thaw/discard)
    - ``id1:from1->to1,id2:from2->to2,...`` (move within same box)
    - ``id1:from1->to1:box,id2:from2->to2:box,...`` (cross-box move)
    """
    result = []
    try:
        for entry in str(entries_str).split(","):
            entry = entry.strip()
            if not entry:
                continue
            parts = entry.split(":")
            record_id = int(parts[0])
            pos_text = parts[1].strip() if len(parts) >= 2 else ""
            to_box = int(parts[2]) if len(parts) >= 3 else None
            if "->" in pos_text:
                from_pos_text, to_pos_text = pos_text.split("->", 1)
                tup = (record_id, int(from_pos_text), int(to_pos_text))
                if to_box is not None:
                    tup = tup + (to_box,)
                result.append(tup)
            elif ">" in pos_text:
                from_pos_text, to_pos_text = pos_text.split(">", 1)
                tup = (record_id, int(from_pos_text), int(to_pos_text))
                if to_box is not None:
                    tup = tup + (to_box,)
                result.append(tup)
            else:
                result.append((record_id, int(pos_text)))
    except Exception as exc:
        raise ValueError(
            "输入格式错误: "
            f"{exc}. 正确格式示例: '182:23,183:41' 或 '182:23->31,183:41->42' 或 '182:23->31:1' (cross-box)"
        )
    return result


def _coerce_batch_entry(entry):
    """Normalize one batch entry to a tuple of ints.

    Accepts tuple/list forms ``(record_id, position)`` or ``(record_id, from_pos, to_pos)``
    and dict forms with common aliases.
    """
    if isinstance(entry, dict):
        record_id = entry.get("record_id", entry.get("id"))
        from_pos = entry.get("position")
        if from_pos is None:
            from_pos = entry.get("from_position", entry.get("from_pos", entry.get("from")))
        to_pos = entry.get("to_position")
        if to_pos is None:
            to_pos = entry.get("to_pos", entry.get("target_position", entry.get("target_pos")))
        to_box = entry.get("to_box")

        if record_id is None or from_pos is None:
            raise ValueError("每个条目必须包含 record_id/id 和 position/from_position")
        if to_pos is None:
            return (int(record_id), int(from_pos))
        if to_box is not None:
            return (int(record_id), int(from_pos), int(to_pos), int(to_box))
        return (int(record_id), int(from_pos), int(to_pos))

    if isinstance(entry, (list, tuple)):
        if len(entry) == 2:
            return (int(entry[0]), int(entry[1]))
        if len(entry) == 3:
            return (int(entry[0]), int(entry[1]), int(entry[2]))
        if len(entry) == 4:
            return (int(entry[0]), int(entry[1]), int(entry[2]), int(entry[3]))
        raise ValueError("每个条目必须是 (record_id, position) 或 (record_id, from_position, to_position[, to_box])")

    raise ValueError("每个条目必须是 tuple/list/dict")


def _replace_position_once(positions, old_pos, new_pos):
    """Replace the first occurrence of old_pos with new_pos."""
    replaced = False
    updated = []
    for pos in positions:
        if not replaced and pos == old_pos:
            updated.append(new_pos)
            replaced = True
        else:
            updated.append(pos)
    return updated, replaced


def _build_move_event(date_str, from_position, to_position, note=None,
                      paired_record_id=None, from_box=None, to_box=None):
    """Build normalized move event payload."""
    event = {
        "date": date_str,
        "action": "move",
        "positions": [from_position],
        "from_position": from_position,
        "to_position": to_position,
    }
    if from_box is not None:
        event["from_box"] = from_box
    if to_box is not None:
        event["to_box"] = to_box
    if paired_record_id is not None:
        event["paired_record_id"] = paired_record_id
    if note:
        event["note"] = note
    return event


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


def _append_failed_audit(
    yaml_path,
    action,
    source,
    tool_name,
    actor_context=None,
    details=None,
    tool_input=None,
    error_code=None,
    message=None,
    errors=None,
    before_data=None,
):
    """Best-effort audit append for blocked/failed write operations."""
    meta = _build_audit_meta(
        action=action,
        source=source,
        tool_name=tool_name,
        actor_context=actor_context,
        details=details,
        tool_input=tool_input,
    )
    meta["status"] = "failed"
    error_payload = {
        "error_code": error_code,
        "message": message,
    }
    if errors:
        error_payload["errors"] = errors
    meta["error"] = error_payload

    snapshot = before_data if isinstance(before_data, dict) else None
    try:
        append_audit_event(
            yaml_path=yaml_path,
            before_data=snapshot,
            after_data=snapshot,
            backup_path=None,
            warnings=[],
            audit_meta=meta,
        )
    except Exception:
        # Failure auditing must never change tool behavior.
        return


def _failure_result(
    yaml_path,
    action,
    source,
    tool_name,
    error_code,
    message,
    actor_context=None,
    details=None,
    tool_input=None,
    before_data=None,
    errors=None,
    extra=None,
):
    payload = {
        "ok": False,
        "error_code": error_code,
        "message": message,
    }
    if errors is not None:
        payload["errors"] = errors
    if extra:
        payload.update(extra)

    _append_failed_audit(
        yaml_path=yaml_path,
        action=action,
        source=source,
        tool_name=tool_name,
        actor_context=actor_context,
        details=details,
        tool_input=tool_input,
        error_code=error_code,
        message=message,
        errors=errors,
        before_data=before_data,
    )
    return payload


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
    auto_html=None,
    auto_server=None,
    auto_backup=True,
):
    """Add a new frozen entry using the shared tool flow."""
    action = "add_entry"
    tool_name = "tool_add_entry"
    tool_input = {
        "parent_cell_line": parent_cell_line,
        "short_name": short_name,
        "box": box,
        "positions": list(positions) if isinstance(positions, list) else positions,
        "frozen_at": frozen_at,
        "plasmid_name": plasmid_name,
        "plasmid_id": plasmid_id,
        "note": note,
        "dry_run": bool(dry_run),
    }

    if VALID_CELL_LINES and parent_cell_line not in VALID_CELL_LINES:
        return _failure_result(
            yaml_path=yaml_path,
            action=action,
            source=source,
            tool_name=tool_name,
            error_code="invalid_cell_line",
            message=f"parent_cell_line 不在允许列表中: {parent_cell_line}",
            actor_context=actor_context,
            tool_input=tool_input,
            details={"parent_cell_line": parent_cell_line},
            extra={"allowed_cell_lines": list(VALID_CELL_LINES)},
        )

    if not validate_date(frozen_at):
        return _failure_result(
            yaml_path=yaml_path,
            action=action,
            source=source,
            tool_name=tool_name,
            error_code="invalid_date",
            message=f"日期格式无效: {frozen_at}",
            actor_context=actor_context,
            tool_input=tool_input,
            details={"frozen_at": frozen_at},
        )

    if box < BOX_RANGE[0] or box > BOX_RANGE[1]:
        return _failure_result(
            yaml_path=yaml_path,
            action=action,
            source=source,
            tool_name=tool_name,
            error_code="invalid_box",
            message=f"盒子编号必须在 {BOX_RANGE[0]}-{BOX_RANGE[1]} 之间",
            actor_context=actor_context,
            tool_input=tool_input,
            details={"box": box},
        )

    if not positions:
        return _failure_result(
            yaml_path=yaml_path,
            action=action,
            source=source,
            tool_name=tool_name,
            error_code="empty_positions",
            message="必须指定至少一个位置",
            actor_context=actor_context,
            tool_input=tool_input,
        )

    try:
        data = load_yaml(yaml_path)
    except Exception as exc:
        return _failure_result(
            yaml_path=yaml_path,
            action=action,
            source=source,
            tool_name=tool_name,
            error_code="load_failed",
            message=f"无法读取YAML文件: {exc}",
            actor_context=actor_context,
            tool_input=tool_input,
            details={"load_error": str(exc)},
        )

    records = data.get("inventory", [])
    conflicts = check_position_conflicts(records, box, positions)
    if conflicts:
        return _failure_result(
            yaml_path=yaml_path,
            action=action,
            source=source,
            tool_name=tool_name,
            error_code="position_conflict",
            message="位置冲突",
            actor_context=actor_context,
            tool_input=tool_input,
            before_data=data,
            details={"box": box, "positions": list(positions), "conflict_count": len(conflicts)},
            extra={"conflicts": conflicts},
        )

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
            validation_error = _validate_data_or_error(candidate_data) or {
                "error_code": "integrity_validation_failed",
                "message": "写入被阻止：完整性校验失败",
                "errors": [],
            }
            return _failure_result(
                yaml_path=yaml_path,
                action=action,
                source=source,
                tool_name=tool_name,
                error_code=validation_error.get("error_code", "integrity_validation_failed"),
                message=validation_error.get("message", "写入被阻止：完整性校验失败"),
                actor_context=actor_context,
                tool_input=tool_input,
                before_data=data,
                errors=validation_error.get("errors"),
            )
        candidate_inventory.append(new_record)
        validation_error = _validate_data_or_error(candidate_data)
        if validation_error:
            validation_error = validation_error or {
                "error_code": "integrity_validation_failed",
                "message": "写入被阻止：完整性校验失败",
                "errors": [],
            }
            return _failure_result(
                yaml_path=yaml_path,
                action=action,
                source=source,
                tool_name=tool_name,
                error_code=validation_error.get("error_code", "integrity_validation_failed"),
                message=validation_error.get("message", "写入被阻止：完整性校验失败"),
                actor_context=actor_context,
                tool_input=tool_input,
                before_data=data,
                errors=validation_error.get("errors"),
                details={"new_id": new_id, "box": box, "positions": list(positions)},
            )

        _backup_path = write_yaml(
            candidate_data,
            yaml_path,
            auto_html=auto_html,
            auto_server=auto_server,
            auto_backup=auto_backup,
            audit_meta=_build_audit_meta(
                action=action,
                source=source,
                tool_name=tool_name,
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
        return _failure_result(
            yaml_path=yaml_path,
            action=action,
            source=source,
            tool_name=tool_name,
            error_code="write_failed",
            message=f"添加失败: {exc}",
            actor_context=actor_context,
            tool_input=tool_input,
            before_data=data,
            details={"new_id": new_id, "box": box},
        )

    return {
        "ok": True,
        "dry_run": False,
        "preview": preview,
        "result": {"new_id": new_id, "record": new_record},
        "backup_path": _backup_path,
    }


def tool_record_thaw(
    yaml_path,
    record_id,
    position,
    date_str,
    action="取出",
    note=None,
    to_position=None,
    to_box=None,
    dry_run=False,
    actor_context=None,
    source="tool_api",
    auto_html=None,
    auto_server=None,
    auto_backup=True,
):
    """Record one thaw/takeout/discard/move operation via shared tool flow."""
    audit_action = "record_thaw"
    tool_name = "tool_record_thaw"
    tool_input = {
        "record_id": record_id,
        "position": position,
        "to_position": to_position,
        "to_box": to_box,
        "date": date_str,
        "action": action,
        "note": note,
        "dry_run": bool(dry_run),
    }

    if not validate_date(date_str):
        return _failure_result(
            yaml_path=yaml_path,
            action=audit_action,
            source=source,
            tool_name=tool_name,
            error_code="invalid_date",
            message=f"日期格式无效: {date_str}",
            actor_context=actor_context,
            tool_input=tool_input,
            details={"date": date_str},
        )

    if position < POSITION_RANGE[0] or position > POSITION_RANGE[1]:
        return _failure_result(
            yaml_path=yaml_path,
            action=audit_action,
            source=source,
            tool_name=tool_name,
            error_code="invalid_position",
            message=f"位置编号必须在 {POSITION_RANGE[0]}-{POSITION_RANGE[1]} 之间",
            actor_context=actor_context,
            tool_input=tool_input,
            details={"position": position},
        )

    action_en = normalize_action(action)
    if not action_en:
        return _failure_result(
            yaml_path=yaml_path,
            action=audit_action,
            source=source,
            tool_name=tool_name,
            error_code="invalid_action",
            message="操作类型必须是 取出/复苏/扔掉/移动",
            actor_context=actor_context,
            tool_input=tool_input,
            details={"action": action},
        )
    action_cn = ACTION_LABEL.get(action_en, action)

    move_to_position = None
    if action_en == "move":
        if to_position in (None, ""):
            return _failure_result(
                yaml_path=yaml_path,
                action=audit_action,
                source=source,
                tool_name=tool_name,
                error_code="invalid_move_target",
                message="移动操作必须提供 to_position（目标位置）",
                actor_context=actor_context,
                tool_input=tool_input,
                details={"record_id": record_id, "position": position},
            )
        try:
            move_to_position = int(to_position)
        except (TypeError, ValueError):
            return _failure_result(
                yaml_path=yaml_path,
                action=audit_action,
                source=source,
                tool_name=tool_name,
                error_code="invalid_move_target",
                message=f"目标位置必须是整数: {to_position}",
                actor_context=actor_context,
                tool_input=tool_input,
                details={"to_position": to_position},
            )
        if move_to_position < POSITION_RANGE[0] or move_to_position > POSITION_RANGE[1]:
            return _failure_result(
                yaml_path=yaml_path,
                action=audit_action,
                source=source,
                tool_name=tool_name,
                error_code="invalid_position",
                message=f"目标位置编号必须在 {POSITION_RANGE[0]}-{POSITION_RANGE[1]} 之间",
                actor_context=actor_context,
                tool_input=tool_input,
                details={"to_position": move_to_position},
            )
        if move_to_position == position:
            return _failure_result(
                yaml_path=yaml_path,
                action=audit_action,
                source=source,
                tool_name=tool_name,
                error_code="invalid_move_target",
                message="移动操作的起始位置与目标位置不能相同",
                actor_context=actor_context,
                tool_input=tool_input,
                details={"position": position, "to_position": move_to_position},
            )

    try:
        data = load_yaml(yaml_path)
    except Exception as exc:
        return _failure_result(
            yaml_path=yaml_path,
            action=audit_action,
            source=source,
            tool_name=tool_name,
            error_code="load_failed",
            message=f"无法读取YAML文件: {exc}",
            actor_context=actor_context,
            tool_input=tool_input,
            details={"load_error": str(exc)},
        )

    records = data.get("inventory", [])
    idx, record = find_record_by_id(records, record_id)
    if record is None:
        return _failure_result(
            yaml_path=yaml_path,
            action=audit_action,
            source=source,
            tool_name=tool_name,
            error_code="record_not_found",
            message=f"未找到 ID={record_id} 的记录",
            actor_context=actor_context,
            tool_input=tool_input,
            before_data=data,
            details={"record_id": record_id},
        )

    positions = record.get("positions", [])
    if position not in positions:
        return _failure_result(
            yaml_path=yaml_path,
            action=audit_action,
            source=source,
            tool_name=tool_name,
            error_code="position_not_found",
            message=f"位置 {position} 不在记录 #{record_id} 的现有位置中",
            actor_context=actor_context,
            tool_input=tool_input,
            before_data=data,
            details={"record_id": record_id, "position": position},
            extra={"current_positions": positions},
        )

    swap_target = None
    swap_target_new_positions = None
    swap_target_event = None

    if action_en == "move":
        new_positions, replaced = _replace_position_once(list(positions), position, move_to_position)
        if not replaced:
            return _failure_result(
                yaml_path=yaml_path,
                action=audit_action,
                source=source,
                tool_name=tool_name,
                error_code="position_not_found",
                message=f"位置 {position} 不在记录 #{record_id} 的现有位置中",
                actor_context=actor_context,
                tool_input=tool_input,
                before_data=data,
                details={"record_id": record_id, "position": position},
                extra={"current_positions": positions},
            )

        box = record.get("box")
        cross_box = to_box is not None and to_box != box

        if cross_box:
            if not validate_box(to_box):
                return _failure_result(
                    yaml_path=yaml_path,
                    action=audit_action,
                    source=source,
                    tool_name=tool_name,
                    error_code="invalid_box",
                    message=f"目标盒子编号 {to_box} 超出范围 ({BOX_RANGE[0]}-{BOX_RANGE[1]})",
                    actor_context=actor_context,
                    tool_input=tool_input,
                    before_data=data,
                    details={"to_box": to_box},
                )
            # Cross-box: check if target (to_box, to_pos) is occupied
            target_box = to_box
            for other_idx, other in enumerate(records):
                if other.get("box") != target_box:
                    continue
                other_positions = other.get("positions") or []
                if move_to_position in other_positions:
                    return _failure_result(
                        yaml_path=yaml_path,
                        action=audit_action,
                        source=source,
                        tool_name=tool_name,
                        error_code="position_conflict",
                        message=f"目标盒子 {target_box} 位置 {move_to_position} 已被记录 #{other.get('id')} 占用",
                        actor_context=actor_context,
                        tool_input=tool_input,
                        before_data=data,
                        details={
                            "record_id": record_id,
                            "to_box": target_box,
                            "to_position": move_to_position,
                            "blocking_record_id": other.get("id"),
                        },
                    )
        else:
            # Same-box: existing swap logic
            for other_idx, other in enumerate(records):
                if other.get("box") != box:
                    continue
                other_positions = other.get("positions") or []
                if move_to_position in other_positions:
                    if other_idx == idx:
                        return _failure_result(
                            yaml_path=yaml_path,
                            action=audit_action,
                            source=source,
                            tool_name=tool_name,
                            error_code="invalid_move_target",
                            message=f"目标位置 {move_to_position} 已属于记录 #{record_id}，无需移动",
                            actor_context=actor_context,
                            tool_input=tool_input,
                            before_data=data,
                            details={"record_id": record_id, "to_position": move_to_position},
                        )

                    swap_target_new_positions, swap_replaced = _replace_position_once(
                        list(other_positions),
                        move_to_position,
                        position,
                    )
                    if not swap_replaced:
                        return _failure_result(
                            yaml_path=yaml_path,
                            action=audit_action,
                            source=source,
                            tool_name=tool_name,
                            error_code="position_conflict",
                            message="目标位置冲突，无法完成换位",
                            actor_context=actor_context,
                            tool_input=tool_input,
                            before_data=data,
                            details={
                                "record_id": record_id,
                                "position": position,
                                "to_position": move_to_position,
                                "swap_record_id": other.get("id"),
                            },
                        )

                    swap_target = {
                        "idx": other_idx,
                        "record": other,
                        "old_positions": list(other_positions),
                    }
                    break

        new_event = _build_move_event(
            date_str=date_str,
            from_position=position,
            to_position=move_to_position,
            note=note,
            paired_record_id=swap_target["record"].get("id") if swap_target else None,
            from_box=box if cross_box else None,
            to_box=to_box if cross_box else None,
        )
        if swap_target:
            swap_target_event = _build_move_event(
                date_str=date_str,
                from_position=move_to_position,
                to_position=position,
                note=note,
                paired_record_id=record_id,
            )
    else:
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
        "to_position": move_to_position,
        "to_box": to_box,
        "note": note,
        "date": date_str,
        "positions_before": positions,
        "positions_after": new_positions,
    }
    if swap_target:
        preview["swap_with_record_id"] = swap_target["record"].get("id")
        preview["swap_with_short_name"] = swap_target["record"].get("short_name")
        preview["swap_positions_before"] = swap_target["old_positions"]
        preview["swap_positions_after"] = swap_target_new_positions

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
            validation_error = _validate_data_or_error(candidate_data) or {
                "error_code": "integrity_validation_failed",
                "message": "写入被阻止：完整性校验失败",
                "errors": [],
            }
            return _failure_result(
                yaml_path=yaml_path,
                action=audit_action,
                source=source,
                tool_name=tool_name,
                error_code=validation_error.get("error_code", "integrity_validation_failed"),
                message=validation_error.get("message", "写入被阻止：完整性校验失败"),
                actor_context=actor_context,
                tool_input=tool_input,
                before_data=data,
                errors=validation_error.get("errors"),
            )

        candidate_records[idx]["positions"] = new_positions
        if to_box is not None and to_box != record.get("box"):
            candidate_records[idx]["box"] = to_box
        thaw_events = candidate_records[idx].get("thaw_events")
        if thaw_events is None:
            candidate_records[idx]["thaw_events"] = []
            thaw_events = candidate_records[idx]["thaw_events"]
        if not isinstance(thaw_events, list):
            validation_error = _validate_data_or_error(candidate_data) or {
                "error_code": "integrity_validation_failed",
                "message": "写入被阻止：完整性校验失败",
                "errors": [],
            }
            return _failure_result(
                yaml_path=yaml_path,
                action=audit_action,
                source=source,
                tool_name=tool_name,
                error_code=validation_error.get("error_code", "integrity_validation_failed"),
                message=validation_error.get("message", "写入被阻止：完整性校验失败"),
                actor_context=actor_context,
                tool_input=tool_input,
                before_data=data,
                errors=validation_error.get("errors"),
            )
        thaw_events.append(new_event)

        affected_record_ids = [record_id]
        if swap_target:
            swap_idx = swap_target["idx"]
            candidate_records[swap_idx]["positions"] = swap_target_new_positions
            swap_events = candidate_records[swap_idx].get("thaw_events")
            if swap_events is None:
                candidate_records[swap_idx]["thaw_events"] = []
                swap_events = candidate_records[swap_idx]["thaw_events"]
            if not isinstance(swap_events, list):
                validation_error = _validate_data_or_error(candidate_data) or {
                    "error_code": "integrity_validation_failed",
                    "message": "写入被阻止：完整性校验失败",
                    "errors": [],
                }
                return _failure_result(
                    yaml_path=yaml_path,
                    action=audit_action,
                    source=source,
                    tool_name=tool_name,
                    error_code=validation_error.get("error_code", "integrity_validation_failed"),
                    message=validation_error.get("message", "写入被阻止：完整性校验失败"),
                    actor_context=actor_context,
                    tool_input=tool_input,
                    before_data=data,
                    errors=validation_error.get("errors"),
                )
            swap_events.append(swap_target_event)
            affected_record_ids.append(swap_target["record"].get("id"))

        validation_error = _validate_data_or_error(candidate_data)
        if validation_error:
            validation_error = validation_error or {
                "error_code": "integrity_validation_failed",
                "message": "写入被阻止：完整性校验失败",
                "errors": [],
            }
            return _failure_result(
                yaml_path=yaml_path,
                action=audit_action,
                source=source,
                tool_name=tool_name,
                error_code=validation_error.get("error_code", "integrity_validation_failed"),
                message=validation_error.get("message", "写入被阻止：完整性校验失败"),
                actor_context=actor_context,
                tool_input=tool_input,
                before_data=data,
                errors=validation_error.get("errors"),
                details={
                    "record_id": record_id,
                    "position": position,
                    "to_position": move_to_position,
                    "action": action_en,
                    "date": date_str,
                },
            )

        _backup_path = write_yaml(
            candidate_data,
            yaml_path,
            auto_html=auto_html,
            auto_server=auto_server,
            auto_backup=auto_backup,
            audit_meta=_build_audit_meta(
                action=audit_action,
                source=source,
                tool_name=tool_name,
                actor_context=actor_context,
                details={
                    "record_id": record_id,
                    "box": record.get("box"),
                    "position": position,
                    "to_position": move_to_position,
                    "action": action_en,
                    "date": date_str,
                    "affected_record_ids": affected_record_ids,
                },
                tool_input={
                    "record_id": record_id,
                    "position": position,
                    "to_position": move_to_position,
                    "date": date_str,
                    "action": action,
                    "note": note,
                },
            ),
        )
    except Exception as exc:
        return _failure_result(
            yaml_path=yaml_path,
            action=audit_action,
            source=source,
            tool_name=tool_name,
            error_code="write_failed",
            message=f"更新失败: {exc}",
            actor_context=actor_context,
            tool_input=tool_input,
            before_data=data,
            details={
                "record_id": record_id,
                "position": position,
                "to_position": move_to_position,
                "action": action_en,
            },
        )

    result_payload = {
        "record_id": record_id,
        "remaining_positions": new_positions,
    }
    if move_to_position is not None:
        result_payload["to_position"] = move_to_position
    if swap_target:
        result_payload["swap_with_record_id"] = swap_target["record"].get("id")

    return {
        "ok": True,
        "dry_run": False,
        "preview": preview,
        "result": result_payload,
        "backup_path": _backup_path,
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
    auto_html=None,
    auto_server=None,
    auto_backup=True,
):
    """Record batch thaw/takeout/discard/move operations via shared tool flow."""
    audit_action = "batch_thaw"
    tool_name = "tool_batch_thaw"
    tool_input = {
        "entries": list(entries) if isinstance(entries, (list, tuple)) else entries,
        "date": date_str,
        "action": action,
        "note": note,
        "dry_run": bool(dry_run),
    }

    if not validate_date(date_str):
        return _failure_result(
            yaml_path=yaml_path,
            action=audit_action,
            source=source,
            tool_name=tool_name,
            error_code="invalid_date",
            message=f"日期格式无效: {date_str}",
            actor_context=actor_context,
            tool_input=tool_input,
            details={"date": date_str},
        )

    if not entries:
        return _failure_result(
            yaml_path=yaml_path,
            action=audit_action,
            source=source,
            tool_name=tool_name,
            error_code="empty_entries",
            message="未指定任何操作",
            actor_context=actor_context,
            tool_input=tool_input,
        )

    action_en = normalize_action(action)
    if not action_en:
        return _failure_result(
            yaml_path=yaml_path,
            action=audit_action,
            source=source,
            tool_name=tool_name,
            error_code="invalid_action",
            message="操作类型必须是 取出/复苏/扔掉/移动",
            actor_context=actor_context,
            tool_input=tool_input,
            details={"action": action},
        )

    if isinstance(entries, str):
        try:
            entries = parse_batch_entries(entries)
        except ValueError as exc:
            return _failure_result(
                yaml_path=yaml_path,
                action=audit_action,
                source=source,
                tool_name=tool_name,
                error_code="validation_failed",
                message="批量操作参数校验失败",
                actor_context=actor_context,
                tool_input=tool_input,
                errors=[str(exc)],
            )

    normalized_entries = []
    normalize_errors = []
    for idx, entry in enumerate(entries, 1):
        try:
            normalized_entries.append(_coerce_batch_entry(entry))
        except Exception as exc:
            normalize_errors.append(f"第{idx}条: {exc}")

    if normalize_errors:
        return _failure_result(
            yaml_path=yaml_path,
            action=audit_action,
            source=source,
            tool_name=tool_name,
            error_code="validation_failed",
            message="批量操作参数校验失败",
            actor_context=actor_context,
            tool_input=tool_input,
            errors=normalize_errors,
        )

    try:
        data = load_yaml(yaml_path)
    except Exception as exc:
        return _failure_result(
            yaml_path=yaml_path,
            action=audit_action,
            source=source,
            tool_name=tool_name,
            error_code="load_failed",
            message=f"无法读取YAML文件: {exc}",
            actor_context=actor_context,
            tool_input=tool_input,
            details={"load_error": str(exc)},
        )

    records = data.get("inventory", [])
    operations = []
    errors = []

    if action_en == "move":
        simulated_positions = {}
        simulated_box = {}
        position_owner = {}
        events_by_idx = defaultdict(list)
        touched_indices = set()

        for idx, rec in enumerate(records):
            rec_positions = list(rec.get("positions") or [])
            simulated_positions[idx] = rec_positions
            box = rec.get("box")
            simulated_box[idx] = box
            for pos in rec_positions:
                key = (box, pos)
                if key in position_owner and position_owner[key] != idx:
                    errors.append(f"盒子 {box} 位置 {pos} 已存在冲突，无法执行移动")
                else:
                    position_owner[key] = idx

        for row_idx, entry in enumerate(normalized_entries, 1):
            if len(entry) < 3:
                errors.append(f"第{row_idx}条: move 操作必须使用 id:from->to 格式")
                continue

            record_id, from_pos, to_pos = entry[0], entry[1], entry[2]
            entry_to_box = entry[3] if len(entry) >= 4 else None

            if from_pos < POSITION_RANGE[0] or from_pos > POSITION_RANGE[1]:
                errors.append(
                    f"第{row_idx}条 ID {record_id}: 起始位置 {from_pos} 必须在 {POSITION_RANGE[0]}-{POSITION_RANGE[1]} 之间"
                )
                continue
            if to_pos < POSITION_RANGE[0] or to_pos > POSITION_RANGE[1]:
                errors.append(
                    f"第{row_idx}条 ID {record_id}: 目标位置 {to_pos} 必须在 {POSITION_RANGE[0]}-{POSITION_RANGE[1]} 之间"
                )
                continue
            if entry_to_box is not None and not validate_box(entry_to_box):
                errors.append(
                    f"第{row_idx}条 ID {record_id}: 目标盒子 {entry_to_box} 超出范围 ({BOX_RANGE[0]}-{BOX_RANGE[1]})"
                )
                continue

            idx, record = find_record_by_id(records, record_id)
            if record is None:
                errors.append(f"第{row_idx}条 ID {record_id}: 未找到该记录")
                continue

            current_box = simulated_box.get(idx, record.get("box"))
            cross_box = entry_to_box is not None and entry_to_box != current_box

            if not cross_box and from_pos == to_pos:
                errors.append(f"第{row_idx}条 ID {record_id}: 起始位置与目标位置不能相同")
                continue

            source_before = list(simulated_positions.get(idx, []))
            if from_pos not in source_before:
                errors.append(f"第{row_idx}条 ID {record_id}: 起始位置 {from_pos} 不在现有位置 {source_before} 中")
                continue

            source_after, replaced = _replace_position_once(source_before, from_pos, to_pos)
            if not replaced:
                errors.append(f"第{row_idx}条 ID {record_id}: 无法在现有位置中替换 {from_pos}")
                continue

            target_box = entry_to_box if cross_box else current_box
            dest_idx = position_owner.get((target_box, to_pos))
            if dest_idx == idx:
                errors.append(f"第{row_idx}条 ID {record_id}: 目标位置 {to_pos} 已属于该记录")
                continue

            dest_before = None
            dest_after = None
            dest_record = None
            if dest_idx is not None:
                if cross_box:
                    # Cross-box: no swap support, reject occupied target
                    dest_record = records[dest_idx]
                    errors.append(
                        f"第{row_idx}条 ID {record_id}: 目标盒子 {target_box} 位置 {to_pos} 已被记录 #{dest_record.get('id')} 占用"
                    )
                    continue
                else:
                    # Same-box: swap
                    dest_record = records[dest_idx]
                    dest_before = list(simulated_positions.get(dest_idx, []))
                    dest_after, dest_replaced = _replace_position_once(dest_before, to_pos, from_pos)
                    if not dest_replaced:
                        errors.append(
                            f"第{row_idx}条 ID {record_id}: 目标位置 {to_pos} 冲突，记录 #{dest_record.get('id')} 无法换位"
                        )
                        continue

            simulated_positions[idx] = source_after
            touched_indices.add(idx)

            # Update position_owner and simulated_box
            old_key = (current_box, from_pos)
            if dest_idx is None:
                position_owner.pop(old_key, None)
            else:
                simulated_positions[dest_idx] = dest_after
                touched_indices.add(dest_idx)
                position_owner[old_key] = dest_idx
            position_owner[(target_box, to_pos)] = idx

            if cross_box:
                simulated_box[idx] = entry_to_box

            source_event = _build_move_event(
                date_str=date_str,
                from_position=from_pos,
                to_position=to_pos,
                note=note,
                paired_record_id=dest_record.get("id") if dest_record else None,
                from_box=current_box if cross_box else None,
                to_box=entry_to_box if cross_box else None,
            )
            events_by_idx[idx].append(source_event)

            if dest_record is not None:
                events_by_idx[dest_idx].append(
                    _build_move_event(
                        date_str=date_str,
                        from_position=to_pos,
                        to_position=from_pos,
                        note=note,
                        paired_record_id=record_id,
                    )
                )

            op = {
                "idx": idx,
                "record_id": record_id,
                "record": record,
                "position": from_pos,
                "to_position": to_pos,
                "old_positions": source_before,
                "new_positions": source_after,
            }
            if entry_to_box is not None:
                op["to_box"] = entry_to_box
            if dest_record is not None:
                op["swap_with_record_id"] = dest_record.get("id")
                op["swap_with_short_name"] = dest_record.get("short_name")
                op["swap_old_positions"] = dest_before
                op["swap_new_positions"] = dest_after
            operations.append(op)

        if errors:
            return _failure_result(
                yaml_path=yaml_path,
                action=audit_action,
                source=source,
                tool_name=tool_name,
                error_code="validation_failed",
                message="批量操作参数校验失败",
                actor_context=actor_context,
                tool_input=tool_input,
                before_data=data,
                errors=errors,
                extra={"operations": operations},
                details={"error_count": len(errors)},
            )

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
                    "to_position": op.get("to_position"),
                    "old_positions": op["old_positions"],
                    "new_positions": op["new_positions"],
                    "swap_with_record_id": op.get("swap_with_record_id"),
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
                validation_error = _validate_data_or_error(candidate_data) or {
                    "error_code": "integrity_validation_failed",
                    "message": "写入被阻止：完整性校验失败",
                    "errors": [],
                }
                return _failure_result(
                    yaml_path=yaml_path,
                    action=audit_action,
                    source=source,
                    tool_name=tool_name,
                    error_code=validation_error.get("error_code", "integrity_validation_failed"),
                    message=validation_error.get("message", "写入被阻止：完整性校验失败"),
                    actor_context=actor_context,
                    tool_input=tool_input,
                    before_data=data,
                    errors=validation_error.get("errors"),
                )

            for idx in touched_indices:
                candidate_records[idx]["positions"] = list(simulated_positions[idx])
                if simulated_box.get(idx) != records[idx].get("box"):
                    candidate_records[idx]["box"] = simulated_box[idx]

            for idx in touched_indices:
                events = events_by_idx.get(idx) or []
                if not events:
                    continue
                thaw_events = candidate_records[idx].get("thaw_events")
                if thaw_events is None:
                    candidate_records[idx]["thaw_events"] = []
                    thaw_events = candidate_records[idx]["thaw_events"]
                if not isinstance(thaw_events, list):
                    validation_error = _validate_data_or_error(candidate_data) or {
                        "error_code": "integrity_validation_failed",
                        "message": "写入被阻止：完整性校验失败",
                        "errors": [],
                    }
                    return _failure_result(
                        yaml_path=yaml_path,
                        action=audit_action,
                        source=source,
                        tool_name=tool_name,
                        error_code=validation_error.get("error_code", "integrity_validation_failed"),
                        message=validation_error.get("message", "写入被阻止：完整性校验失败"),
                        actor_context=actor_context,
                        tool_input=tool_input,
                        before_data=data,
                        errors=validation_error.get("errors"),
                    )
                thaw_events.extend(events)

            validation_error = _validate_data_or_error(candidate_data)
            if validation_error:
                validation_error = validation_error or {
                    "error_code": "integrity_validation_failed",
                    "message": "写入被阻止：完整性校验失败",
                    "errors": [],
                }
                return _failure_result(
                    yaml_path=yaml_path,
                    action=audit_action,
                    source=source,
                    tool_name=tool_name,
                    error_code=validation_error.get("error_code", "integrity_validation_failed"),
                    message=validation_error.get("message", "写入被阻止：完整性校验失败"),
                    actor_context=actor_context,
                    tool_input=tool_input,
                    before_data=data,
                    errors=validation_error.get("errors"),
                    details={"count": len(operations), "action": action_en, "date": date_str},
                )

            affected_ids = sorted({records[idx].get("id") for idx in touched_indices})
            _backup_path = write_yaml(
                candidate_data,
                yaml_path,
                auto_html=auto_html,
                auto_server=auto_server,
                auto_backup=auto_backup,
                audit_meta=_build_audit_meta(
                    action=audit_action,
                    source=source,
                    tool_name=tool_name,
                    actor_context=actor_context,
                    details={
                        "count": len(operations),
                        "action": action_en,
                        "date": date_str,
                        "record_ids": [op["record_id"] for op in operations],
                        "affected_record_ids": affected_ids,
                    },
                    tool_input={
                        "entries": list(normalized_entries),
                        "date": date_str,
                        "action": action,
                        "note": note,
                    },
                ),
            )
        except Exception as exc:
            return _failure_result(
                yaml_path=yaml_path,
                action=audit_action,
                source=source,
                tool_name=tool_name,
                error_code="write_failed",
                message=f"批量更新失败: {exc}",
                actor_context=actor_context,
                tool_input=tool_input,
                before_data=data,
                details={"count": len(operations), "action": action_en, "date": date_str},
            )

        return {
            "ok": True,
            "dry_run": False,
            "preview": preview,
            "result": {
                "count": len(operations),
                "record_ids": [op["record_id"] for op in operations],
                "affected_record_ids": affected_ids,
            },
            "backup_path": _backup_path,
        }

    # Track cumulative position changes per record index so that multiple
    # entries targeting the same record correctly build on each other.
    cumulative_positions: dict[int, list[int]] = {}

    for row_idx, entry in enumerate(normalized_entries, 1):
        if len(entry) != 2:
            errors.append(f"第{row_idx}条: 非移动操作必须使用 id:position 格式")
            continue

        record_id, position = entry
        if position < POSITION_RANGE[0] or position > POSITION_RANGE[1]:
            errors.append(f"ID {record_id}: 位置编号 {position} 必须在 {POSITION_RANGE[0]}-{POSITION_RANGE[1]} 之间")
            continue

        idx, record = find_record_by_id(records, record_id)
        if record is None:
            errors.append(f"ID {record_id}: 未找到该记录")
            continue

        # Use cumulative positions if this record was already seen,
        # otherwise start from the original record positions.
        if idx in cumulative_positions:
            current_positions = cumulative_positions[idx]
        else:
            current_positions = list(record.get("positions", []))

        if position not in current_positions:
            errors.append(f"ID {record_id}: 位置 {position} 不在现有位置 {current_positions} 中")
            continue

        new_positions = [p for p in current_positions if p != position]
        cumulative_positions[idx] = new_positions

        operations.append(
            {
                "idx": idx,
                "record_id": record_id,
                "record": record,
                "position": position,
                "old_positions": current_positions.copy(),
                "new_positions": new_positions,
            }
        )

    if errors:
        return _failure_result(
            yaml_path=yaml_path,
            action=audit_action,
            source=source,
            tool_name=tool_name,
            error_code="validation_failed",
            message="批量操作参数校验失败",
            actor_context=actor_context,
            tool_input=tool_input,
            before_data=data,
            errors=errors,
            extra={"operations": operations},
            details={"error_count": len(errors)},
        )

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
            validation_error = _validate_data_or_error(candidate_data) or {
                "error_code": "integrity_validation_failed",
                "message": "写入被阻止：完整性校验失败",
                "errors": [],
            }
            return _failure_result(
                yaml_path=yaml_path,
                action=audit_action,
                source=source,
                tool_name=tool_name,
                error_code=validation_error.get("error_code", "integrity_validation_failed"),
                message=validation_error.get("message", "写入被阻止：完整性校验失败"),
                actor_context=actor_context,
                tool_input=tool_input,
                before_data=data,
                errors=validation_error.get("errors"),
            )

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
                validation_error = _validate_data_or_error(candidate_data) or {
                    "error_code": "integrity_validation_failed",
                    "message": "写入被阻止：完整性校验失败",
                    "errors": [],
                }
                return _failure_result(
                    yaml_path=yaml_path,
                    action=audit_action,
                    source=source,
                    tool_name=tool_name,
                    error_code=validation_error.get("error_code", "integrity_validation_failed"),
                    message=validation_error.get("message", "写入被阻止：完整性校验失败"),
                    actor_context=actor_context,
                    tool_input=tool_input,
                    before_data=data,
                    errors=validation_error.get("errors"),
                )
            thaw_events.append(new_event)

        validation_error = _validate_data_or_error(candidate_data)
        if validation_error:
            validation_error = validation_error or {
                "error_code": "integrity_validation_failed",
                "message": "写入被阻止：完整性校验失败",
                "errors": [],
            }
            return _failure_result(
                yaml_path=yaml_path,
                action=audit_action,
                source=source,
                tool_name=tool_name,
                error_code=validation_error.get("error_code", "integrity_validation_failed"),
                message=validation_error.get("message", "写入被阻止：完整性校验失败"),
                actor_context=actor_context,
                tool_input=tool_input,
                before_data=data,
                errors=validation_error.get("errors"),
                details={"count": len(operations), "action": action_en, "date": date_str},
            )

        _backup_path = write_yaml(
            candidate_data,
            yaml_path,
            auto_html=auto_html,
            auto_server=auto_server,
            auto_backup=auto_backup,
            audit_meta=_build_audit_meta(
                action=audit_action,
                source=source,
                tool_name=tool_name,
                actor_context=actor_context,
                details={
                    "count": len(operations),
                    "action": action_en,
                    "date": date_str,
                    "record_ids": [op["record_id"] for op in operations],
                },
                tool_input={
                    "entries": list(normalized_entries),
                    "date": date_str,
                    "action": action,
                    "note": note,
                },
            ),
        )
    except Exception as exc:
        return _failure_result(
            yaml_path=yaml_path,
            action=audit_action,
            source=source,
            tool_name=tool_name,
            error_code="write_failed",
            message=f"批量更新失败: {exc}",
            actor_context=actor_context,
            tool_input=tool_input,
            before_data=data,
            details={"count": len(operations), "action": action_en, "date": date_str},
        )

    return {
        "ok": True,
        "dry_run": False,
        "preview": preview,
        "result": {
            "count": len(operations),
            "record_ids": [op["record_id"] for op in operations],
        },
        "backup_path": _backup_path,
    }


def tool_list_backups(yaml_path):
    """List YAML backup files, newest first."""
    return list_yaml_backups(yaml_path)


def tool_rollback(
    yaml_path,
    backup_path=None,
    actor_context=None,
    source="tool_api",
):
    """Rollback inventory YAML using shared tool flow."""
    audit_action = "rollback"
    tool_name = "tool_rollback"
    tool_input = {
        "backup_path": backup_path,
    }
    current_data = None
    try:
        current_data = load_yaml(yaml_path)
    except Exception:
        current_data = None

    backups = list_yaml_backups(yaml_path)
    if not backups and not backup_path:
        return _failure_result(
            yaml_path=yaml_path,
            action=audit_action,
            source=source,
            tool_name=tool_name,
            error_code="no_backups",
            message="无可用备份，无法回滚",
            actor_context=actor_context,
            tool_input=tool_input,
            before_data=current_data,
        )

    target = backup_path or backups[0]
    try:
        backup_data = load_yaml(target)
    except Exception as exc:
        return _failure_result(
            yaml_path=yaml_path,
            action=audit_action,
            source=source,
            tool_name=tool_name,
            error_code="backup_load_failed",
            message=f"无法读取备份文件: {exc}",
            actor_context=actor_context,
            tool_input=tool_input,
            before_data=current_data,
            details={"requested_backup": target},
        )

    validation_error = _validate_data_or_error(
        backup_data,
        message_prefix="回滚被阻止：目标备份不满足完整性约束",
    )
    if validation_error:
        validation_error = validation_error or {
            "error_code": "rollback_backup_invalid",
            "message": "回滚被阻止：目标备份不满足完整性约束",
            "errors": [],
        }
        return _failure_result(
            yaml_path=yaml_path,
            action=audit_action,
            source=source,
            tool_name=tool_name,
            error_code="rollback_backup_invalid",
            message=validation_error.get("message", "回滚被阻止：目标备份不满足完整性约束"),
            actor_context=actor_context,
            tool_input=tool_input,
            before_data=current_data,
            errors=validation_error.get("errors"),
            details={"requested_backup": target},
            extra={"backup_path": target},
        )

    try:
        result = rollback_yaml(
            path=yaml_path,
            backup_path=target,
            audit_meta=_build_audit_meta(
                action=audit_action,
                source=source,
                tool_name=tool_name,
                actor_context=actor_context,
                details={"requested_backup": target},
                tool_input=tool_input,
            ),
        )
    except Exception as exc:
        return _failure_result(
            yaml_path=yaml_path,
            action=audit_action,
            source=source,
            tool_name=tool_name,
            error_code="rollback_failed",
            message=f"回滚失败: {exc}",
            actor_context=actor_context,
            tool_input=tool_input,
            before_data=current_data,
            details={"requested_backup": target},
        )

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
    """Query thaw/takeout/discard/move events by date mode and action."""
    action_filter = normalize_action(action) if action else None
    if action and not action_filter:
        return {
            "ok": False,
            "error_code": "invalid_action",
            "message": "操作类型必须是 取出/复苏/扔掉/移动 或 takeout/thaw/discard/move",
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
    elif date is not None:
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
    else:
        # No date specified - return all events
        mode = "all"
        target_dates = None
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

        if mode == "all":
            # Return all events with optional action filter
            filtered = [
                ev
                for ev in events
                if ev.get("date") and (not action_filter or ev.get("action") == action_filter)
            ]
        elif mode == "single":
            filtered = [
                ev
                for ev in events
                if ev.get("date") in target_dates and (not action_filter or ev.get("action") == action_filter)
            ]
        else:  # mode == "range" or "days"
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

    # Apply max_records to limit number of events (not records)
    if max_records and max_records > 0:
        # Collect all events and limit by max_records
        all_events = []
        for m in matched:
            events_for_record = m["events"][:max_records]
            remaining = max_records - len(events_for_record)
            if remaining > 0:
                max_records = remaining
                all_events.append({"record": m["record"], "events": events_for_record})
            else:
                if events_for_record:
                    all_events.append({"record": m["record"], "events": events_for_record})
                break
        records_to_return = all_events
    else:
        records_to_return = matched

    # Recalculate event_count based on filtered records
    final_event_count = sum(len(m["events"]) for m in records_to_return)

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
            "event_count": final_event_count,
        },
    }


def _collect_timeline_events(records, days=None):
    timeline = defaultdict(lambda: {"frozen": [], "thaw": [], "takeout": [], "discard": [], "move": []})
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
            if action not in {"thaw", "takeout", "discard", "move"}:
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
    total_move = 0
    active_days = 0
    for _, events in timeline.items():
        frozen = len(events["frozen"])
        thaw = len(events["thaw"])
        takeout = len(events["takeout"])
        discard = len(events["discard"])
        move = len(events["move"])
        total_frozen += frozen
        total_thaw += thaw
        total_takeout += takeout
        total_discard += discard
        total_move += move
        if frozen + thaw + takeout + discard + move > 0:
            active_days += 1

    return {
        "ok": True,
        "result": {
            "timeline": dict(timeline),
            "sorted_dates": sorted(timeline.keys(), reverse=True),
            "summary": {
                "active_days": active_days,
                "total_ops": total_frozen + total_thaw + total_takeout + total_discard + total_move,
                "frozen": total_frozen,
                "thaw": total_thaw,
                "takeout": total_takeout,
                "discard": total_discard,
                "move": total_move,
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
                box_recs.append({"box": int(box_key), "positions": group, "reason": "连续位置", "score": 100})

        if strategy == "same_row":
            for group in _find_same_row_slots(empty, count, layout)[:3]:
                box_recs.append({"box": int(box_key), "positions": group, "reason": "同一行", "score": 90})

        if not box_recs:
            box_recs.append({"box": int(box_key), "positions": empty[:count], "reason": "最早空位", "score": 50})

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

    # Flatten the stats structure for easier access, but keep nested structure for backward compatibility
    stats_nested = {
        "overall": {
            "total_occupied": total_occupied,
            "total_empty": total_capacity - total_occupied,
            "total_capacity": total_capacity,
            "occupancy_rate": overall_rate,
        },
        "boxes": box_stats,
        "cell_lines": dict(sorted(cell_lines.items(), key=lambda x: x[1], reverse=True)),
    }

    stats_result = {
        # Backward compatibility: keep nested structure
        "data": data,
        "layout": layout,
        "occupancy": occupancy,
        "stats": stats_nested,
        # Also provide flattened structure for easier access
        "total_slots": total_capacity,  # Total slots across all boxes
        "slots_per_box": total_slots,  # Slots per single box
        "total_occupied": total_occupied,
        "total_empty": total_capacity - total_occupied,
        "total_capacity": total_capacity,
        "occupancy_rate": overall_rate,
        "boxes": box_stats,
        "cell_lines": dict(sorted(cell_lines.items(), key=lambda x: x[1], reverse=True)),
        "record_count": len(records),
    }

    return {
        "ok": True,
        "result": stats_result,
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

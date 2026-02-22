"""Adjust-box-count write-operation implementations for Tool API."""

from copy import deepcopy

from ..position_fmt import get_box_numbers
from ..yaml_ops import load_yaml, write_yaml
from .write_common import api


def _prepare_adjust_box_count_context(
    *,
    data,
    yaml_path,
    audit_action,
    source,
    tool_name,
    actor_context,
    tool_input,
):
    if not isinstance(data, dict):
        data = {}
    records = data.get("inventory") or []
    layout = api._get_layout(data)
    current_boxes = list(get_box_numbers(layout))
    if not current_boxes:
        current_boxes = [1]

    candidate_data = deepcopy(data)
    if not isinstance(candidate_data, dict):
        candidate_data = {}
    meta = candidate_data.setdefault("meta", {})
    if not isinstance(meta, dict):
        return None, api._failure_result(
            yaml_path=yaml_path,
            action=audit_action,
            source=source,
            tool_name=tool_name,
            error_code="invalid_meta",
            message="Validation failed",
            actor_context=actor_context,
            tool_input=tool_input,
            before_data=data,
        )

    candidate_layout = meta.setdefault("box_layout", {})
    if not isinstance(candidate_layout, dict):
        return None, api._failure_result(
            yaml_path=yaml_path,
            action=audit_action,
            source=source,
            tool_name=tool_name,
            error_code="invalid_box_layout",
            message="Validation failed",
            actor_context=actor_context,
            tool_input=tool_input,
            before_data=data,
        )

    preview = {
        "operation": None,
        "box_numbers_before": current_boxes,
        "box_count_before": len(current_boxes),
    }

    return {
        "data": data,
        "records": records,
        "layout": layout,
        "current_boxes": current_boxes,
        "candidate_data": candidate_data,
        "candidate_layout": candidate_layout,
        "preview": preview,
    }, None


def _plan_adjust_box_count(
    *,
    op,
    count,
    box,
    renumber_mode,
    context,
    yaml_path,
    audit_action,
    source,
    tool_name,
    actor_context,
    tool_input,
):
    data = context["data"]
    records = context["records"]
    layout = context["layout"]
    current_boxes = context["current_boxes"]
    candidate_data = context["candidate_data"]
    preview = context["preview"]

    preview["operation"] = op

    if op == "add":
        try:
            add_count = int(count)
        except Exception:
            add_count = 0
        if add_count <= 0:
            return None, api._failure_result(
                yaml_path=yaml_path,
                action=audit_action,
                source=source,
                tool_name=tool_name,
                error_code="invalid_count",
                message="Validation failed",
                actor_context=actor_context,
                tool_input=tool_input,
                before_data=data,
                details={"count": count},
            )

        start = max(current_boxes) + 1 if current_boxes else 1
        added_boxes = list(range(start, start + add_count))
        new_boxes = current_boxes + added_boxes
        preview.update(
            {
                "added_boxes": added_boxes,
                "box_numbers_after": new_boxes,
                "box_count_after": len(new_boxes),
            }
        )
        return {"new_boxes": new_boxes, "preview": preview}, None

    try:
        target_box = int(box)
    except Exception:
        return None, api._failure_result(
            yaml_path=yaml_path,
            action=audit_action,
            source=source,
            tool_name=tool_name,
            error_code="invalid_box",
            message="Delete operation requires a valid box ID",
            actor_context=actor_context,
            tool_input=tool_input,
            before_data=data,
            details={"box": box},
        )

    if target_box not in current_boxes:
        return None, api._failure_result(
            yaml_path=yaml_path,
            action=audit_action,
            source=source,
            tool_name=tool_name,
            error_code="invalid_box",
            message=f"Box {target_box} does not exist (allowed: {api._format_box_constraint(layout)})",
            actor_context=actor_context,
            tool_input=tool_input,
            before_data=data,
            details={"box": target_box},
        )

    blocking_records = []
    for rec in records:
        if not isinstance(rec, dict):
            continue
        if rec.get("box") != target_box:
            continue
        blocking_records.append(rec)

    if blocking_records:
        blocking_ids = [rec.get("id") for rec in blocking_records if rec.get("id") is not None]
        active_ids = [
            rec.get("id")
            for rec in blocking_records
            if rec.get("id") is not None and rec.get("position") is not None
        ]
        historical_ids = [
            rec.get("id")
            for rec in blocking_records
            if rec.get("id") is not None and rec.get("position") is None
        ]
        if active_ids:
            block_message = "Cannot remove box with active records"
        else:
            block_message = "Cannot remove box with historical records"
        return None, api._failure_result(
            yaml_path=yaml_path,
            action=audit_action,
            source=source,
            tool_name=tool_name,
            error_code="box_not_empty",
            message=block_message,
            actor_context=actor_context,
            tool_input=tool_input,
            before_data=data,
            details={
                "box": target_box,
                "blocking_record_ids": blocking_ids,
                "active_blocking_record_ids": active_ids,
                "historical_blocking_record_ids": historical_ids,
            },
            extra={
                "blocking_record_ids": blocking_ids,
                "active_blocking_record_ids": active_ids,
                "historical_blocking_record_ids": historical_ids,
            },
        )

    is_middle = api._is_middle_box(current_boxes, target_box)
    mode = str(renumber_mode or "").strip().lower() or None
    if mode in {"renumber", "compact", "reindex"}:
        mode = "renumber_contiguous"

    if is_middle and mode not in {"keep_gaps", "renumber_contiguous"}:
        return None, api._failure_result(
            yaml_path=yaml_path,
            action=audit_action,
            source=source,
            tool_name=tool_name,
            error_code="renumber_mode_required",
            message="Deleting a middle box requires renumber_mode=keep_gaps or renumber_contiguous",
            actor_context=actor_context,
            tool_input=tool_input,
            before_data=data,
            details={"box": target_box, "current_boxes": current_boxes},
            extra={"choices": ["keep_gaps", "renumber_contiguous"]},
        )

    if mode is None:
        mode = "keep_gaps"
    if mode not in {"keep_gaps", "renumber_contiguous"}:
        return None, api._failure_result(
            yaml_path=yaml_path,
            action=audit_action,
            source=source,
            tool_name=tool_name,
            error_code="invalid_renumber_mode",
            message="renumber_mode must be keep_gaps or renumber_contiguous",
            actor_context=actor_context,
            tool_input=tool_input,
            before_data=data,
            details={"renumber_mode": renumber_mode},
        )

    remaining_boxes = [box_num for box_num in current_boxes if box_num != target_box]
    if not remaining_boxes:
        return None, api._failure_result(
            yaml_path=yaml_path,
            action=audit_action,
            source=source,
            tool_name=tool_name,
            error_code="min_box_count",
            message="Validation failed",
            actor_context=actor_context,
            tool_input=tool_input,
            before_data=data,
            details={"box": target_box},
        )

    box_mapping = {}
    if mode == "renumber_contiguous":
        sorted_remaining = sorted(remaining_boxes)
        box_mapping = {old_box: idx + 1 for idx, old_box in enumerate(sorted_remaining)}
        for rec in candidate_data.get("inventory", []):
            if not isinstance(rec, dict):
                continue
            rec_box = rec.get("box")
            if rec_box in box_mapping:
                rec["box"] = box_mapping[rec_box]
        new_boxes = list(range(1, len(sorted_remaining) + 1))
    else:
        new_boxes = sorted(remaining_boxes)

    preview.update(
        {
            "removed_box": target_box,
            "middle_box": is_middle,
            "renumber_mode": mode,
            "box_mapping": box_mapping,
            "box_numbers_after": new_boxes,
            "box_count_after": len(new_boxes),
        }
    )

    return {"new_boxes": new_boxes, "preview": preview}, None


def _persist_adjust_box_count(
    *,
    candidate_data,
    yaml_path,
    audit_action,
    source,
    tool_name,
    actor_context,
    tool_input,
    preview,
    auto_backup,
    request_backup_path,
    before_data,
):
    try:
        backup_path = write_yaml(
            candidate_data,
            yaml_path,
            auto_backup=auto_backup,
            backup_path=request_backup_path,
            audit_meta=api._build_audit_meta(
                action=audit_action,
                source=source,
                tool_name=tool_name,
                actor_context=actor_context,
                details=preview,
                tool_input=tool_input,
            ),
        )
    except Exception as exc:
        return None, api._failure_result(
            yaml_path=yaml_path,
            action=audit_action,
            source=source,
            tool_name=tool_name,
            error_code="write_failed",
            message=f"Adjust box count failed: {exc}",
            actor_context=actor_context,
            tool_input=tool_input,
            before_data=before_data,
            details=preview,
        )

    return backup_path, None


def _tool_adjust_box_count_impl(
    yaml_path,
    operation,
    count=1,
    box=None,
    renumber_mode=None,
    dry_run=False,
    execution_mode=None,
    actor_context=None,
    source="tool_api",
    auto_backup=True,
    request_backup_path=None,
):
    """Safely add/remove boxes without changing rows/cols/indexing."""
    audit_action = "adjust_box_count"
    tool_name = "tool_adjust_box_count"
    tool_input = {
        "operation": operation,
        "count": count,
        "box": box,
        "renumber_mode": renumber_mode,
        "dry_run": bool(dry_run),
        "execution_mode": execution_mode,
        "request_backup_path": request_backup_path,
    }

    validation = api.validate_write_tool_call(
        yaml_path=yaml_path,
        action=audit_action,
        source=source,
        tool_name=tool_name,
        tool_input=tool_input,
        payload={"operation": operation},
        dry_run=dry_run,
        execution_mode=execution_mode,
        actor_context=actor_context,
        auto_backup=auto_backup,
        request_backup_path=request_backup_path,
    )
    if not validation.get("ok"):
        return validation

    op = (validation.get("normalized") or {}).get("op")

    try:
        data = load_yaml(yaml_path)
    except Exception as exc:
        return api._failure_result(
            yaml_path=yaml_path,
            action=audit_action,
            source=source,
            tool_name=tool_name,
            error_code="load_failed",
            message=f"Failed to load YAML file: {exc}",
            actor_context=actor_context,
            tool_input=tool_input,
        )

    context, failure = _prepare_adjust_box_count_context(
        data=data,
        yaml_path=yaml_path,
        audit_action=audit_action,
        source=source,
        tool_name=tool_name,
        actor_context=actor_context,
        tool_input=tool_input,
    )
    if failure:
        return failure

    plan, failure = _plan_adjust_box_count(
        op=op,
        count=count,
        box=box,
        renumber_mode=renumber_mode,
        context=context,
        yaml_path=yaml_path,
        audit_action=audit_action,
        source=source,
        tool_name=tool_name,
        actor_context=actor_context,
        tool_input=tool_input,
    )
    if failure:
        return failure

    candidate_data = context["candidate_data"]
    candidate_layout = context["candidate_layout"]
    preview = plan["preview"]
    new_boxes = plan["new_boxes"]

    candidate_layout["box_numbers"] = list(new_boxes)
    candidate_layout["box_count"] = len(new_boxes)

    validation_error = api._validate_data_or_error(candidate_data)
    if validation_error:
        return api._failure_result(
            yaml_path=yaml_path,
            action=audit_action,
            source=source,
            tool_name=tool_name,
            error_code=validation_error.get("error_code", "integrity_validation_failed"),
            message=validation_error.get("message", "Validation failed"),
            actor_context=actor_context,
            tool_input=tool_input,
            before_data=context["data"],
            errors=validation_error.get("errors"),
            details=preview,
        )

    if dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "preview": preview,
        }

    backup_path, failure = _persist_adjust_box_count(
        candidate_data=candidate_data,
        yaml_path=yaml_path,
        audit_action=audit_action,
        source=source,
        tool_name=tool_name,
        actor_context=actor_context,
        tool_input=tool_input,
        preview=preview,
        auto_backup=auto_backup,
        request_backup_path=request_backup_path,
        before_data=context["data"],
    )
    if failure:
        return failure

    return {
        "ok": True,
        "dry_run": False,
        "preview": preview,
        "result": preview,
        "backup_path": backup_path,
    }

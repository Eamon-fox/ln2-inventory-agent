from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple


def make_error_item(item: Dict[str, object], error_code: str, message: str) -> Dict[str, object]:
    return {
        "item": item,
        "ok": False,
        "blocked": True,
        "error_code": error_code,
        "message": message,
    }


def make_ok_item(item: Dict[str, object], response: Dict[str, object]) -> Dict[str, object]:
    return {
        "item": item,
        "ok": True,
        "blocked": False,
        "response": response,
    }


def resolve_error_from_response(
    response: Dict[str, object],
    *,
    fallback_error_code: str,
    fallback_message: str,
) -> Tuple[str, str]:
    if not isinstance(response, dict):
        return fallback_error_code, fallback_message
    return (
        response.get("error_code", fallback_error_code),
        response.get("message", fallback_message),
    )


def as_int(value: object) -> Optional[int]:
    if isinstance(value, bool):
        return None
    try:
        return int(value)
    except Exception:
        return None


def normalize_batch_item_key(
    *,
    record_id: object,
    box: object,
    position: object,
    to_box: object,
    to_position: object,
) -> Tuple[Optional[int], Optional[int], Optional[int], Optional[int], Optional[int]]:
    source_box = as_int(box)
    target_box = as_int(to_box)
    if target_box is None:
        target_box = source_box
    return (
        as_int(record_id),
        source_box,
        as_int(position),
        target_box,
        as_int(to_position),
    )


def batch_item_key_from_plan_item(item: Dict[str, object]) -> Tuple[Optional[int], Optional[int], Optional[int], Optional[int], Optional[int]]:
    payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
    return normalize_batch_item_key(
        record_id=payload.get("record_id", item.get("record_id")),
        box=payload.get("box", item.get("box")),
        position=payload.get("position", item.get("position")),
        to_box=payload.get("to_box", item.get("to_box")),
        to_position=payload.get("to_position", item.get("to_position")),
    )


def batch_item_key_from_error_item(item: Dict[str, object]) -> Tuple[Optional[int], Optional[int], Optional[int], Optional[int], Optional[int]]:
    return normalize_batch_item_key(
        record_id=item.get("record_id"),
        box=item.get("box"),
        position=item.get("position"),
        to_box=item.get("to_box"),
        to_position=item.get("to_position"),
    )


def extract_record_id_from_text(text: str) -> Optional[int]:
    patterns = [
        r"\bID\s*#?\s*(\d+)\b",
        r"\brecord\s*#?\s*(\d+)\b",
        r"\bid\s*=\s*(\d+)\b",
        r"\bmove\s+(\d+)\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, str(text or ""), flags=re.IGNORECASE)
        if not match:
            continue
        rid = as_int(match.group(1))
        if rid is not None:
            return rid
    return None


def extract_batch_error_maps(
    response: Dict[str, object],
) -> Tuple[
    Dict[Tuple[Optional[int], Optional[int], Optional[int], Optional[int], Optional[int]], Tuple[str, str]],
    Dict[int, Tuple[str, str]],
]:
    key_errors: Dict[Tuple[Optional[int], Optional[int], Optional[int], Optional[int], Optional[int]], Tuple[str, str]] = {}
    rid_errors: Dict[int, Tuple[str, str]] = {}
    if not isinstance(response, dict):
        return key_errors, rid_errors

    default_code = str(response.get("error_code") or "").strip()
    blocked_items = response.get("blocked_items")
    if isinstance(blocked_items, list):
        for blocked in blocked_items:
            if not isinstance(blocked, dict):
                continue
            message = str(blocked.get("message") or "").strip()
            if not message:
                continue
            error_code = str(blocked.get("error_code") or default_code or "validation_failed")
            key = batch_item_key_from_error_item(blocked)
            if key not in key_errors:
                key_errors[key] = (error_code, message)
            rid = key[0]
            if rid is not None and rid not in rid_errors:
                rid_errors[rid] = (error_code, message)

    errors = response.get("errors")
    if isinstance(errors, list):
        for raw_error in errors:
            message = str(raw_error or "").strip()
            if not message:
                continue
            rid = extract_record_id_from_text(message)
            if rid is None or rid in rid_errors:
                continue
            rid_errors[rid] = (default_code or "validation_failed", message)

    response_message = str(response.get("message") or "").strip()
    if response_message:
        for part in re.split(r";\s*", response_message):
            message = str(part or "").strip()
            if not message:
                continue
            rid = extract_record_id_from_text(message)
            if rid is None or rid in rid_errors:
                continue
            rid_errors[rid] = (default_code or "validation_failed", message)

    return key_errors, rid_errors


def make_error_item_from_response(
    item: Dict[str, object],
    response: Dict[str, object],
    *,
    fallback_error_code: str,
    fallback_message: str,
) -> Dict[str, object]:
    error_code, message = resolve_error_from_response(
        response,
        fallback_error_code=fallback_error_code,
        fallback_message=fallback_message,
    )
    return make_error_item(item, error_code, message)


def fanout_batch_response(
    items: List[Dict[str, object]],
    response: Dict[str, object],
    *,
    fallback_error_code: str,
    fallback_message: str,
) -> Tuple[bool, List[Dict[str, object]]]:
    reports: List[Dict[str, object]] = []
    if isinstance(response, dict) and response.get("ok"):
        for item in items:
            reports.append(make_ok_item(item, response))
        return True, reports

    key_errors, rid_errors = extract_batch_error_maps(response)
    for item in items:
        key = batch_item_key_from_plan_item(item)
        mapped = key_errors.get(key)
        if mapped is None:
            record_id = key[0]
            if record_id is not None:
                mapped = rid_errors.get(record_id)
        if mapped is not None:
            mapped_error_code, mapped_message = mapped
            reports.append(
                make_error_item(
                    item,
                    mapped_error_code or fallback_error_code,
                    mapped_message or fallback_message,
                )
            )
            continue
        reports.append(
            make_error_item_from_response(
                item,
                response,
                fallback_error_code=fallback_error_code,
                fallback_message=fallback_message,
            )
        )
    return False, reports


def append_item_report(
    reports: List[Dict[str, object]],
    *,
    item: Dict[str, object],
    response: Dict[str, object],
    fallback_error_code: str,
    fallback_message: str,
) -> bool:
    if response.get("ok"):
        reports.append(make_ok_item(item, response))
        return True
    reports.append(
        make_error_item_from_response(
            item,
            response,
            fallback_error_code=fallback_error_code,
            fallback_message=fallback_message,
        )
    )
    return False


def update_last_backup(
    last_backup: Optional[str],
    response: Dict[str, object],
    *,
    include_snapshot_before_rollback: bool = False,
) -> Optional[str]:
    if not isinstance(response, dict):
        return last_backup
    backup_path = response.get("backup_path")
    if backup_path:
        return backup_path
    if include_snapshot_before_rollback:
        snapshot = (response.get("result") or {}).get("snapshot_before_rollback")
        if snapshot:
            return snapshot
    return last_backup


def consume_batch_successes(
    remaining: List[Dict[str, object]],
    batch_reports: List[Dict[str, object]],
    last_backup: Optional[str],
) -> Optional[str]:
    for report in batch_reports:
        item = report.get("item")
        if not report.get("ok") or item not in remaining:
            continue
        remaining.remove(item)
        last_backup = update_last_backup(last_backup, report.get("response") or {})
    return last_backup


def first_success_backup_path(reports: List[Dict[str, object]]) -> Optional[str]:
    for report in reports:
        if not report.get("ok"):
            continue
        response = report.get("response")
        if not isinstance(response, dict):
            continue
        backup_path = response.get("backup_path")
        if backup_path:
            return backup_path
    return None


def append_and_consume_item_report(
    reports: List[Dict[str, object]],
    remaining: List[Dict[str, object]],
    *,
    item: Dict[str, object],
    response: Dict[str, object],
    fallback_error_code: str,
    fallback_message: str,
    last_backup: Optional[str],
    include_snapshot_before_rollback: bool = False,
) -> Optional[str]:
    if not append_item_report(
        reports,
        item=item,
        response=response,
        fallback_error_code=fallback_error_code,
        fallback_message=fallback_message,
    ):
        return last_backup
    if item in remaining:
        remaining.remove(item)
    return update_last_backup(
        last_backup,
        response,
        include_snapshot_before_rollback=include_snapshot_before_rollback,
    )


def batch_ok_reports(
    items: List[Dict[str, object]],
    response: Dict[str, object],
) -> Tuple[bool, List[Dict[str, object]]]:
    return True, [make_ok_item(item, response) for item in items]


_make_error_item = make_error_item
_make_ok_item = make_ok_item
_resolve_error_from_response = resolve_error_from_response
_as_int = as_int
_normalize_batch_item_key = normalize_batch_item_key
_batch_item_key_from_plan_item = batch_item_key_from_plan_item
_batch_item_key_from_error_item = batch_item_key_from_error_item
_extract_record_id_from_text = extract_record_id_from_text
_extract_batch_error_maps = extract_batch_error_maps
_make_error_item_from_response = make_error_item_from_response
_fanout_batch_response = fanout_batch_response
_append_item_report = append_item_report
_update_last_backup = update_last_backup
_consume_batch_successes = consume_batch_successes
_first_success_backup_path = first_success_backup_path
_append_and_consume_item_report = append_and_consume_item_report
_batch_ok_reports = batch_ok_reports

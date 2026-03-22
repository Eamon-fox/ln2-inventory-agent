"""Shared normalization helpers for box-layout mutation requests."""

from __future__ import annotations

from typing import Any, Dict, Iterable, Optional, Tuple

from .position_fmt import is_valid_box_layout_indexing, normalize_box_layout_indexing


BOX_TAG_MAX_LENGTH = 80

_MANAGE_BOXES_OPERATION_ALIASES = {
    "add": "add",
    "add_boxes": "add",
    "increase": "add",
    "remove": "remove",
    "remove_box": "remove",
    "delete": "remove",
}
_MANAGE_BOXES_RENUMBER_MODE_ALIASES = {
    "keep_gaps": "keep_gaps",
    "keep": "keep_gaps",
    "gaps": "keep_gaps",
    "renumber_contiguous": "renumber_contiguous",
    "renumber": "renumber_contiguous",
    "compact": "renumber_contiguous",
    "reindex": "renumber_contiguous",
}


def normalize_manage_boxes_operation(operation: Any) -> Optional[str]:
    if operation in (None, ""):
        return None
    op_text = str(operation).strip().lower()
    return _MANAGE_BOXES_OPERATION_ALIASES.get(op_text)


def normalize_manage_boxes_renumber_mode(mode_value: Any) -> Optional[str]:
    if mode_value in (None, ""):
        return None
    mode_text = str(mode_value).strip().lower()
    return _MANAGE_BOXES_RENUMBER_MODE_ALIASES.get(mode_text)


def normalize_positive_box_number(raw_box: Any) -> Tuple[Optional[int], Optional[Dict[str, Any]]]:
    try:
        box_num = int(raw_box)
    except Exception:
        return None, {
            "error_code": "invalid_box",
            "message": "box must be an integer",
            "details": {"box": raw_box},
        }
    if box_num <= 0:
        return None, {
            "error_code": "invalid_box",
            "message": "box must be >= 1",
            "details": {"box": box_num},
        }
    return box_num, None


def normalize_manage_boxes_count(raw_count: Any) -> Tuple[Optional[int], Optional[Dict[str, Any]]]:
    try:
        count = int(raw_count)
    except Exception:
        return None, {
            "error_code": "invalid_count",
            "message": "count must be a positive integer",
            "details": {"count": raw_count},
        }
    if count <= 0:
        return None, {
            "error_code": "invalid_count",
            "message": "count must be a positive integer",
            "details": {"count": count},
        }
    return count, None


def normalize_manage_boxes_request(payload: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], Dict[str, Any]]:
    payload_dict = payload if isinstance(payload, dict) else {}
    raw_operation = payload_dict.get("operation")
    if raw_operation in (None, ""):
        raw_operation = payload_dict.get("action")
    op = normalize_manage_boxes_operation(raw_operation)
    if not op:
        return {
            "error_code": "invalid_operation",
            "message": "operation must be add/remove",
            "details": {"operation": raw_operation},
        }, {}

    raw_mode = payload_dict.get("renumber_mode")
    normalized_mode = normalize_manage_boxes_renumber_mode(raw_mode)
    if raw_mode not in (None, "") and normalized_mode is None:
        return {
            "error_code": "invalid_renumber_mode",
            "message": "renumber_mode must be keep_gaps or renumber_contiguous",
            "details": {"renumber_mode": raw_mode},
        }, {}

    normalized = {
        "op": op,
        "operation": op,
        "renumber_mode": normalized_mode,
    }

    if op == "add":
        count, issue = normalize_manage_boxes_count(payload_dict.get("count"))
        if issue:
            return issue, {}
        normalized["count"] = count
        return None, normalized

    box_num, issue = normalize_positive_box_number(payload_dict.get("box"))
    if issue:
        return issue, {}
    normalized["box"] = box_num
    return None, normalized


def normalize_box_tag_value(raw_tag: Any) -> Tuple[Optional[str], Optional[str]]:
    text = "" if raw_tag is None else str(raw_tag)
    if "\n" in text or "\r" in text:
        return None, "Box tag must be a single line"
    normalized = text.strip()
    if len(normalized) > BOX_TAG_MAX_LENGTH:
        return None, f"Box tag must be <= {BOX_TAG_MAX_LENGTH} characters"
    return normalized, None


def normalize_box_tag_request(payload: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], Dict[str, Any]]:
    payload_dict = payload if isinstance(payload, dict) else {}
    box_num, issue = normalize_positive_box_number(payload_dict.get("box"))
    if issue:
        return issue, {}

    normalized_tag, tag_error = normalize_box_tag_value(payload_dict.get("tag", ""))
    if tag_error:
        return {
            "error_code": "invalid_tag",
            "message": tag_error,
            "details": {"max_length": BOX_TAG_MAX_LENGTH},
        }, {}

    return None, {
        "box": box_num,
        "tag": normalized_tag,
    }


def normalize_box_tags(raw_tags: Any, allowed_boxes: Iterable[Any]) -> Dict[str, str]:
    if not isinstance(raw_tags, dict):
        return {}

    allowed = set()
    for raw_box in list(allowed_boxes or []):
        try:
            allowed.add(int(raw_box))
        except Exception:
            continue

    normalized: Dict[str, str] = {}
    for raw_box, raw_tag in raw_tags.items():
        try:
            box_num = int(raw_box)
        except Exception:
            continue
        if box_num not in allowed:
            continue
        tag_text, _err = normalize_box_tag_value(raw_tag)
        if tag_text:
            normalized[str(box_num)] = tag_text
    return normalized


def normalize_box_layout_indexing_value(raw_value: Any) -> Tuple[Optional[str], Optional[str]]:
    text = str(raw_value or "").strip().lower()
    if not text:
        return None, "indexing is required"
    if not is_valid_box_layout_indexing(text):
        return None, "indexing must be one of: numeric, alphanumeric"
    return normalize_box_layout_indexing(text), None


def normalize_box_layout_indexing_request(payload: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], Dict[str, Any]]:
    payload_dict = payload if isinstance(payload, dict) else {}
    indexing, error = normalize_box_layout_indexing_value(payload_dict.get("indexing"))
    if error:
        issue = {
            "error_code": "invalid_indexing",
            "message": error,
        }
        if payload_dict.get("indexing") not in (None, ""):
            issue["details"] = {"indexing": payload_dict.get("indexing")}
        return issue, {}
    return None, {"indexing": indexing}

"""Application-layer helpers for box-layout mutation flows."""

from __future__ import annotations

import os
from typing import Callable, Optional

from lib.box_layout_requests import normalize_manage_boxes_operation
from lib.position_fmt import get_box_numbers
from lib.yaml_ops import load_yaml


class BoxLayoutMutationUseCase:
    """Prepare/preflight box-layout mutations below GUI window chokepoints."""

    def __init__(
        self,
        *,
        bridge,
        current_yaml_path_getter: Callable[[], str],
        load_yaml_fn: Callable[[str], dict] = load_yaml,
        get_box_numbers_fn: Callable[[dict], list] = get_box_numbers,
        normalize_operation_fn: Callable[[object], Optional[str]] = normalize_manage_boxes_operation,
    ):
        self._bridge = bridge
        self._current_yaml_path = current_yaml_path_getter
        self._load_yaml = load_yaml_fn
        self._get_box_numbers = get_box_numbers_fn
        self._normalize_operation = normalize_operation_fn

    def prepare_request(self, request, *, yaml_path_override=None):
        if not isinstance(request, dict):
            return self._error_response("invalid_tool_input", "Invalid manage boxes request")

        yaml_path = str(yaml_path_override or self._current_yaml_path() or "")
        if not yaml_path or not os.path.isfile(yaml_path):
            return self._error_response("load_failed", f"Inventory file not found: {yaml_path}")

        raw_op = str(request.get("operation") or request.get("action") or "").strip().lower()
        if raw_op in {"set_tag", "set_indexing"}:
            op = raw_op
        else:
            op = self._normalize_operation(raw_op)
        if op not in {"add", "remove", "set_tag", "set_indexing"}:
            return self._error_response(
                "invalid_operation",
                "operation must be add/remove/set_tag/set_indexing",
            )

        prepared = {
            "yaml_path": yaml_path,
            "op": op,
            "payload": {"operation": op},
        }

        if op == "add":
            prepared["payload"]["count"] = request.get("count")
            return prepared

        if op == "set_tag":
            raw_tag = request.get("tag", "")
            prepared["payload"]["box"] = request.get("box")
            prepared["payload"]["tag"] = "" if raw_tag is None else str(raw_tag)
            return prepared

        if op == "set_indexing":
            prepared["payload"]["indexing"] = request.get("indexing")
            return prepared

        prepared["payload"]["box"] = request.get("box")
        raw_mode = request.get("renumber_mode")
        if raw_mode not in (None, ""):
            prepared["payload"]["renumber_mode"] = raw_mode
        return prepared

    def preflight(self, prepared):
        if not isinstance(prepared, dict):
            return self._error_response("invalid_tool_input", "Invalid manage boxes request")
        bridge = self._bridge
        if bridge is None:
            return self._error_response("bridge_unavailable", "GUI bridge is unavailable")

        yaml_path = prepared["yaml_path"]
        op = prepared["op"]
        payload = dict(prepared.get("payload") or {})

        if op == "set_tag":
            return bridge.set_box_tag(
                yaml_path=yaml_path,
                box=payload.get("box"),
                tag=payload.get("tag", ""),
                dry_run=True,
            )
        if op == "set_indexing":
            return bridge.set_box_layout_indexing(
                yaml_path=yaml_path,
                indexing=payload.get("indexing"),
                dry_run=True,
            )
        return bridge.manage_boxes(
            yaml_path=yaml_path,
            dry_run=True,
            **payload,
        )

    def load_box_numbers_for_presentation(self, yaml_path):
        try:
            data = self._load_yaml(yaml_path)
            layout = (data or {}).get("meta", {}).get("box_layout", {})
            return list(self._get_box_numbers(layout))
        except Exception as exc:
            return self._error_response("load_failed", str(exc))

    @staticmethod
    def _error_response(error_code, message):
        return {
            "ok": False,
            "error_code": str(error_code or "unknown_error"),
            "message": str(message or ""),
        }

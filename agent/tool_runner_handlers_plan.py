"""Plan-store dispatch handlers for AgentToolRunner."""


def _extract_staged_item_positions(item):
    """Extract one-or-many source positions from a staged plan item."""
    if not isinstance(item, dict):
        return []

    candidates = []
    top_positions = item.get("positions")
    if isinstance(top_positions, (list, tuple, set)):
        candidates.append(top_positions)

    payload = item.get("payload")
    payload_positions = payload.get("positions") if isinstance(payload, dict) else None
    if isinstance(payload_positions, (list, tuple, set)):
        candidates.append(payload_positions)

    for raw_values in candidates:
        values = [value for value in list(raw_values) if value not in (None, "")]
        if values:
            return values

    fallback_pos = item.get("position")
    if fallback_pos not in (None, ""):
        return [fallback_pos]
    return []


def _run_staged_plan(self, payload, _trace_id=None):
    tool_name = "staged_plan"

    def _list_items():
        if not self._plan_store:
            return {
                "ok": True,
                "result": {"items": [], "count": 0},
                "message": self._msg(
                    "manageStaged.noPlanStoreAvailableList",
                    "No plan store available.",
                ),
            }

        items = self._plan_store.list_items()
        summary = []
        for index, item in enumerate(items):
            positions = _extract_staged_item_positions(item)
            entry = {
                "index": index,
                "action": item.get("action"),
                "record_id": item.get("record_id"),
                "box": item.get("box"),
                "positions": positions,
                "label": item.get("label"),
                "source": item.get("source"),
            }
            if item.get("to_position") is not None:
                entry["to_position"] = item["to_position"]
            if item.get("to_box") is not None:
                entry["to_box"] = item["to_box"]
            summary.append(entry)
        return {"ok": True, "result": {"items": summary, "count": len(summary)}}

    def _remove_item():
        idx = self._required_int(payload, "index")

        if not self._plan_store:
            return {
                "ok": False,
                "error_code": "no_plan_store",
                "message": self._msg(
                    "manageStaged.planStoreNotAvailable",
                    "Plan store not available.",
                ),
            }

        removed = self._plan_store.remove_by_index(idx)
        if removed is None:
            max_idx = self._plan_store.count() - 1
            return self._with_hint(
                tool_name,
                {
                    "ok": False,
                    "error_code": "invalid_index",
                    "message": self._msg(
                        "manageStaged.indexOutOfRange",
                        "Index {idx} out of range (0..{max_idx}).",
                        idx=idx,
                        max_idx=max_idx,
                    ),
                },
            )

        return {
            "ok": True,
            "message": self._msg(
                "manageStaged.removedByIndex",
                "Removed item at index {idx}: {desc}",
                idx=idx,
                desc=self._item_desc(removed),
            ),
            "result": {"removed": 1},
        }

    def _clear_items():
        if not self._plan_store:
            return {
                "ok": False,
                "error_code": "no_plan_store",
                "message": self._msg(
                    "manageStaged.planStoreNotAvailable",
                    "Plan store not available.",
                ),
            }

        cleared = self._plan_store.clear()
        return {
            "ok": True,
            "message": self._msg(
                "manageStaged.clearedCount",
                "Cleared {count} staged item(s).",
                count=len(cleared),
            ),
            "result": {"cleared_count": len(cleared)},
        }

    def _call_staged_plan():
        action = str(payload.get("action") or "").strip().lower()
        if action == "list":
            return _list_items()
        if action == "remove":
            return _remove_item()
        if action == "clear":
            return _clear_items()
        raise ValueError(
            self._msg(
                "validation.mustBeOneOf",
                "{label} must be one of: {values}",
                label="action",
                values="list, remove, clear",
            )
        )

    return self._safe_call(tool_name, _call_staged_plan, include_expected_schema=True)

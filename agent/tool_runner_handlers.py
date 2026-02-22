"""Dispatch handlers for AgentToolRunner."""

from lib.tool_api import (
    tool_add_entry,
    tool_adjust_box_count,
    tool_batch_move,
    tool_batch_takeout,
    tool_collect_timeline,
    tool_edit_entry,
    tool_generate_stats,
    tool_get_raw_entries,
    tool_list_empty_positions,
    tool_query_takeout_events,
    tool_recent_frozen,
    tool_recommend_positions,
    tool_record_move,
    tool_record_takeout,
    tool_rollback,
    tool_search_records,
)


def _run_manage_boxes_add(self, payload, trace_id=None):
    tool_name = "manage_boxes_add"

    def _call_manage_boxes_add():
        count = self._required_int(payload, "count")
        request = {
            "operation": "add",
            "count": count,
            "box": None,
            "renumber_mode": None,
        }

        dry_run = self._as_bool(payload.get("dry_run", False), default=False)
        if dry_run:
            return tool_adjust_box_count(
                yaml_path=self._yaml_path,
                operation="add",
                count=count,
                dry_run=True,
                execution_mode="preflight",
                actor_context=self._actor_context(trace_id=trace_id),
                source="agent.react",
            )

        return {
            "ok": True,
            "waiting_for_user_confirmation": True,
            "request": request,
            "message": self._msg(
                "manageBoxes.awaitingUserConfirmation",
                "Awaiting user confirmation in GUI.",
            ),
        }

    return self._safe_call(tool_name, _call_manage_boxes_add, include_expected=True)


def _run_manage_boxes_remove(self, payload, trace_id=None):
    tool_name = "manage_boxes_remove"

    def _call_manage_boxes_remove():
        box = self._required_int(payload, "box")
        renumber_mode = payload.get("renumber_mode")
        request = {
            "operation": "remove",
            "count": None,
            "box": box,
            "renumber_mode": renumber_mode,
        }

        dry_run = self._as_bool(payload.get("dry_run", False), default=False)
        if dry_run:
            call_kwargs = {
                "yaml_path": self._yaml_path,
                "operation": "remove",
                "box": box,
                "dry_run": True,
                "execution_mode": "preflight",
                "actor_context": self._actor_context(trace_id=trace_id),
                "source": "agent.react",
            }
            if renumber_mode not in (None, ""):
                call_kwargs["renumber_mode"] = renumber_mode
            return tool_adjust_box_count(**call_kwargs)

        return {
            "ok": True,
            "waiting_for_user_confirmation": True,
            "request": request,
            "message": self._msg(
                "manageBoxes.awaitingUserConfirmation",
                "Awaiting user confirmation in GUI.",
            ),
        }

    return self._safe_call(tool_name, _call_manage_boxes_remove, include_expected=True)


def _run_list_empty_positions(self, payload, _trace_id=None):
    tool_name = "list_empty_positions"
    return self._safe_call(
        tool_name,
        lambda: tool_list_empty_positions(
            yaml_path=self._yaml_path,
            box=self._optional_int(payload, "box"),
        ),
    )


def _run_search_records(self, payload, _trace_id=None):
    tool_name = "search_records"
    mode = self._normalize_search_mode(payload.get("mode"))
    layout = self._load_layout()

    position = None
    if payload.get("position") not in (None, ""):
        position = self._parse_position(
            payload.get("position"),
            layout=layout,
            field_name="position",
        )

    return self._safe_call(
        tool_name,
        lambda: tool_search_records(
            yaml_path=self._yaml_path,
            query=payload.get("query"),
            mode=mode,
            max_results=self._optional_int(payload, "max_results"),
            case_sensitive=self._as_bool(payload.get("case_sensitive", False), default=False),
            box=self._optional_int(payload, "box"),
            position=position,
            record_id=self._optional_int(payload, "record_id"),
            active_only=(payload.get("active_only") if "active_only" in payload else None),
        ),
    )


def _run_recent_frozen(self, payload, _trace_id=None):
    tool_name = "recent_frozen"

    def _call_recent_frozen():
        basis = str(payload.get("basis") or "").strip().lower()
        value = self._required_int(payload, "value")
        if basis == "days":
            return tool_recent_frozen(yaml_path=self._yaml_path, days=value, count=None)
        if basis == "count":
            return tool_recent_frozen(yaml_path=self._yaml_path, days=None, count=value)
        raise ValueError(
            self._msg(
                "validation.mustBeOneOf",
                "{label} must be one of: {values}",
                label="basis",
                values="days, count",
            )
        )

    return self._safe_call(tool_name, _call_recent_frozen, include_expected=True)


def _run_query_takeout_events(self, payload, _trace_id=None):
    tool_name = "query_takeout_events"
    days_value = self._optional_int(payload, "days")
    if days_value is not None:
        days_value = int(days_value)
    max_records_value = self._optional_int(payload, "max_records", default=0)
    max_records_value = 0 if max_records_value is None else int(max_records_value)

    return self._safe_call(
        tool_name,
        lambda: tool_query_takeout_events(
            yaml_path=self._yaml_path,
            date=payload.get("date"),
            days=days_value,
            start_date=payload.get("start_date"),
            end_date=payload.get("end_date"),
            action=payload.get("action"),
            max_records=max_records_value,
        ),
    )


def _run_query_takeout_summary(self, payload, _trace_id=None):
    tool_name = "query_takeout_summary"

    def _call_query_takeout_summary():
        selector = str(payload.get("range") or "").strip().lower()
        if selector == "all":
            return tool_collect_timeline(
                yaml_path=self._yaml_path,
                days=30,
                all_history=True,
            )

        days_map = {"7d": 7, "30d": 30, "90d": 90}
        days = days_map.get(selector)
        if days is None:
            raise ValueError(
                self._msg(
                    "validation.mustBeOneOf",
                    "{label} must be one of: {values}",
                    label="range",
                    values="7d, 30d, 90d, all",
                )
            )

        return tool_collect_timeline(
            yaml_path=self._yaml_path,
            days=days,
            all_history=False,
        )

    return self._safe_call(tool_name, _call_query_takeout_summary, include_expected=True)


def _run_recommend_positions(self, payload, _trace_id=None):
    tool_name = "recommend_positions"
    return self._safe_call(
        tool_name,
        lambda: tool_recommend_positions(
            yaml_path=self._yaml_path,
            count=self._optional_int(payload, "count", default=2),
            box_preference=self._optional_int(payload, "box_preference"),
            strategy=payload.get("strategy", "consecutive"),
        ),
    )


def _run_generate_stats(self, _payload, _trace_id=None):
    return self._safe_call(
        "generate_stats",
        lambda: tool_generate_stats(yaml_path=self._yaml_path),
    )


def _run_get_raw_entries(self, payload, _trace_id=None):
    tool_name = "get_raw_entries"

    def _call_get_raw_entries():
        ids = list(payload.get("ids") or [])
        return tool_get_raw_entries(
            yaml_path=self._yaml_path,
            ids=ids,
        )

    return self._safe_call(tool_name, _call_get_raw_entries, include_expected=True)


def _run_edit_entry(self, payload, trace_id=None):
    tool_name = "edit_entry"

    def _call_edit_entry():
        rid = self._required_int(payload, "record_id")
        fields = payload.get("fields")
        if not fields or not isinstance(fields, dict):
            raise ValueError(
                self._msg(
                    "errors.fieldsMustBeNonEmptyObject",
                    "fields must be a non-empty object",
                )
            )
        return tool_edit_entry(
            yaml_path=self._yaml_path,
            record_id=rid,
            fields=fields,
            actor_context=self._actor_context(trace_id=trace_id),
            source="agent.react",
        )

    return self._safe_call(tool_name, _call_edit_entry, include_expected=True)


def _run_add_entry(self, payload, trace_id=None):
    tool_name = "add_entry"

    def _call_add_entry():
        layout = self._load_layout()
        box_val = self._required_int(payload, "box")
        frozen_at = payload.get("frozen_at")
        positions = self._normalize_positions(payload.get("positions"), layout=layout)
        fields = dict(payload.get("fields") or {})

        return tool_add_entry(
            yaml_path=self._yaml_path,
            box=box_val,
            positions=positions,
            frozen_at=frozen_at,
            fields=fields,
            dry_run=self._as_bool(payload.get("dry_run", False), default=False),
            actor_context=self._actor_context(trace_id=trace_id),
            source="agent.react",
        )

    return self._safe_call(tool_name, _call_add_entry, include_expected=True)


def _parse_batch_flat_entries(self, raw_entries, *, layout, include_target):
    entries = []
    for idx, entry in enumerate(raw_entries):
        if not isinstance(entry, dict):
            raise ValueError(
                self._msg(
                    "validation.mustBeObject",
                    "{label} must be an object",
                    label=f"entries[{idx}]",
                )
            )

        parsed = {
            "record_id": self._required_int(entry, "record_id"),
            "from": {
                "box": self._required_int(entry, "from_box"),
                "position": self._parse_position(
                    entry.get("from_position"),
                    layout=layout,
                    field_name=f"entries[{idx}].from_position",
                ),
            },
        }
        if include_target:
            parsed["to"] = {
                "box": self._required_int(entry, "to_box"),
                "position": self._parse_position(
                    entry.get("to_position"),
                    layout=layout,
                    field_name=f"entries[{idx}].to_position",
                ),
            }
        entries.append(parsed)
    return entries


def _call_record_flat_tool(self, payload, trace_id, *, tool_fn, include_target):
    layout = self._load_layout()
    call_kwargs = {
        "yaml_path": self._yaml_path,
        "record_id": self._required_int(payload, "record_id"),
        "from_slot": {
            "box": self._required_int(payload, "from_box"),
            "position": self._parse_position(
                payload.get("from_position"),
                layout=layout,
                field_name="from_position",
            ),
        },
        "date_str": payload.get("date"),
        "dry_run": self._as_bool(payload.get("dry_run", False), default=False),
        "actor_context": self._actor_context(trace_id=trace_id),
        "source": "agent.react",
    }
    if include_target:
        call_kwargs["to_slot"] = {
            "box": self._required_int(payload, "to_box"),
            "position": self._parse_position(
                payload.get("to_position"),
                layout=layout,
                field_name="to_position",
            ),
        }
    return tool_fn(**call_kwargs)


def _call_batch_flat_tool(self, payload, trace_id, *, tool_fn, include_target):
    layout = self._load_layout()
    entries = _parse_batch_flat_entries(
        self,
        payload.get("entries") or [],
        layout=layout,
        include_target=include_target,
    )
    return tool_fn(
        yaml_path=self._yaml_path,
        entries=entries,
        date_str=payload.get("date"),
        dry_run=self._as_bool(payload.get("dry_run", False), default=False),
        actor_context=self._actor_context(trace_id=trace_id),
        source="agent.react",
    )


def _run_record_takeout(self, payload, trace_id=None):
    tool_name = "record_takeout"

    def _call_record_takeout():
        return _call_record_flat_tool(
            self,
            payload,
            trace_id,
            tool_fn=tool_record_takeout,
            include_target=False,
        )

    return self._safe_call(tool_name, _call_record_takeout, include_expected=True)


def _run_record_move(self, payload, trace_id=None):
    tool_name = "record_move"

    def _call_record_move():
        return _call_record_flat_tool(
            self,
            payload,
            trace_id,
            tool_fn=tool_record_move,
            include_target=True,
        )

    return self._safe_call(tool_name, _call_record_move, include_expected=True)


def _run_batch_takeout(self, payload, trace_id=None):
    tool_name = "batch_takeout"

    def _call_batch_takeout():
        return _call_batch_flat_tool(
            self,
            payload,
            trace_id,
            tool_fn=tool_batch_takeout,
            include_target=False,
        )

    return self._safe_call(tool_name, _call_batch_takeout, include_expected=True)


def _run_batch_move(self, payload, trace_id=None):
    tool_name = "batch_move"

    def _call_batch_move():
        return _call_batch_flat_tool(
            self,
            payload,
            trace_id,
            tool_fn=tool_batch_move,
            include_target=True,
        )

    return self._safe_call(tool_name, _call_batch_move, include_expected=True)


def _run_rollback(self, payload, trace_id=None):
    tool_name = "rollback"
    return self._safe_call(
        tool_name,
        lambda: tool_rollback(
            yaml_path=self._yaml_path,
            backup_path=payload.get("backup_path"),
            actor_context=self._actor_context(trace_id=trace_id),
            source="agent.react",
        ),
    )


def _run_staged_list(self, _payload, _trace_id=None):
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
        entry = {
            "index": index,
            "action": item.get("action"),
            "record_id": item.get("record_id"),
            "box": item.get("box"),
            "position": item.get("position"),
            "label": item.get("label"),
            "source": item.get("source"),
        }
        if item.get("to_position") is not None:
            entry["to_position"] = item["to_position"]
        if item.get("to_box") is not None:
            entry["to_box"] = item["to_box"]
        summary.append(entry)
    return {"ok": True, "result": {"items": summary, "count": len(summary)}}


def _run_staged_remove(self, payload, _trace_id=None):
    tool_name = "staged_remove"

    if not self._plan_store:
        return {
            "ok": False,
            "error_code": "no_plan_store",
            "message": self._msg(
                "manageStaged.planStoreNotAvailable",
                "Plan store not available.",
            ),
        }

    idx = self._required_int(payload, "index")
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


def _run_staged_clear(self, _payload, _trace_id=None):
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

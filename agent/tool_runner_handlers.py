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

def _run_manage_boxes(self, payload, trace_id=None):
    tool_name = "manage_boxes"

    def _call_manage_boxes():
        op = str(payload.get("operation") or "").strip().lower()
        if op not in {"add", "remove"}:
            raise ValueError(
                self._msg(
                    "errors.operationMustBeAddOrRemove",
                    "operation must be add or remove",
                )
            )

        normalized_mode = payload.get("renumber_mode")
        add_count = None
        target_box = None

        if op == "add":
            if "count" not in payload:
                raise ValueError(
                    self._msg("input.countRequiredWhenAdd", "count is required when operation=add")
                )
            if "box" in payload:
                raise ValueError(
                    self._msg("input.boxNotAllowedWhenAdd", "box is not allowed when operation=add")
                )
            if normalized_mode not in (None, ""):
                raise ValueError(
                    self._msg(
                        "input.renumberOnlyForRemove",
                        "renumber_mode is only valid when operation=remove",
                    )
                )
            add_count = self._required_int(payload, "count")
        else:
            if "box" not in payload:
                raise ValueError(
                    self._msg("input.boxRequiredWhenRemove", "box is required when operation=remove")
                )
            if "count" in payload:
                raise ValueError(
                    self._msg(
                        "input.countNotAllowedWhenRemove",
                        "count is not allowed when operation=remove",
                    )
                )
            target_box = self._required_int(payload, "box")

        request = {
            "operation": op,
            "renumber_mode": normalized_mode,
            "count": add_count if op == "add" else None,
            "box": target_box if op == "remove" else None,
        }

        dry_run = self._as_bool(payload.get("dry_run", False), default=False)
        if dry_run:
            call_kwargs = {
                "yaml_path": self._yaml_path,
                "operation": op,
                "dry_run": True,
                "execution_mode": "preflight",
                "actor_context": self._actor_context(trace_id=trace_id),
                "source": "agent.react",
            }
            if normalized_mode is not None:
                call_kwargs["renumber_mode"] = normalized_mode
            if op == "add":
                call_kwargs["count"] = add_count
            else:
                call_kwargs["box"] = target_box
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

    return self._safe_call(tool_name, _call_manage_boxes, include_expected=True)

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
    recent_days = self._optional_int(payload, "recent_days")
    recent_count = self._optional_int(payload, "recent_count")
    if recent_days is not None or recent_count is not None:
        return self._safe_call(
            tool_name,
            lambda: tool_recent_frozen(
                yaml_path=self._yaml_path,
                days=recent_days,
                count=recent_count,
            ),
        )

    mode = self._normalize_search_mode(payload.get("mode"))
    return self._safe_call(
        tool_name,
        lambda: tool_search_records(
            yaml_path=self._yaml_path,
            query=payload.get("query"),
            mode=mode,
            max_results=self._optional_int(payload, "max_results"),
            case_sensitive=self._as_bool(payload.get("case_sensitive", False), default=False),
            box=payload.get("box"),
            position=payload.get("position"),
            record_id=payload.get("record_id"),
            active_only=(payload.get("active_only") if "active_only" in payload else None),
        ),
    )

def _run_query_takeout_events(self, payload, _trace_id=None):
    tool_name = "query_takeout_events"
    view = payload.get("view", "events")
    if view == "summary":
        timeline_days = self._optional_int(payload, "days", default=30)
        timeline_days = 30 if timeline_days is None else int(timeline_days)
        return self._safe_call(
            tool_name,
            lambda: tool_collect_timeline(
                yaml_path=self._yaml_path,
                days=timeline_days,
                all_history=self._as_bool(payload.get("all_history", False), default=False),
            ),
        )

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


def _parse_slot_payload(self, slot_payload, *, layout, field_name):
    if not isinstance(slot_payload, dict):
        raise ValueError(
            self._msg(
                "validation.mustBeObject",
                "{label} must be an object",
                label=field_name,
            )
        )
    box = self._required_int(slot_payload, "box")
    position = self._parse_position(
        slot_payload.get("position"),
        layout=layout,
        field_name=f"{field_name}.position",
    )
    return {"box": box, "position": position}


def _parse_batch_slot_entries(self, raw_entries, *, layout, include_target):
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
        parsed_entry = {
            "record_id": self._required_int(entry, "record_id"),
            "from": _parse_slot_payload(
                self,
                entry.get("from"),
                layout=layout,
                field_name=f"entries[{idx}].from",
            ),
        }
        if include_target:
            parsed_entry["to"] = _parse_slot_payload(
                self,
                entry.get("to"),
                layout=layout,
                field_name=f"entries[{idx}].to",
            )
        entries.append(parsed_entry)
    return entries


def _call_record_slot_tool(self, payload, trace_id, *, tool_fn, include_target):
    layout = self._load_layout()
    call_kwargs = {
        "yaml_path": self._yaml_path,
        "record_id": self._required_int(payload, "record_id"),
        "from_slot": _parse_slot_payload(
            self,
            payload.get("from"),
            layout=layout,
            field_name="from",
        ),
        "date_str": payload.get("date"),
        "dry_run": self._as_bool(payload.get("dry_run", False), default=False),
        "actor_context": self._actor_context(trace_id=trace_id),
        "source": "agent.react",
    }
    if include_target:
        call_kwargs["to_slot"] = _parse_slot_payload(
            self,
            payload.get("to"),
            layout=layout,
            field_name="to",
        )
    return tool_fn(**call_kwargs)


def _call_batch_slot_tool(self, payload, trace_id, *, tool_fn, include_target):
    layout = self._load_layout()
    entries = _parse_batch_slot_entries(
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
        return _call_record_slot_tool(
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
        return _call_record_slot_tool(
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
        return _call_batch_slot_tool(
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
        return _call_batch_slot_tool(
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

def _run_manage_staged(self, payload, _trace_id=None):
    tool_name = "manage_staged"
    operation = payload.get("operation")

    if operation == "list":
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

    if not self._plan_store:
        return {
            "ok": False,
            "error_code": "no_plan_store",
            "message": self._msg(
                "manageStaged.planStoreNotAvailable",
                "Plan store not available.",
            ),
        }

    if operation == "remove":
        idx = self._optional_int(payload, "index")
        if idx is not None:
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

        action = payload.get("action")
        rid = self._optional_int(payload, "record_id")
        pos = self._optional_int(payload, "position")
        count = self._plan_store.remove_by_key(action, rid, pos)
        if count == 0:
            return self._with_hint(
                tool_name,
                {
                    "ok": False,
                    "error_code": "not_found",
                    "message": self._msg(
                        "manageStaged.noMatchingItem",
                        "No matching staged item found.",
                    ),
                },
            )
        return {
            "ok": True,
            "message": self._msg(
                "manageStaged.removedMatchingCount",
                "Removed {count} matching item(s).",
                count=count,
            ),
            "result": {"removed": count},
        }

    if operation == "clear":
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

    return self._unknown_tool_response(tool_name)

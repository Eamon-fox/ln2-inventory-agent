"""Input/schema validation helpers for AgentToolRunner."""

from copy import deepcopy


def _tool_contracts():
    from . import tool_runner as _runner

    return _runner._TOOL_CONTRACTS


def _normalize_search_mode(value):
    if value in (None, ""):
        return "fuzzy"

    text = str(value).strip().lower()
    if text in {"fuzzy", "exact", "keywords"}:
        return text

    from . import tool_runner as _runner

    raise ValueError(
        _runner.AgentToolRunner._msg(
            "errors.modeMustBeOneOf",
            "mode must be one of: fuzzy, exact, keywords",
        )
    )


def tool_specs(self):
    """Compact tool schemas for runtime grounding (single source of truth)."""
    specs = {}
    for name, contract in _tool_contracts().items():
        schema = deepcopy(contract.get("parameters") or {})
        properties = dict(schema.get("properties") or {})
        required = list(schema.get("required") or [])
        optional = [key for key in properties if key not in required]
        desc_default = contract.get("description") or self._msg(
            "toolContracts.defaultDescription",
            "LN2 inventory tool: {name}",
            name=name,
        )
        item = {
            "required": required,
            "optional": optional,
            "params": properties,
            "description": self._msg(
                f"toolContracts.{name}.description",
                desc_default,
            ),
        }
        notes = contract.get("notes")
        if notes:
            item["notes"] = self._msg(
                f"toolContracts.{name}.notes",
                notes,
            )
        specs[name] = item
    return specs


def tool_schemas(self):
    """OpenAI-compatible function tool schemas for native tool calling."""
    schemas = []

    for name, contract in _tool_contracts().items():
        desc_default = contract.get("description") or self._msg(
            "toolContracts.defaultDescription",
            "LN2 inventory tool: {name}",
            name=name,
        )
        schemas.append(
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": self._msg(
                        f"toolContracts.{name}.description",
                        desc_default,
                    ),
                    "parameters": deepcopy(contract.get("parameters") or {}),
                },
            }
        )

    return schemas


def _is_integer(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _validate_schema_value(self, value, schema, path):
    if not isinstance(schema, dict):
        return None

    if "oneOf" in schema:
        options = schema.get("oneOf") or []
        for option in options:
            if self._validate_schema_value(value, option, path) is None:
                return None
        label = path or "value"
        return self._msg(
            "validation.doesNotMatchAllowedSchema",
            "{label} does not match any allowed schema",
            label=label,
        )

    expected_type = schema.get("type")

    if expected_type == "object":
        if not isinstance(value, dict):
            label = path or "payload"
            return self._msg(
                "validation.mustBeObject",
                "{label} must be an object",
                label=label,
            )

        properties = schema.get("properties") or {}
        required = schema.get("required") or []

        for field in required:
            if field not in value:
                return self._msg(
                    "validation.missingRequiredField",
                    "Missing required field: {field}",
                    field=field,
                )

        if schema.get("additionalProperties") is False:
            extras = sorted(set(value.keys()) - set(properties.keys()))
            if extras:
                return self._msg(
                    "validation.unexpectedFields",
                    "Unexpected field(s): {fields}",
                    fields=", ".join(extras),
                )

        min_props = schema.get("minProperties")
        if isinstance(min_props, int) and len(value) < min_props:
            label = path or "payload"
            return self._msg(
                "validation.mustContainAtLeastFields",
                "{label} must contain at least {min_props} field(s)",
                label=label,
                min_props=min_props,
            )

        for key, val in value.items():
            child_schema = properties.get(key)
            if isinstance(child_schema, dict):
                child_path = f"{path}.{key}" if path else key
                err = self._validate_schema_value(val, child_schema, child_path)
                if err:
                    return err

        return None

    if expected_type == "array":
        if not isinstance(value, list):
            label = path or "value"
            return self._msg(
                "validation.mustBeArray",
                "{label} must be an array",
                label=label,
            )

        min_items = schema.get("minItems")
        if isinstance(min_items, int) and len(value) < min_items:
            label = path or "value"
            return self._msg(
                "validation.mustContainAtLeastItems",
                "{label} must contain at least {min_items} item(s)",
                label=label,
                min_items=min_items,
            )

        max_items = schema.get("maxItems")
        if isinstance(max_items, int) and len(value) > max_items:
            label = path or "value"
            return self._msg(
                "validation.mustContainAtMostItems",
                "{label} must contain at most {max_items} item(s)",
                label=label,
                max_items=max_items,
            )

        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for idx, item in enumerate(value):
                item_path = f"{path}[{idx}]" if path else f"[{idx}]"
                err = self._validate_schema_value(item, item_schema, item_path)
                if err:
                    return err
        return None

    if expected_type == "integer":
        if not self._is_integer(value):
            label = path or "value"
            return self._msg(
                "validation.mustBeInteger",
                "{label} must be an integer",
                label=label,
            )
        minimum = schema.get("minimum")
        if isinstance(minimum, int) and value < minimum:
            label = path or "value"
            return self._msg(
                "validation.mustBeGreaterEqual",
                "{label} must be >= {minimum}",
                label=label,
                minimum=minimum,
            )

    elif expected_type == "boolean":
        if not isinstance(value, bool):
            label = path or "value"
            return self._msg(
                "validation.mustBeBoolean",
                "{label} must be a boolean",
                label=label,
            )

    elif expected_type == "string":
        if not isinstance(value, str):
            label = path or "value"
            return self._msg(
                "validation.mustBeString",
                "{label} must be a string",
                label=label,
            )

    enum_values = schema.get("enum")
    if isinstance(enum_values, list) and enum_values and value not in enum_values:
        label = path or "value"
        return self._msg(
            "validation.mustBeOneOf",
            "{label} must be one of: {values}",
            label=label,
            values=", ".join(str(v) for v in enum_values),
        )

    return None


def _validate_tool_input(self, tool_name, payload):
    contract = _tool_contracts().get(tool_name)
    if not contract:
        return None
    schema = contract.get("parameters") or {}
    schema_error = self._validate_schema_value(payload, schema, "")
    if schema_error:
        return schema_error

    if tool_name == "manage_boxes":
        operation = payload.get("operation")
        if operation == "add":
            if "count" not in payload:
                return self._msg(
                    "input.countRequiredWhenAdd",
                    "count is required when operation=add",
                )
            if "box" in payload:
                return self._msg(
                    "input.boxNotAllowedWhenAdd",
                    "box is not allowed when operation=add",
                )
            if "renumber_mode" in payload:
                return self._msg(
                    "input.renumberOnlyForRemove",
                    "renumber_mode is only valid when operation=remove",
                )
        elif operation == "remove":
            if "box" not in payload:
                return self._msg(
                    "input.boxRequiredWhenRemove",
                    "box is required when operation=remove",
                )
            if "count" in payload:
                return self._msg(
                    "input.countNotAllowedWhenRemove",
                    "count is not allowed when operation=remove",
                )

    if tool_name == "search_records":
        has_recent = any(k in payload for k in ("recent_days", "recent_count"))
        if has_recent:
            if "recent_days" in payload and "recent_count" in payload:
                return self._msg(
                    "input.useEitherRecentDaysOrCount",
                    "Use either recent_days or recent_count, not both",
                )
            mixed_fields = [
                k
                for k in (
                    "query",
                    "mode",
                    "max_results",
                    "case_sensitive",
                    "box",
                    "position",
                    "record_id",
                    "active_only",
                )
                if k in payload
            ]
            if mixed_fields:
                return self._msg(
                    "input.recentCannotMixSearchFields",
                    "recent_* filters cannot be mixed with text/structured search fields",
                )

    if tool_name == "query_takeout_events":
        view = payload.get("view", "events")
        if view == "summary":
            forbidden = [k for k in ("date", "start_date", "end_date", "action", "max_records") if k in payload]
            if forbidden:
                return self._msg(
                    "input.summaryViewAllowedFields",
                    "view=summary only supports: view, days, all_history",
                )
        elif "all_history" in payload:
            return self._msg(
                "input.allHistoryOnlyForSummary",
                "all_history is only valid when view=summary",
            )

    if tool_name == "manage_staged":
        operation = payload.get("operation")
        has_index = "index" in payload
        has_key_fields = any(k in payload for k in ("action", "record_id", "position"))

        if operation in {"list", "clear"}:
            if has_index or has_key_fields:
                return self._msg(
                    "input.manageStagedSelectorOnlyForRemove",
                    "index/action/record_id/position are only valid when operation=remove",
                )
        elif operation == "remove":
            if has_index and has_key_fields:
                return self._msg(
                    "input.manageStagedIndexOrKeyNotBoth",
                    "Provide either index OR action+record_id+position, not both",
                )
            if not has_index and not has_key_fields:
                return self._msg(
                    "input.manageStagedNeedIndexOrKey",
                    "Provide either index OR action+record_id+position",
                )
            if has_key_fields and not all(k in payload for k in ("action", "record_id", "position")):
                return self._msg(
                    "input.manageStagedNeedActionRecordPosition",
                    "action, record_id, and position are required when removing by key",
                )

    if tool_name == "record_takeout":
        action = str(payload.get("action") or "takeout").lower()
        if action == "move" and "to_position" not in payload:
            return self._msg(
                "input.toPositionRequiredWhenMove",
                "to_position is required when action=move",
            )

    if tool_name == "rollback":
        backup_path = str(payload.get("backup_path") or "").strip()
        if not backup_path:
            return self._msg(
                "input.backupPathRequired",
                "backup_path must be a non-empty string",
            )

    return None

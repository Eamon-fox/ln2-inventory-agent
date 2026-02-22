"""Input/schema validation helpers for AgentToolRunner."""

from copy import deepcopy
from lib.tool_contracts import TOOL_CONTRACTS


_HIDDEN_LLM_FIELDS = {"dry_run"}
_POSITION_FIELD_KEYS = {"position", "from_position", "to_position"}


def _tool_contracts():
    return TOOL_CONTRACTS


def _filter_schema_for_llm(schema):
    """Drop internal-only fields before exposing schemas to the LLM."""
    filtered = deepcopy(schema) if isinstance(schema, dict) else {}
    properties = filtered.get("properties")
    if isinstance(properties, dict):
        for field in _HIDDEN_LLM_FIELDS:
            properties.pop(field, None)
    required = filtered.get("required")
    if isinstance(required, list):
        filtered["required"] = [name for name in required if name not in _HIDDEN_LLM_FIELDS]
    return filtered


def _layout_indexing(layout):
    text = str((layout or {}).get("indexing", "numeric")).strip().lower()
    return "alphanumeric" if text == "alphanumeric" else "numeric"


def _strict_position_value_schema(layout):
    if _layout_indexing(layout) == "alphanumeric":
        return {"type": "string"}
    return {"type": "integer", "minimum": 1}


def _merge_schema_metadata(base_schema, strict_schema):
    merged = dict(strict_schema)
    if not isinstance(base_schema, dict):
        return merged
    for key in ("description", "title", "examples", "default"):
        if key in base_schema and key not in merged:
            merged[key] = deepcopy(base_schema[key])
    return merged


def _custom_field_value_schema(field_type):
    type_name = str(field_type or "str").strip().lower()
    if type_name == "int":
        return {"type": "integer"}
    if type_name == "float":
        return {"type": "number"}
    if type_name == "date":
        return {"type": "string", "description": "Date in YYYY-MM-DD format."}
    return {"type": "string"}


def _dynamic_fields_schema(meta, *, include_frozen_at):
    from lib.custom_fields import (
        get_cell_line_options,
        get_effective_fields,
        get_required_field_keys,
        is_cell_line_required,
    )

    field_properties = {}
    if include_frozen_at:
        field_properties["frozen_at"] = {"type": "string", "description": "Date in YYYY-MM-DD format."}

    cell_line_schema = {"type": "string"}
    cell_line_options = [str(option).strip() for option in get_cell_line_options(meta) if str(option).strip()]
    if cell_line_options:
        cell_line_schema["enum"] = cell_line_options
    field_properties["cell_line"] = cell_line_schema
    field_properties["note"] = {"type": "string"}

    for field in get_effective_fields(meta):
        if not isinstance(field, dict):
            continue
        key = str(field.get("key") or "").strip()
        if not key:
            continue
        field_properties[key] = _custom_field_value_schema(field.get("type"))

    required_for_add = set(get_required_field_keys(meta))
    if is_cell_line_required(meta):
        required_for_add.add("cell_line")

    return field_properties, sorted(required_for_add)


def _apply_dynamic_fields_rules(schema, meta, *, tool_name=None):
    if not isinstance(schema, dict):
        return schema

    narrowed = deepcopy(schema)
    properties = narrowed.get("properties")
    if not isinstance(properties, dict):
        return narrowed

    fields_schema = properties.get("fields")
    if not isinstance(fields_schema, dict):
        return narrowed

    if tool_name == "add_entry":
        field_properties, required_for_add = _dynamic_fields_schema(meta, include_frozen_at=False)
        dynamic_schema = {
            "type": "object",
            "properties": field_properties,
            "additionalProperties": False,
        }
        if required_for_add:
            dynamic_schema["required"] = required_for_add
            required_top = list(narrowed.get("required") or [])
            if "fields" not in required_top:
                required_top.append("fields")
            narrowed["required"] = required_top
        properties["fields"] = _merge_schema_metadata(fields_schema, dynamic_schema)
        return narrowed

    if tool_name == "edit_entry":
        field_properties, _required_for_add = _dynamic_fields_schema(meta, include_frozen_at=True)
        dynamic_schema = {
            "type": "object",
            "properties": field_properties,
            "additionalProperties": False,
            "minProperties": 1,
        }
        properties["fields"] = _merge_schema_metadata(fields_schema, dynamic_schema)

    return narrowed


def _apply_layout_position_rules(schema, layout, *, tool_name=None):
    if not isinstance(schema, dict):
        return schema

    narrowed = deepcopy(schema)

    properties = narrowed.get("properties")
    if isinstance(properties, dict):
        for key, value in list(properties.items()):
            if key in _POSITION_FIELD_KEYS:
                strict_value_schema = _strict_position_value_schema(layout)
                properties[key] = _merge_schema_metadata(value, strict_value_schema)
                continue

            if tool_name == "add_entry" and key == "positions":
                strict_positions_schema = {
                    "type": "array",
                    "items": _strict_position_value_schema(layout),
                    "minItems": 1,
                }
                properties[key] = _merge_schema_metadata(value, strict_positions_schema)
                continue

            properties[key] = _apply_layout_position_rules(
                value,
                layout,
                tool_name=tool_name,
            )

    items = narrowed.get("items")
    if isinstance(items, dict):
        narrowed["items"] = _apply_layout_position_rules(items, layout, tool_name=tool_name)

    one_of = narrowed.get("oneOf")
    if isinstance(one_of, list):
        narrowed["oneOf"] = [
            _apply_layout_position_rules(option, layout, tool_name=tool_name)
            if isinstance(option, dict)
            else option
            for option in one_of
        ]

    return narrowed


def _sanitize_tool_input_payload(payload):
    """Ignore LLM-internal fields if the model still sends them."""
    normalized = dict(payload) if isinstance(payload, dict) else {}
    for field in _HIDDEN_LLM_FIELDS:
        normalized.pop(field, None)
    return normalized


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


def _tool_input_schema(self, tool_name):
    contract = _tool_contracts().get(tool_name)
    if not isinstance(contract, dict):
        return {}
    base_schema = _filter_schema_for_llm(contract.get("parameters") or {})
    meta = self._load_meta() if hasattr(self, "_load_meta") else {}
    layout = self._load_layout() if hasattr(self, "_load_layout") else {}
    position_schema = _apply_layout_position_rules(base_schema, layout, tool_name=tool_name)
    return _apply_dynamic_fields_rules(position_schema, meta, tool_name=tool_name)


def _tool_input_field_sets(self, tool_name):
    schema = _tool_input_schema(self, tool_name)
    properties = dict(schema.get("properties") or {})
    required = list(schema.get("required") or [])
    optional = [key for key in properties if key not in required]
    return required, optional


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
                    "parameters": _tool_input_schema(self, name),
                },
            }
        )

    return schemas


def _is_integer(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


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

    elif expected_type == "number":
        if not _is_number(value):
            label = path or "value"
            return self._msg(
                "validation.mustBeNumber",
                "{label} must be a number",
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

    if tool_name == "search_records":
        query_text = payload.get("query")
        if query_text is None or str(query_text).strip() == "":
            return self._msg(
                "input.searchQueryRequired",
                "未输入检索词",
            )

    schema = _tool_input_schema(self, tool_name)
    schema_error = self._validate_schema_value(payload, schema, "")
    if schema_error:
        return schema_error

    if tool_name == "recent_frozen":
        basis = str(payload.get("basis") or "").strip().lower()
        if basis not in {"days", "count"}:
            return self._msg(
                "validation.mustBeOneOf",
                "{label} must be one of: {values}",
                label="basis",
                values="days, count",
            )

    if tool_name == "rollback":
        backup_path = str(payload.get("backup_path") or "").strip()
        if not backup_path:
            return self._msg(
                "input.backupPathRequired",
                "backup_path must be a non-empty string",
            )

    return None

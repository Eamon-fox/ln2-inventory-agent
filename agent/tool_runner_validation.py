"""Input/schema validation helpers for AgentToolRunner."""

from copy import deepcopy
from lib.tool_contracts import TOOL_CONTRACTS


def _tool_contracts():
    return TOOL_CONTRACTS


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

"""Input/schema validation helpers for AgentToolRunner."""

from copy import deepcopy
from pathlib import Path

from lib.legacy_field_policy import (
    PHASE_SCHEMA,
    PHASE_STAGING,
    resolve_legacy_field_policy,
)
from lib.schema_aliases import normalize_record_sort_field, normalize_structural_alias_input_map
from lib.tool_registry import TOOL_CONTRACTS


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


def _dynamic_fields_schema(meta, inventory, *, include_stored_at):
    from lib.custom_fields import (
        get_effective_fields,
        get_required_field_keys,
    )

    field_properties = {}
    if include_stored_at:
        field_properties["stored_at"] = {"type": "string", "description": "Date in YYYY-MM-DD format."}

    # Build schemas for all effective fields exposed by the active policy.
    for field in get_effective_fields(
        meta,
        inventory=inventory,
        phase=PHASE_SCHEMA,
    ):
        if not isinstance(field, dict):
            continue
        key = str(field.get("key") or "").strip()
        if not key:
            continue
        schema = _custom_field_value_schema(field.get("type"))
        options = field.get("options")
        if isinstance(options, list) and options:
            schema["enum"] = [str(o).strip() for o in options if str(o).strip()]
        field_properties[key] = schema

    required_for_add = set(
        get_required_field_keys(
            meta,
            inventory=inventory,
            phase=PHASE_SCHEMA,
        )
    )

    return field_properties, sorted(required_for_add)


def _enrich_add_entry_schema(_runner, schema, *, meta=None, inventory=None):
    if not isinstance(schema, dict):
        return schema

    narrowed = deepcopy(schema)
    properties = narrowed.get("properties")
    if not isinstance(properties, dict):
        return narrowed

    fields_schema = properties.get("fields")
    if not isinstance(fields_schema, dict):
        return narrowed

    field_properties, required_for_add = _dynamic_fields_schema(
        meta,
        inventory,
        include_stored_at=False,
    )
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


def _enrich_edit_entry_schema(_runner, schema, *, meta=None, inventory=None):
    if not isinstance(schema, dict):
        return schema

    narrowed = deepcopy(schema)
    properties = narrowed.get("properties")
    if not isinstance(properties, dict):
        return narrowed

    fields_schema = properties.get("fields")
    if not isinstance(fields_schema, dict):
        return narrowed

    field_properties, _required_for_add = _dynamic_fields_schema(
        meta,
        inventory,
        include_stored_at=True,
    )
    dynamic_schema = {
        "type": "object",
        "properties": field_properties,
        "additionalProperties": False,
        "minProperties": 1,
    }
    properties["fields"] = _merge_schema_metadata(fields_schema, dynamic_schema)
    return narrowed


def _apply_layout_position_rules(schema, layout, *, array_fields=()):
    if not isinstance(schema, dict):
        return schema

    narrowed = deepcopy(schema)
    strict_position_schema = _strict_position_value_schema(layout)
    strict_array_fields = set(array_fields or ())

    properties = narrowed.get("properties")
    if isinstance(properties, dict):
        for key, value in list(properties.items()):
            if key in _POSITION_FIELD_KEYS:
                properties[key] = _merge_schema_metadata(value, strict_position_schema)
                continue

            if key in strict_array_fields:
                strict_positions_schema = {
                    "type": "array",
                    "items": strict_position_schema,
                    "minItems": 1,
                }
                properties[key] = _merge_schema_metadata(value, strict_positions_schema)
                continue

            properties[key] = _apply_layout_position_rules(
                value,
                layout,
                array_fields=strict_array_fields,
            )

    items = narrowed.get("items")
    if isinstance(items, dict):
        narrowed["items"] = _apply_layout_position_rules(items, layout, array_fields=strict_array_fields)

    one_of = narrowed.get("oneOf")
    if isinstance(one_of, list):
        narrowed["oneOf"] = [
            _apply_layout_position_rules(option, layout, array_fields=strict_array_fields)
            if isinstance(option, dict)
            else option
            for option in one_of
        ]

    return narrowed


def _sanitize_tool_input_payload(payload):
    """Normalize direct caller payloads without dropping supported contract fields."""
    normalized = dict(payload) if isinstance(payload, dict) else {}
    normalized, _alias_errors = normalize_structural_alias_input_map(
        normalized,
        scope="payload",
    )
    sort_by_value = normalized.get("sort_by")
    if isinstance(sort_by_value, str):
        normalized["sort_by"] = normalize_record_sort_field(sort_by_value)
    fields = normalized.get("fields")
    if isinstance(fields, dict):
        normalized["fields"], _field_alias_errors = normalize_structural_alias_input_map(
            fields,
            scope="fields",
        )
    return normalized


def _adapt_add_edit_schema_validation_payload(tool_name, payload, schema, *, meta=None, inventory=None):
    """Return a payload variant used only for strict schema validation.

    We keep some legacy add-entry fields accepted at staging time even when the
    LLM-facing schema intentionally hides them for new datasets.
    """
    normalized = dict(payload) if isinstance(payload, dict) else {}

    policy = resolve_legacy_field_policy(
        meta if isinstance(meta, dict) else {},
        inventory if isinstance(inventory, list) else [],
        declared_fields=((meta or {}).get("custom_fields") if isinstance(meta, dict) else None),
        phase=PHASE_STAGING,
    )
    field_schema = ((schema or {}).get("properties") or {}).get("fields") or {}
    field_properties = field_schema.get("properties") if isinstance(field_schema, dict) else {}
    visible_keys = set((field_properties or {}).keys())
    hidden_keys = {
        key
        for key in (policy.get("staging_input_keys") or set())
        if key not in visible_keys
    }
    if not hidden_keys:
        return normalized

    fields = normalized.get("fields")
    if not isinstance(fields, dict):
        return normalized

    filtered_fields = {
        key: value
        for key, value in fields.items()
        if key not in hidden_keys
    }
    if len(filtered_fields) == len(fields):
        return normalized

    adjusted = dict(normalized)
    if tool_name == "edit_entry" and not filtered_fields:
        adjusted["fields"] = {"stored_at": "2000-01-01"}
        return adjusted

    adjusted["fields"] = filtered_fields
    return adjusted


def _adapt_add_entry_schema_validation_payload(_runner, payload, schema, *, meta=None, inventory=None):
    return _adapt_add_edit_schema_validation_payload(
        "add_entry",
        payload,
        schema,
        meta=meta,
        inventory=inventory,
    )


def _adapt_edit_entry_schema_validation_payload(_runner, payload, schema, *, meta=None, inventory=None):
    return _adapt_add_edit_schema_validation_payload(
        "edit_entry",
        payload,
        schema,
        meta=meta,
        inventory=inventory,
    )


def _normalize_search_mode(self, value):
    if value in (None, ""):
        return "fuzzy"

    text = str(value).strip().lower()
    if text in {"fuzzy", "exact", "keywords"}:
        return text

    raise ValueError(
        self._msg(
            "errors.modeMustBeOneOf",
            "mode must be one of: fuzzy, exact, keywords",
        )
        )


def _tool_input_schema(self, tool_name, *, include_hidden=False):
    contract = _tool_contracts().get(tool_name)
    if not isinstance(contract, dict):
        return {}
    base_schema = deepcopy(contract.get("parameters") or {})
    if not include_hidden:
        base_schema = _filter_schema_for_llm(base_schema)
    meta = self._load_meta() if hasattr(self, "_load_meta") else {}
    inventory = self._load_inventory() if hasattr(self, "_load_inventory") else []
    layout = self._load_layout() if hasattr(self, "_load_layout") else {}
    runtime_spec = self._runtime_spec(tool_name) if hasattr(self, "_runtime_spec") else None
    array_fields = tuple(getattr(runtime_spec, "layout_array_fields", ()) or ())
    schema = _apply_layout_position_rules(base_schema, layout, array_fields=array_fields)
    schema_enricher = getattr(runtime_spec, "schema_enricher", None)
    if callable(schema_enricher):
        return schema_enricher(
            self,
            schema,
            meta=meta,
            inventory=inventory,
        )
    return schema


def _tool_input_field_sets(self, tool_name):
    schema = _tool_input_schema(self, tool_name)
    properties = dict(schema.get("properties") or {})
    required = list(schema.get("required") or [])
    optional = [key for key in properties if key not in required]
    return required, optional


def tool_schemas(self):
    """OpenAI-compatible function tool schemas for native tool calling."""
    schemas = []

    tool_names = self.list_tools() if hasattr(self, "list_tools") else list(_tool_contracts().keys())
    for name in tool_names:
        contract = _tool_contracts().get(name) or {}
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


def _looks_absolute_path(value):
    text = str(value or "").strip()
    if not text:
        return False
    if text.startswith(("/", "\\")):
        return True
    if len(text) >= 2 and text[1] == ":" and text[0].isalpha():
        return True
    return Path(text).is_absolute()


def _guard_repo_relative_path(self, payload, *, field_name, message_key, default_message):
    path_value = payload.get(field_name)
    if path_value not in (None, "") and _looks_absolute_path(path_value):
        return self._msg(
            message_key,
            default_message,
        )
    return None


def _guard_fs_read_write(self, payload):
    return _guard_repo_relative_path(
        self,
        payload,
        field_name="path",
        message_key="input.pathMustBeRepoRelative",
        default_message="path must be repository-relative (absolute paths are not allowed).",
    )


def _guard_fs_list(self, payload):
    return _guard_repo_relative_path(
        self,
        payload,
        field_name="path",
        message_key="input.pathMustBeRepoRelative",
        default_message="path must be repository-relative (absolute paths are not allowed).",
    )


def _guard_fs_edit(self, payload):
    return _guard_repo_relative_path(
        self,
        payload,
        field_name="filePath",
        message_key="input.filePathMustBeRepoRelative",
        default_message="filePath must be repository-relative (absolute paths are not allowed).",
    )


def _guard_shell_workdir(self, payload):
    return _guard_repo_relative_path(
        self,
        payload,
        field_name="workdir",
        message_key="input.workdirMustBeRepoRelative",
        default_message="workdir must be repository-relative (absolute paths are not allowed).",
    )


def _guard_recent_basis(self, payload):
    basis = str(payload.get("basis") or "").strip().lower()
    if basis not in {"days", "count"}:
        return self._msg(
            "validation.mustBeOneOf",
            "{label} must be one of: {values}",
            label="basis",
            values="days, count",
        )
    return None


def _guard_rollback_backup_path(self, payload):
    backup_path = str(payload.get("backup_path") or "").strip()
    if not backup_path:
        return self._msg(
            "input.backupPathRequired",
            "backup_path must be a non-empty string",
        )
    return None


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

    schema = _tool_input_schema(self, tool_name, include_hidden=True)
    meta = self._load_meta() if hasattr(self, "_load_meta") else {}
    inventory = self._load_inventory() if hasattr(self, "_load_inventory") else []
    runtime_spec = self._runtime_spec(tool_name) if hasattr(self, "_runtime_spec") else None
    validation_payload_adapter = getattr(runtime_spec, "validation_payload_adapter", None)
    if callable(validation_payload_adapter):
        validation_payload = validation_payload_adapter(
            self,
            payload,
            schema,
            meta=meta,
            inventory=inventory,
        )
    else:
        validation_payload = dict(payload) if isinstance(payload, dict) else {}
    schema_error = self._validate_schema_value(
        validation_payload,
        schema,
        "",
    )
    if schema_error:
        return schema_error

    input_guard = getattr(runtime_spec, "input_guard", None)
    if callable(input_guard):
        guard_error = input_guard(self, payload)
        if guard_error:
            return guard_error

    return None

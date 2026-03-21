# Field Schema Reference

Use this reference when the user asks about YAML field structure, custom-field rules, selector behavior, or when a repair/script must preserve the schema shape.

## 1. Built-In Fields

SnowFox has 5 canonical structural record fields:

- `id`: integer record identity
- `box`: integer box identity
- `position`: integer slot identity inside a box
- `stored_at`: canonical stored-date field, `YYYY-MM-DD`
- `storage_events`: canonical event-history field

These 5 keys are structural. They are not user-configurable custom fields.

There is also 1 fixed system custom field that is always present in effective schema:

- `note`: label `Note`, type `str`, `required: false`, `multiline: true`

`note` is not structural, but it is protected. Users must not rename another custom field to `note`.

## 2. User Custom Field Rules

User-defined fields live in `meta.custom_fields` as one global schema list.

- Use a single global `meta.custom_fields` schema.
- `meta.box_fields` is no longer supported.
- Field keys must be valid identifiers.
- Custom-field keys must not collide with structural keys like `id`, `box`, `position`, `stored_at`, or `storage_events`.
- Renaming a custom field to a structural key or to fixed `note` is blocked.
- There are no default preset custom fields beyond the fixed `note` behavior.

`cell_line` is not structural. It is treated as a normal custom field when declared in schema.

## 3. Field Attributes

Each custom-field entry may use these schema keys:

- `key`: machine key
- `label`: user-facing label
- `type`: one of `str`, `int`, `float`, `date`
- `default`: optional default value
- `required`: boolean
- `options`: optional list of allowed non-empty string values
- `multiline`: optional boolean, mainly used for long text such as `note`

A field can be either required or optional:

- `required: true` means schema-aware write flows should treat it as mandatory.
- `required: false` means the field may be omitted or left empty.

Compatibility note:

- Option-constrained mismatches may still surface as warnings in some validation/import compatibility paths.
- Canonical write flows should still preserve declared schema and avoid values outside declared options.

## 4. Selector / Dropdown Behavior

Two metadata selectors point at declared custom fields:

- `display_key` / `meta.display_key`: which custom field is shown as the main grid label
- `color_key` / `meta.color_key`: which custom field drives color/filter grouping

If a field declares `options`, schema-driven surfaces treat it as a constrained-choice field.

- The schema stores options as a string list.
- Non-empty values are expected to come from that list.
- Without `options`, the field behaves like free text (or typed free input for `int` / `float` / `date`).

## 5. Indexing Mode And Numeric Storage

Position indexing mode is controlled by:

- `meta.box_layout.indexing`

Allowed values:

- `numeric`
- `alphanumeric`

Important rule:

- Switching indexing changes display/input mode only.
- Stored `inventory[].position` remains an integer.
- Do not rewrite stored positions into strings like `A1`.

## 6. Canonical / Legacy Naming

Canonical persisted names are:

- `stored_at` instead of legacy `frozen_at`
- `storage_events` instead of legacy `thaw_events`

Legacy compatibility still exists for some inputs:

- record alias `parent_cell_line` may map to canonical `cell_line`
- legacy meta keys `cell_line_options` and `cell_line_required` may still be canonicalized into schema-backed `cell_line` behavior during compatibility windows

When writing or repairing YAML, prefer canonical names.

## 7. Simplest Schema Example

```yaml
meta:
  box_layout:
    rows: 9
    cols: 9
    box_count: 2
    box_numbers: [1, 2]
    indexing: numeric
  custom_fields:
    - key: cell_line
      label: Cell Line
      type: str
      required: true
      options: [K562, HeLa]
    - key: short_name
      label: Short Name
      type: str
      required: false
  display_key: short_name
  color_key: cell_line

inventory:
  - id: 1
    box: 1
    position: 1
    stored_at: "2026-01-02"
    cell_line: "K562"
    short_name: "clone-a"
    note: "baseline seed"
    storage_events: []
```

## 8. Repair Rule Of Thumb

If a user forces script-based repair anyway:

- preserve structural keys and their value types
- preserve `inventory[].position` as integer
- preserve canonical names like `stored_at`
- keep `meta.custom_fields` as the single schema source
- do not invent undeclared custom-field keys unless the user is intentionally editing schema

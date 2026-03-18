# Structural Fields

Treat these record keys as structural inventory fields:

- `id`
- `box`
- `position`
- `frozen_at`
- `thaw_events`

## Notes

- Structural fields are not custom fields.
- `cell_line` and `note` are default custom fields, not structural fields.
- `meta.custom_fields` must not reuse structural field keys.

# Structural Fields

Treat these record keys as structural inventory fields:

- `id`
- `box`
- `position`
- `stored_at`
- `storage_events`

## Notes

- Structural fields are not custom fields.
- `cell_line` and `note` are default custom fields, not structural fields.
- `meta.custom_fields` must not reuse structural field keys.
- Legacy input aliases `frozen_at` and `thaw_events` may still appear in older datasets, but generated migration output should use `stored_at` and `storage_events`.

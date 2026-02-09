# GUI Scaffold (M2 starter)

This directory contains a minimal desktop GUI scaffold that calls the unified Tool API.

Current status:

- `Overview` is the default first tab with per-box grid visualization (9x9 style)
- Overview supports clickable cells and a detail panel (ID/cell/short/frozen/plasmid/note)
- Overview includes summary cards (records, capacity, occupied, empty, occupancy rate, 7-day ops)
- Overview supports filters (box/cell/keyword/show-empty) for focused browsing
- Overview detail panel supports quick actions (copy ID, prefill thaw form)
- Overview cells support right-click context menu (copy location/ID, prefill thaw)
- Quick Start flow lets users choose current/demo/custom YAML on launch
- Settings dialog manages YAML path and actor ID (advanced options moved off main screen)
- Query panel wired to `tool_query_inventory` / `tool_list_empty_positions`
- Query results render in an interactive table (records and empty-slot views)
- Query table can export current view to CSV
- Query/backup tables support sorting; table widths and last tab are persisted across sessions
- Add Entry panel wired to `tool_add_entry`
- Single and batch thaw panels wired to `tool_record_thaw` / `tool_batch_thaw`
- Inputs are typed widgets (spin boxes/date pickers/action dropdowns) to reduce format errors
- Operation buttons now reflect dry-run state (`Preview` vs `Execute`)
- Rollback panel supports backup listing and rollback by selected path/latest
- Rollback now requires explicit confirmation with backup path/time/size
- GUI calls go through `GuiToolBridge` with `channel="gui"`

Run:

```bash
pip install PySide6
python app_gui/main.py
```

The scaffold is intentionally minimal and exists to unblock M2 implementation.

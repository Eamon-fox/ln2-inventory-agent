# GUI Scaffold (M2 starter)

This directory contains a minimal desktop GUI scaffold that calls the unified Tool API.

Current status:

- GUI now uses a single-screen dashboard layout (left: overview, middle: manual operations, right: AI copilot)
- The 3 columns are resizable so users can prioritize overview/manual/AI focus
- Manual operations use a compact mode selector instead of multiple large action tabs/buttons
- Raw JSON output is hidden by default and can be expanded on demand
- `Overview` panel provides per-box grid visualization (9x9 style)
- `AI Copilot` panel supports natural-language requests via ReAct runtime
- AI Copilot provides quick prompts and structured output (`计划 -> 预览 -> 执行结果 -> 审计记录`)
- AI Copilot keeps the chat input composer at the bottom, with advanced settings/report panels collapsed by default
- AI composer supports `Enter` to send and `Shift+Enter` for newline
- AI run executes in background; only send is blocked while waiting, input/editing stays responsive
- User message is appended to chat immediately on send, then agent response arrives asynchronously
- AI panel streams step-by-step progress in chat while the agent is running
- AI Copilot supports mock mode (default) and LiteLLM model mode
- Overview supports hover/click slot preview with a compact detail hint line
- Hover preview is handled with enter/move events for immediate slot detail updates
- Overview includes summary cards (records, capacity, occupied, empty, occupancy rate, 7-day ops)
- Overview supports filters (box/cell/keyword/show-empty) for focused browsing
- Overview shows only keyword search by default; extra filters are behind a "More Filters" toggle
- Removed redundant "Ask AI" quick button from Overview (AI panel is always visible on the right)
- Quick actions (copy ID, prefill thaw form) are available from each slot's right-click menu
- Overview cells support right-click context menu (copy location/ID, prefill thaw)
- Quick Start flow lets users choose current/demo/custom YAML on launch
- Settings dialog manages YAML path and actor ID (advanced options moved off main screen)
- Query panel wired to `tool_query_inventory` / `tool_list_empty_positions`
- Query results render in an interactive table (records and empty-slot views)
- Query table can export current view to CSV
- Query/backup tables support sorting; table widths and last operation mode are persisted across sessions
- Add Entry panel wired to `tool_add_entry`
- Single and batch thaw panels wired to `tool_record_thaw` / `tool_batch_thaw`
- Thaw panel shows rich prefill context (cell/short/box/all positions/target check/frozen/plasmid/history/note)
- Inputs are typed widgets (spin boxes/date pickers/action dropdowns) to reduce format errors
- Operation buttons now reflect dry-run state (`Preview` vs `Execute`)
- Non-dry-run `Execute` actions (Add/Single/Batch) show a confirmation dialog before write
- Rollback panel supports backup listing and rollback by selected path/latest
- Rollback now requires explicit confirmation with backup path/time/size
- GUI calls go through `GuiToolBridge` with `channel="gui"`
- AI tool traces are mapped to audit events by `trace_id`

Run:

```bash
pip install PySide6
python app_gui/main.py
```

The scaffold is intentionally minimal and exists to unblock M2 implementation.

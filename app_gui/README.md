# GUI Scaffold (M2 starter)

This directory contains a minimal desktop GUI scaffold that calls the unified Tool API.

Current status:

- GUI now uses a single-screen dashboard layout (left: overview, middle: manual operations, right: AI copilot)
- The 3 columns are resizable so users can prioritize overview/manual/AI focus
- Manual operations use a compact mode selector instead of multiple large action tabs/buttons
- Execution flow is shown in Plan/AI reporting panels (Plan details, execution result, and audit log)
- `Overview` panel provides per-box grid visualization (9x9 style)
- `AI Copilot` panel supports natural-language requests via ReAct runtime
- AI Copilot provides quick prompts and structured output (`plan -> preview -> execution result -> audit log`)
- AI Copilot keeps the chat input composer at the bottom, with advanced settings/report panels collapsed by default
- AI composer supports `Enter` to send and `Shift+Enter` for newline
- AI run executes in background; only send is blocked while waiting, input/editing stays responsive
- User message is appended to chat immediately on send, then agent response arrives asynchronously
- AI panel streams step-by-step progress in chat while the agent is running
- AI Copilot uses DeepSeek model mode
- Overview supports hover/click slot preview with a compact detail hint line
- Hover preview is handled with enter/move events for immediate slot detail updates
- Overview includes summary cards (records, capacity, occupied, empty, occupancy rate, 7-day ops)
- Overview supports filters (box/cell/keyword/show-empty) for focused browsing
- Overview shows only keyword search by default; extra filters are behind a "More Filters" toggle
- Removed redundant "Ask AI" quick button from Overview (AI panel is always visible on the right)
- Quick actions (copy ID, prefill takeout form) are available from each slot's right-click menu
- Overview cells support right-click context menu (copy location/ID, prefill takeout)
- Settings dialog manages YAML path and actor ID (advanced options moved off main screen)
- Query panel wired to `tool_query_inventory` / `tool_list_empty_positions`
- Query results render in an interactive table (records and empty-slot views)
- Query table can export current view to CSV
- Query/backup tables support sorting; table widths and last operation mode are persisted across sessions
- Add Entry panel wired to `tool_add_entry`
- Single and batch takeout panels wired to `tool_record_takeout` / `tool_batch_takeout`
- Takeout panel shows rich prefill context (cell/short/box/all positions/target check/frozen/plasmid/history/note)
- Batch takeout operation is placed in an independent collapsible section in the Takeout panel
- Inputs are typed widgets (spin boxes/date pickers/action dropdowns) to reduce format errors
- Action dropdown supports Takeout / Move (Move requires `To Position`; supports real relocation/swap)
- Manual operations are execute-only (no dry-run toggle in GUI)
- Execute actions (Add/Single/Batch) are highlighted in red and require confirmation before write
- Rollback panel supports backup listing and rollback by selected path/latest
- Rollback now requires explicit confirmation with backup path/time/size
- GUI calls go through `GuiToolBridge` with shared `session_id` context
- AI tool traces are mapped to audit events by `trace_id`

Run:

```bash
pip install PySide6
python app_gui/main.py
```

Config paths and defaults:

- GUI settings: `~/.ln2agent/config.yaml`
- AI default model: `deepseek-chat`
- Missing key hint: GUI chat shows where to set `DEEPSEEK_API_KEY` or auth file
- Frozen EXE demo dataset path: `~/.ln2agent/demo/ln2_inventory.demo.yaml`

Packaging notes:

- `pyinstaller ln2_inventory.spec` builds one-dir output (`dist/LN2InventoryAgent/`)
- Inno Setup script is included: `installer/windows/LN2InventoryAgent.iss`
- Example installer build command: `"C:\\Program Files (x86)\\Inno Setup 6\\ISCC.exe" installer\\windows\\LN2InventoryAgent.iss`
- Output installer: `dist/installer/LN2InventoryAgent-Setup-<version>.exe`

The scaffold is intentionally minimal and exists to unblock M2 implementation.


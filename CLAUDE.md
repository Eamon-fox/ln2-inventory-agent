# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Environment Setup

```bash
source .venv/bin/activate
```

All commands (python, pytest, etc.) must run inside the repository-local `.venv`. Do not use system python.

## Build & Run

```bash
# Install (single dependency)
python -m pip install pyyaml

# GUI (requires PySide6)
python -m pip install PySide6
python app_gui/main.py

# AI Agent (requires DEEPSEEK_API_KEY)
python app_gui/main.py

# Windows packaging
pyinstaller ln2_inventory.spec

# Windows installer (Inno Setup)
iscc installer/windows/LN2InventoryAgent.iss
```

## Testing

```bash
# All tests
python -m pytest tests/

# Single test file
python -m pytest tests/test_tool_api.py -v

# Single test
python -m pytest tests/test_tool_api.py::TestToolAddEntry::test_basic_add -v

# GUI tests (need PySide6)
python -m pytest tests/integration/gui -v
```

No mocking framework required — tests use real YAML in temp directories.

## Architecture

Four-layer design with a single unified API (`lib/tool_api.py`) shared by all three frontends:

```
GUI (app_gui/)  ─┼──▶  lib/tool_api.py  ──▶  lib/{yaml_ops,validators,operations,thaw_parser}
Agent (agent/)  ─┘           │                              │
                             ▼                              ▼
                      Standard result:               lib/config.py
                      {ok, result, error_code, message}
```

### Key modules

- **`lib/tool_api.py`** — unified tool functions (add, takeout, move, query, search, stats, recommend, rollback, etc.). Every write goes through validate → backup → write → audit.
- **`lib/config.py`** — Runtime configuration with priority: built-in defaults → `LN2_CONFIG_FILE` env JSON → PyInstaller frozen detection. Exports `YAML_PATH`, `BOX_RANGE`, `POSITION_RANGE`, etc.
- **`lib/yaml_ops.py`** — YAML I/O with atomic backup-before-write and JSONL audit logging.
- **`lib/validators.py`** — Date/box/position validation, position-conflict and duplicate-ID checks.
- **`lib/takeout_parser.py`** — Chinese/English action normalization (取出/takeout, 复苏/thaw, 扔掉/discard, 移动/move).
- **`agent/react_agent.py`** — ReAct loop: LLM call → tool dispatch (parallel via ThreadPoolExecutor) → observation → repeat until max_steps or direct answer.
- **`agent/tool_runner.py`** — Dispatches named tool calls to `tool_api`, with plan-stashing for write operations (human approval required in GUI).
- **`app_gui/tool_bridge.py`** — Adapter stamping GUI metadata (actor_id) onto tool_api calls.
- **`app_gui/ui/ai_panel.py`** — Chat widget with streaming markdown re-rendering and tool progress display.
- **`app_gui/ui/overview_panel.py`** — 9x9 grid visualization per box, multi-select for batch operations.
- **`app_gui/ui/operations_panel.py`** — Forms for add/thaw/move, plan staging/execution/undo, export (CSV/HTML).

### Data model

Single YAML file (`ln2_inventory.yaml`): `inventory[]` records with structural fields `id`, `box`, `position`, `stored_at`, `storage_events[]`, plus schema-declared custom fields (for example `cell_line`, `short_name`, `note`) and `meta.box_layout`. Legacy aliases like `frozen_at` / `thaw_events` may still be accepted on read, but canonical persisted/output names are `stored_at` / `storage_events`. Default grid is 9x9 (positions 1-81) across boxes 1-5.

### GUI panel communication (Qt signals)

- OverviewPanel → OperationsPanel: `plan_items_requested`, `request_prefill`, `data_loaded`
- OperationsPanel → OverviewPanel: `operation_completed`
- AIPanel → OperationsPanel: `plan_items_staged`, `operation_completed`

### i18n

Translation files at `app_gui/i18n/translations/{en,zh-CN}.json`. Use `tr("key.subkey")` throughout GUI code.

## Configuration

- **Runtime config**: `LN2_CONFIG_FILE` env var → JSON (see `references/ln2_config.sample.json`)
- **GUI config**: `~/.ln2agent/config.yaml` (yaml_path, actor_id, api_key, language, theme, ai settings)
- **Audit log**: `ln2_inventory_audit.jsonl` (JSONL with action/timestamp/actor_id/session_id/trace_id)
- **Backups**: `ln2_inventory_backups/` (timestamped, auto-rotated)

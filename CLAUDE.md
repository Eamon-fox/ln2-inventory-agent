# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Environment Setup

```bash
source /analysis4/software/miniconda3/etc/profile.d/conda.sh && conda activate /analysis4/fanym/conda/envs/bio-py
```

All commands (python, pytest, etc.) must run inside `bio-py`. Do not use system python.

## Build & Run

```bash
# Install (single dependency)
pip install pyyaml

# GUI (requires PySide6)
pip install PySide6
python app_gui/main.py

# AI Agent (requires DEEPSEEK_API_KEY)
python app_gui/main.py

# Windows packaging
pyinstaller ln2_inventory.spec
```

## Testing

```bash
# All tests
pytest tests/

# Single test file
pytest tests/test_tool_api.py -v

# Single test
pytest tests/test_tool_api.py::TestToolAddEntry::test_basic_add -v

# GUI tests (need PySide6)
pytest tests/test_gui_panels.py -v
```

No mocking framework required 鈥?tests use real YAML in temp directories.

## Architecture

Four-layer design with a single unified API (`lib/tool_api.py`) shared by all three frontends:

```
GUI (app_gui/)  鈹€鈹尖攢鈹€鈻? lib/tool_api.py  鈹€鈹€鈻? lib/{yaml_ops,validators,operations,takeout_parser}
Agent (agent/)  鈹€鈹?          鈹?                             鈹?
                             鈻?                             鈻?
                      Standard result:               lib/config.py
                      {ok, result, error_code, message}
```

### Key modules

- **`lib/tool_api.py`** 鈥?13 tool functions (add, takeout, batch_takeout, query, search, stats, recommend, rollback, etc.). Every write goes through validate 鈫?backup 鈫?write 鈫?audit.
- **`lib/config.py`** 鈥?Runtime configuration with priority: built-in defaults 鈫?`LN2_CONFIG_FILE` env JSON 鈫?PyInstaller frozen detection. Exports `YAML_PATH`, `BOX_RANGE`, `POSITION_RANGE`, etc.
- **`lib/yaml_ops.py`** 鈥?YAML I/O with atomic backup-before-write and JSONL audit logging.
- **`lib/validators.py`** 鈥?Date/box/position validation, position-conflict and duplicate-ID checks.
- **`lib/takeout_parser.py`** 鈥?Chinese/English action normalization (鍙栧嚭/takeout, 绉诲姩/move).
- **`agent/react_agent.py`** 鈥?ReAct loop: LLM call 鈫?tool dispatch (parallel via ThreadPoolExecutor) 鈫?observation 鈫?repeat until max_steps or direct answer.
- **`agent/tool_runner.py`** 鈥?Dispatches named tool calls to `tool_api`, with plan-stashing for write operations (human approval required in GUI).
- **`app_gui/tool_bridge.py`** 鈥?Adapter stamping GUI metadata (actor_id) onto tool_api calls.
- **`app_gui/ui/ai_panel.py`** 鈥?Chat widget with streaming markdown re-rendering and tool progress display.
- **`app_gui/ui/overview_panel.py`** 鈥?9x9 grid visualization per box, multi-select for batch operations.
- **`app_gui/ui/operations_panel.py`** 鈥?Forms for add/takeout/move, plan staging/execution/undo, export (CSV/HTML).

### Data model

Single YAML file (`ln2_inventory.yaml`): `inventory[]` records with `id`, `cell_line`, `short_name`, `box`, `position`, `frozen_at`, `thaw_events[]`, plus `meta.box_layout`. Default grid is 9x9 (positions 1-81) across boxes 1-5.

### GUI panel communication (Qt signals)

- OverviewPanel 鈫?OperationsPanel: `plan_items_requested`, `request_prefill`, `data_loaded`
- OperationsPanel 鈫?OverviewPanel: `operation_completed`
- AIPanel 鈫?OperationsPanel: `plan_items_staged`, `operation_completed`

### i18n

Translation files at `app_gui/i18n/translations/{en,zh-CN}.json`. Use `tr("key.subkey")` throughout GUI code.

## Configuration

- **Runtime config**: `LN2_CONFIG_FILE` env var 鈫?JSON (see `references/ln2_config.sample.json`)
- **GUI config**: `~/.ln2agent/config.yaml` (yaml_path, actor_id, api_key, language, theme, ai settings)
- **Audit log**: `ln2_inventory_audit.jsonl` (JSONL with action/timestamp/actor_id/session_id/trace_id)
- **Backups**: `ln2_inventory_backups/` (timestamped, auto-rotated)


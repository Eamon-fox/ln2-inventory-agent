# LN2 Inventory Agent

[English](README.md) | [简体中文](README.zh-CN.md)

> Liquid nitrogen tank inventory management for frozen cell/tube samples, with a desktop GUI, AI copilot, and a unified Python Tool API.

## Highlights

- **One tube = one record** -- tube-level tracking with position-accurate storage
- **Single YAML file** as the source of truth, human-readable and version-control friendly
- **Three frontends, one API** -- Desktop GUI, AI Copilot, and Python library all share `lib/tool_api.py`
- **AI Copilot** with ReAct agent (DeepSeek / Zhipu GLM) embedded in the GUI
- **Write safety** -- every mutation goes through validate -> backup -> write -> audit
- **Bilingual** -- full English and Simplified Chinese UI and thaw-action normalization
- **9x9 grid visualization** per box with color-coded occupancy
- **Plan staging** -- AI-proposed write operations require human approval before execution

## Quick Start

```bash
# 1. Install core dependency
pip install pyyaml mistune

# 2. Copy the sample data (or start with an empty inventory)
cp demo/ln2_inventory.demo.yaml ln2_inventory.yaml

# 3. Launch the GUI
pip install PySide6
python app_gui/main.py
```

The app reads `ln2_inventory.yaml` from the current working directory by default. No other configuration is required.

## Features

### Inventory Management

- Add, edit, query, and search frozen tube records
- Thaw / takeout / discard / move operations (single and batch)
- Position-conflict detection and empty-slot listing
- Smart position recommendations (consecutive, same-row strategies)
- Timeline and statistics views
- CSV and HTML export

### AI Copilot

- Natural language interface for all inventory operations
- ReAct agent loop with native tool calling
- Streaming responses with thinking/reasoning display
- Write operations are staged, not executed directly -- human must confirm

### Data Safety

- Automatic timestamped backups before every write (keeps last 200)
- Append-only JSONL audit log with actor, session, and trace IDs
- Integrity validation on every write and rollback
- One-click rollback to any previous backup
- Capacity warnings when boxes or the tank are nearly full

### GUI Features

- Three-column layout: Overview | Operations | AI Copilot
- 9x9 grid visualization per box with multi-select
- Dark, light, and auto (system) themes
- Internationalization (English, Simplified Chinese)
- Drag-and-drop and keyboard shortcuts
- Settings dialog for data path, AI provider, language, theme, and custom fields

## Architecture

### Four-Layer Design

```
┌─────────────────────────────────────────────────────┐
│                    Frontends                         │
│  ┌───────────┐  ┌───────────┐  ┌─────────────────┐  │
│  │  Desktop   │  │    AI     │  │  Python Library  │  │
│  │    GUI     │  │  Copilot  │  │   (direct call)  │  │
│  │ (PySide6)  │  │  (ReAct)  │  │                  │  │
│  └─────┬─────┘  └─────┬─────┘  └────────┬─────────┘  │
│        │              │                  │            │
│        ▼              ▼                  ▼            │
│  ┌─────────────────────────────────────────────────┐  │
│  │           Unified Tool API (lib/tool_api.py)    │  │
│  │     18 tool functions, standard result format   │  │
│  └──────────────────────┬──────────────────────────┘  │
│                         │                             │
│  ┌──────────────────────▼──────────────────────────┐  │
│  │              Core Library (lib/)                 │  │
│  │  yaml_ops · validators · operations · config    │  │
│  │  thaw_parser · custom_fields · position_fmt     │  │
│  └──────────────────────┬──────────────────────────┘  │
│                         │                             │
│                         ▼                             │
│              ln2_inventory.yaml (data)                │
│              ln2_inventory_audit.jsonl (audit)        │
│              ln2_inventory_backups/ (backups)         │
└─────────────────────────────────────────────────────┘
```

### Unified Tool API

Every tool function returns a standard result dict:

```python
{
    "ok": True,           # or False
    "result": { ... },    # payload on success
    "error_code": "...",  # machine-readable error key on failure
    "message": "...",     # human-readable message on failure
}
```

### Data Flow (Write Operations)

```
User/Agent action
    │
    ▼
Validate input (dates, boxes, positions, conflicts)
    │
    ▼
Create timestamped backup
    │
    ▼
Write updated YAML
    │
    ▼
Append audit event to JSONL log
    │
    ▼
Emit capacity warnings (if thresholds exceeded)
```

## Data Model

### YAML Structure

All data lives in a single YAML file with two top-level keys:

```yaml
meta:
  box_layout:
    rows: 9
    cols: 9
    box_count: 5          # number of boxes (default 5)
    box_numbers: [1,2,3,4,5]
  custom_fields:          # optional user-defined fields
    - key: plasmid_name
      label: Plasmid Name
      type: str
    - key: plasmid_id
      label: Plasmid ID
      type: str

inventory:
  - id: 1
    parent_cell_line: NCCIT
    short_name: NCCIT_ctrl_A
    plasmid_name: pLenti-empty
    plasmid_id: p0001
    box: 1
    positions: [1]
    frozen_at: '2026-02-01'
    note: baseline control clone
    thaw_events: null
```

### Tube-Level Model

Each `inventory[]` record represents one physical tube:

| Field | Type | Description |
|---|---|---|
| `id` | int | Auto-incremented unique ID |
| `parent_cell_line` | str | Parent cell line name (e.g. K562, HeLa) |
| `short_name` | str | Short descriptive name for the tube |
| `box` | int | Box number (default 1-5) |
| `positions` | list[int] | Position(s) in the box grid (usually length 1) |
| `frozen_at` | str | Freeze date (YYYY-MM-DD) |
| `note` | str | Free-text notes |
| `thaw_events` | list | History of thaw/takeout/discard/move events |

Additional fields (e.g. `plasmid_name`, `plasmid_id`) can be added via `meta.custom_fields`.

### Thaw Events

Each thaw event records an action on a tube:

```yaml
thaw_events:
  - date: '2026-01-28'
    action: thaw          # thaw | takeout | discard | move
    positions: [17]
    note: recovery culture
```

Actions are bilingual -- Chinese and English inputs are normalized automatically:

| English | Chinese | Meaning |
|---|---|---|
| `thaw` | 复苏 | Thaw for culture recovery |
| `takeout` | 取出 | Take out for use |
| `discard` | 扔掉 / 丢掉 | Discard the tube |
| `move` | 移动 / 整理 | Move to a different position or box |

### Custom Fields

Define additional fields in `meta.custom_fields`:

```yaml
meta:
  custom_fields:
    - key: plasmid_name
      label: Plasmid Name
      type: str           # str | int | float | date
      required: false
      default: null
```

Custom fields appear in the GUI forms and are searchable by the AI copilot. Structural fields (`id`, `box`, `positions`, `frozen_at`, `thaw_events`, `cell_line`) cannot be overridden.

## Tool API Reference

### Write Tools

| Tool | Description | Key Parameters |
|---|---|---|
| `tool_add_entry` | Add a new frozen tube record | `box`, `positions`, `frozen_at`, `fields` |
| `tool_edit_entry` | Edit metadata fields of an existing record | `record_id`, `fields` |
| `tool_record_thaw` | Record a single thaw/takeout/discard/move | `record_id`, `position`, `date_str`, `action`, `to_position`, `to_box` |
| `tool_batch_thaw` | Batch thaw/takeout/discard/move operations | `entries`, `date_str`, `action`, `note` |
| `tool_rollback` | Rollback to a previous backup | `backup_path`, `dry_run` |
| `tool_adjust_box_count` | Add or remove boxes | `operation` (add/remove), `count`, `box` |

All write tools accept `dry_run=True` to preview changes without writing, and `actor_context` for audit attribution.

### Read Tools

| Tool | Description | Key Parameters |
|---|---|---|
| `tool_query_inventory` | Query records with field filters | `box`, `position`, `**field_filters` |
| `tool_search_records` | Fuzzy/exact/keyword search | `query`, `mode`, `max_results` |
| `tool_list_empty_positions` | List empty positions by box | `box` (optional) |
| `tool_recommend_positions` | Recommend positions for new samples | `count`, `box_preference`, `strategy` |
| `tool_recent_frozen` | Recently frozen records | `days`, `count` |
| `tool_query_thaw_events` | Query thaw events by date/action | `date`, `days`, `start_date`, `end_date`, `action` |
| `tool_collect_timeline` | Timeline events and summary stats | `days`, `all_history` |
| `tool_generate_stats` | Occupancy statistics and cell line breakdown | -- |
| `tool_list_backups` | List backup files (newest first) | -- |
| `tool_get_raw_entries` | Raw YAML entries by ID list | `ids` |
| `tool_export_inventory_csv` | Export inventory to CSV | `output_path` |

## GUI Guide

### Overview Panel

The left panel shows a 9x9 grid for each box:

- Color-coded cells: occupied (filled), empty (available), thawed/taken out (marked)
- Click a cell to select it; Ctrl+click or drag for multi-select
- Filter by box using the tab bar
- Selected positions are passed to the Operations panel for quick actions

### Operations Panel

The center panel provides forms for:

- **Add** -- freeze a new tube into a selected position
- **Thaw / Takeout / Discard** -- record an action on an existing tube
- **Move** -- relocate a tube to a different position or box
- **Batch operations** -- process multiple tubes at once
- **Plan queue** -- review, execute, or undo staged operations from the AI copilot
- **Export** -- save inventory as CSV or HTML
- **Rollback** -- revert to a previous backup

### AI Copilot Panel

The right panel is a chat interface:

- Type natural language requests (e.g. "add 3 tubes of K562 to box 2")
- The AI calls inventory tools, shows reasoning steps, and stages write operations
- Staged operations appear in the Plan queue for human review
- Supports streaming responses with expandable thinking blocks

### Settings

Access via the gear icon or menu:

- **Data**: inventory YAML file path
- **AI**: provider (DeepSeek / Zhipu), model, API key, max steps, thinking toggle, custom prompt
- **User**: actor ID (for audit logs), language, theme
- **Fields**: manage custom fields (add, edit, delete, reorder)

## AI Copilot

### Supported Providers

| Provider | Default Model | API Key Env Var | Base URL |
|---|---|---|---|
| DeepSeek | `deepseek-chat` | `DEEPSEEK_API_KEY` | `https://api.deepseek.com` |
| Zhipu GLM | `glm-5` | `ZHIPUAI_API_KEY` | `https://open.bigmodel.cn/api/paas/v4` |

Configure via the Settings dialog or environment variables. The provider and model can be changed at runtime.

### How It Works

The AI copilot uses a ReAct (Reason + Act) agent loop:

1. User sends a natural language message
2. LLM reasons about the request and decides which tools to call
3. Tool calls are dispatched (read tools execute immediately; write tools are staged)
4. Tool results are fed back to the LLM as observations
5. LLM generates the next action or a final answer
6. Loop repeats until the agent answers or reaches `max_steps` (default 12)

### Plan Staging

Write operations from the AI copilot are never executed directly. Instead:

1. The AI stages the operation into the Plan queue
2. The user reviews the staged plan in the Operations panel
3. The user clicks "Execute" to apply, or "Remove" to discard
4. Executed operations can be undone via rollback

This ensures humans always have final control over data mutations.

## Configuration

### Runtime Config (`LN2_CONFIG_FILE`)

Set the `LN2_CONFIG_FILE` environment variable to point to a JSON file:

```bash
export LN2_CONFIG_FILE=/path/to/config.json
```

```json
{
  "yaml_path": "./ln2_inventory.yaml",
  "schema": {
    "box_range": [1, 5],
    "position_range": [1, 81]
  },
  "safety": {
    "backup_dir_name": "ln2_inventory_backups",
    "backup_keep_count": 200,
    "audit_log_file": "ln2_inventory_audit.jsonl",
    "total_empty_warning_threshold": 20,
    "box_empty_warning_threshold": 5,
    "yaml_size_warning_mb": 5
  }
}
```

### GUI Config (`~/.ln2agent/config.yaml`)

The GUI stores its settings in `~/.ln2agent/config.yaml`:

```yaml
yaml_path: /path/to/ln2_inventory.yaml
api_keys:
  deepseek: sk-...
  zhipu: ...
language: en          # en | zh-CN
theme: dark           # dark | light | auto
ai:
  provider: deepseek  # deepseek | zhipu
  model: deepseek-chat
  max_steps: 12
  thinking_enabled: true
  custom_prompt: ""
```

### Environment Variables

| Variable | Description |
|---|---|
| `LN2_CONFIG_FILE` | Path to runtime config JSON |
| `DEEPSEEK_API_KEY` | DeepSeek API key |
| `DEEPSEEK_MODEL` | DeepSeek model override |
| `DEEPSEEK_BASE_URL` | DeepSeek API base URL override |
| `ZHIPUAI_API_KEY` | Zhipu GLM API key |

## Backup & Audit

### Automatic Backups

- Created before every write operation
- Stored in `ln2_inventory_backups/` next to the YAML file
- Named `ln2_inventory.yaml.YYYYMMDD-HHMMSS.bak`
- Auto-rotated: keeps the most recent 200 backups (configurable)

### JSONL Audit Log

Every write operation appends an event to `ln2_inventory_audit.jsonl`:

```json
{
  "timestamp": "2026-02-14T10:30:00",
  "action": "add_entry",
  "actor_type": "human",
  "actor_id": "human",
  "channel": "gui",
  "session_id": "session-20260214103000-a1b2c3d4",
  "trace_id": "trace-...",
  "tool_name": "tool_add_entry",
  "status": "success",
  "before": { "record_count": 26, "total_occupied": 26 },
  "after": { "record_count": 27, "total_occupied": 27 },
  "changed_ids": { "added": [27], "removed": [], "updated": [] }
}
```

### Rollback

- Rollback to the latest backup or a specific backup file
- A pre-rollback snapshot is always created first (so you can undo the undo)
- The target backup is validated for integrity before restoring
- Available from the GUI Operations panel or via `tool_rollback`

## Internationalization

The GUI supports English and Simplified Chinese. Translation files are at:

```
app_gui/i18n/translations/
├── en.json
└── zh-CN.json
```

Switch language in Settings. A restart is required for the change to take effect.

Thaw actions are also bilingual -- the system accepts both Chinese (复苏, 取出, 扔掉, 移动) and English (thaw, takeout, discard, move) inputs and normalizes them internally.

## Testing

```bash
# Run all tests
pytest tests/

# Run a specific test file
pytest tests/test_tool_api.py -v

# Run a single test
pytest tests/test_tool_api.py::TestToolAddEntry::test_basic_add -v

# GUI tests (requires PySide6)
pytest tests/test_gui_panels.py -v
```

Tests use real YAML files in temporary directories -- no mocking framework required.

## Packaging (Windows EXE)

### PyInstaller

```bash
pip install pyinstaller
pyinstaller ln2_inventory.spec
```

The spec file produces a one-directory build in `dist/`.

### Inno Setup Installer

An Inno Setup script is provided for creating a Windows installer:

```
installer/windows/LN2InventoryAgent.iss
```

Build the installer:

```bat
"C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer\windows\LN2InventoryAgent.iss
```

A helper script is also available: `installer/windows/build_installer.bat`

## Project Structure

```
ln2-inventory-agent/
├── lib/                        # Core library
│   ├── tool_api.py             # Unified Tool API (18 tool functions)
│   ├── yaml_ops.py             # YAML I/O, backup, audit logging
│   ├── validators.py           # Date/box/position validation
│   ├── operations.py           # Record lookup, ID generation, conflict checks
│   ├── thaw_parser.py          # Bilingual action normalization
│   ├── config.py               # Runtime configuration
│   ├── custom_fields.py        # Custom field definitions
│   ├── position_fmt.py         # Box/position formatting
│   ├── csv_export.py           # CSV export
│   ├── plan_item_factory.py    # Plan item builders
│   └── plan_store.py           # Plan storage
│
├── agent/                      # AI agent runtime
│   ├── react_agent.py          # ReAct loop implementation
│   ├── llm_client.py           # LLM client (DeepSeek, Zhipu)
│   └── tool_runner.py          # Tool dispatcher with plan staging
│
├── app_gui/                    # Desktop GUI (PySide6)
│   ├── main.py                 # Application entry point
│   ├── gui_config.py           # GUI configuration manager
│   ├── tool_bridge.py          # GUI-to-Tool-API adapter
│   ├── plan_model.py           # Plan queue model
│   ├── plan_executor.py        # Plan execution engine
│   ├── plan_gate.py            # Plan validation gate
│   ├── audit_guide.py          # Audit guide utilities
│   ├── i18n/                   # Internationalization
│   │   └── translations/
│   │       ├── en.json
│   │       └── zh-CN.json
│   ├── ui/
│   │   ├── overview_panel.py   # 9x9 grid visualization
│   │   ├── operations_panel.py # Forms and plan queue
│   │   ├── ai_panel.py         # AI chat interface
│   │   └── theme.py            # Dark/light/auto themes
│   └── assets/                 # Icons, default prompt
│
├── tests/                      # Unit tests (pytest)
├── demo/                       # Demo dataset
│   └── ln2_inventory.demo.yaml
├── installer/                  # Windows installer assets
│   └── windows/
│       ├── LN2InventoryAgent.iss
│       └── build_installer.bat
├── ln2_inventory.spec          # PyInstaller spec
├── requirements.txt            # Core dependencies
└── LICENSE                     # MIT License
```

## Requirements

- Python 3.8+
- PyYAML >= 5.0
- mistune >= 2.0
- PySide6 (for the GUI)
- DeepSeek or Zhipu API key (for the AI copilot)

## License

MIT License. Copyright (c) 2026 Yiming Fan.

---

## Support

If you find this project helpful, consider buying me a coffee :)

<img src="app_gui/assets/donate.png" width="200" alt="Donate QR Code" />

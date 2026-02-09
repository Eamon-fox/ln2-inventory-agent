# ln2-inventory

[English](README.md) | [简体中文](README.zh-CN.md)

> This project is first and foremost a **Claude Code agent skill** (see `SKILL.md`), and it can also run as a standalone Python CLI toolkit.

CLI toolkit for managing liquid nitrogen tank inventory. Tracks frozen cell line samples, thaw/takeout events, and storage positions across multiple boxes.

Data is stored in a single YAML file. All operations go through validated scripts — no manual YAML editing needed.

## Features

- **Add / query / search** frozen cell line records
- **Record thaw/takeout** (single or batch) with audit trail
- **Position management**: conflict detection, empty slot finder, smart position recommendations
- **Statistics**: per-box occupancy, cell line distribution, ASCII grid visualization
- **HTML dashboard**: auto-generated interactive overview
- **Backup & rollback**: automatic timestamped backups, one-click restore
- **Audit log**: JSONL log of all modifications
- **Fully configurable**: box count, grid size, position range, cell line whitelist — all via JSON config

## Quick Start

```bash
# 1. Install dependency
pip install pyyaml

# 2. Initialize with sample data (or start empty)
cp references/ln2_inventory.sample.yaml ln2_inventory.yaml

# 3. Try it
python scripts/stats.py --visual
python scripts/smart_search.py "K562" --keywords
python scripts/query_inventory.py --empty --box 1
python scripts/recommend_position.py --count 3
```

## Usage

### Add a frozen entry

```bash
python scripts/add_entry.py \
  --parent-cell-line "K562" \
  --short-name "RTCB-dTAG-clone12" \
  --box 1 --positions "30,31" \
  --frozen-at "2026-01-08" \
  --plasmid-name "pGEMT-N-RTCB-dTAG" \
  --note "homozygous clone"
```

### Record thaw / takeout

```bash
# Single
python scripts/record_thaw.py --id 5 --position 30 --date 2026-02-01

# Batch
python scripts/batch_thaw.py --entries "5:30,6:12" --date 2026-02-01 --action 复苏
```

### Query

```bash
python scripts/smart_search.py "dTAG" --keywords --raw
python scripts/query_recent.py --frozen --days 30
python scripts/query_thaw.py --days 7
python scripts/timeline.py --days 30 --summary
```

### Backup & rollback

```bash
python scripts/rollback.py --list
python scripts/rollback.py  # restore latest backup
```

## Configuration

By default, scripts look for `ln2_inventory.yaml` in the current directory. To customize paths or parameters, create a JSON config file and point to it:

```bash
export LN2_CONFIG_FILE=/path/to/my_config.json
```

See [`references/ln2_config.sample.json`](references/ln2_config.sample.json) for all available options:

- `yaml_path` — inventory file location
- `schema.box_range` — number of boxes (default `[1, 5]`)
- `schema.position_range` — positions per box (default `[1, 81]` for 9x9 grid)
- `schema.valid_cell_lines` — optional whitelist (empty = accept any)
- `schema.valid_actions` — thaw action types
- `safety.*` — backup rotation, warning thresholds

## Use as a Claude Code Skill

This project can also be installed as a [Claude Code](https://claude.ai/code) skill. See [`SKILL.md`](SKILL.md) for AI agent integration instructions.

## Project Structure

```
scripts/          # 16 CLI scripts (query, modify, utility)
lib/              # Shared library (config, YAML ops, validation)
tests/            # Unit tests (pytest)
references/       # Sample files and documentation
SKILL.md          # Claude Code skill definition
```

## Requirements

- Python 3.8+
- PyYAML

## License

MIT

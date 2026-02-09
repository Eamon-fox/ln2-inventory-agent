---
name: ln2-inventory
description: Manage liquid nitrogen tank inventory YAML. Use when adding frozen entries, recording thaw/取出, querying by cell line/plasmid/box/position, listing empty slots, viewing statistics, recommending positions, or validating ln2_inventory.yaml.
---

# LN2 Inventory Management

## Black Box Principle

**CRITICAL: The YAML file is a black box. ONLY use the provided Python scripts.**
- NEVER read/parse the YAML directly
- NEVER write custom code to access the YAML
- ALWAYS use script APIs for ALL operations

Scripts provide: input validation, auto-rebuild of occupancy metadata, conflict detection, consistent output.

## Environment

Configure via `LN2_CONFIG_FILE` environment variable pointing to a JSON config file,
or use defaults (scripts look for `ln2_inventory.yaml` in the current directory).

```bash
export LN2_CONFIG_FILE=/path/to/ln2_config.json
```

Template config: `references/ln2_config.sample.json`

## Core Operations

### Query

```bash
# Smart search (recommended)
smart_search.py "K562 dTAG" --keywords --raw

# Recent frozen entries
query_recent.py --frozen --days 30
query_recent.py --frozen --count 10 --verbose

# Thaw/takeout records
query_thaw.py --action 复苏                    # Today
query_thaw.py --days 7 --action 取出           # Last 7 days

# Operation timeline
timeline.py --days 30 --summary

# Empty slots
query_inventory.py --empty --box 3
```

### Add Entry

```bash
# Step 1: Get recommended positions
recommend_position.py --count 2

# Step 2: Add entry
add_entry.py \
  --parent-cell-line "K562" \
  --short-name "C-ABL1-dTAG-clone12" \
  --box 1 --positions "30,31" \
  --frozen-at "2026-01-08" \
  --plasmid-name "pGEMT-C-ABL1-dTAG" \
  --plasmid-id "p260101-1" \
  --note "纯合单克隆"
```

### Record Thaw

```bash
# Single (default action: 取出)
record_thaw.py --id 182 --position 23 --date 2026-01-08

# With action type and note
record_thaw.py --id 182 --position 23 --date 2026-01-08 --action 复苏 --note "复苏培养"

# Batch (recommended)
batch_thaw.py --entries "182:23,183:41,184:43" --date 2026-01-08
batch_thaw.py --entries "182:23,183:41" --date 2026-01-08 --action 复苏 --note "送人"
```

### Statistics

```bash
stats.py --visual
recommend_position.py --count 4
```

### Backup / Rollback

```bash
# List backups
rollback.py --list

# One-click rollback to latest backup
rollback.py

# Rollback to specific backup
rollback.py --backup "/path/to/ln2_inventory.yaml.20260209-010101.bak"
```

## Script Reference

See [references/scripts.md](references/scripts.md) for complete script documentation.

## Usage Examples

**User asks "最近冻过哪些细胞？取过哪些？"**

WRONG:
```python
import yaml
with open('ln2_inventory.yaml') as f:  # NEVER do this!
    data = yaml.safe_load(f)
```

CORRECT:
```bash
query_recent.py --frozen --days 30 --verbose
timeline.py --days 30 --verbose
query_thaw.py --days 7 --action 复苏
```

**Key principle: Trust script outputs. Never verify by reading YAML directly.**

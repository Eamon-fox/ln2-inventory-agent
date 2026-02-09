# Script Reference

## Query Scripts

| Script | Purpose | Key Parameters |
|--------|---------|----------------|
| `smart_search.py` | Intelligent search with raw data | `关键词`, `--raw`, `--keywords` |
| `query_recent.py` | Recent frozen entries | `--frozen`, `--days N`, `--count N` |
| `timeline.py` | Operation timeline | `--days N`, `--verbose`, `--summary` |
| `query_thaw.py` | Thaw/takeout records | `--date`, `--days`, `--action` |
| `query_inventory.py` | Query by field / empty slots | `--empty`, `--box N` |
| `search.py` | Basic global search | `关键词` |
| `show_raw.py` | Display raw YAML | `ID1 ID2 ...` |

## Modify Scripts

| Script | Purpose | Required Parameters |
|--------|---------|---------------------|
| `add_entry.py` | Add new frozen entry | `--parent-cell-line`, `--short-name`, `--box`, `--positions`, `--frozen-at` |
| `record_thaw.py` | Record single thaw | `--id`, `--position`, `--date` |
| `batch_thaw.py` | Batch thaw operations | `--entries`, `--date` |

Note: Use `--note` for special cases (e.g., "复苏", "送人", "扔掉")

## Utility Scripts

| Script | Purpose |
|--------|---------|
| `stats.py` | Statistics and visualization |
| `recommend_position.py` | Recommend storage positions |
| `validate.py` | Data validation |
| `check_conflicts.py` | Check position conflicts |
| `rollback.py` | One-click rollback to latest backup |

## Safety and Audit

- 每次写入 YAML 会自动创建备份目录：`ln2_inventory_backups/`
- 审计日志会追加到：`ln2_inventory_audit.jsonl`
- 一键回滚：`python rollback.py`
- 查看备份：`python rollback.py --list`

## Sample Files

- Inventory YAML sample: `references/ln2_inventory.sample.yaml`
- Config JSON sample: `references/ln2_config.sample.json`
- Env sample: `references/env.sample`

Use unified runtime config:

```bash
export LN2_CONFIG_FILE=/absolute/path/to/ln2_config.json
```

All key parameters can be configured in one file:

- paths: `yaml_path`, `python_path`, `scripts_dir`
- preview: `preview.host`, `preview.preferred_port`, `preview.max_port_scan`
- safety: `backup_keep_count`, `total_empty_warning_threshold`, `box_empty_warning_threshold`, `yaml_size_warning_mb`
- schema: `box_range`, `position_range`, `valid_actions`, `valid_cell_lines`

Quick check sample YAML:

```bash
python validate.py --yaml references/ln2_inventory.sample.yaml
```

## Common Parameters

- `--note` - Note for special cases (复苏, 送人, 扔掉, etc.)
- `--dry-run` - Preview mode (no modification)
- `--raw` - Display raw YAML data
- `--keywords` - Keyword search (AND logic)
- `--empty` - Show empty positions
- `--box <n>` - Specify box (1-5)
- `--visual` - Visual display mode
- `--verbose`, `-v` - Verbose output
- `--days <n>` - Query last N days
- `--count <n>` - Limit results
- `--summary`, `-s` - Show statistics

## Position Formats

- Single: `"30"`
- Multiple: `"30,31,32"`
- Range: `"30-32"` (equals "30,31,32")

## Valid Actions

`取出` | `复苏` | `扔掉`

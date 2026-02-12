"""Shared CLI rendering helpers for inventory records and raw YAML entries."""

from __future__ import annotations

from typing import Iterable, Mapping, Sequence

import yaml


def format_record_verbose(rec: Mapping[str, object]) -> str:
    """Format a record in verbose key-value layout."""
    pos = ",".join(str(p) for p in rec.get("positions") or [])
    lines = [
        f"{'ID':<15} {rec.get('id')}",
        f"{'细胞系':<15} {rec.get('parent_cell_line')}",
        f"{'简称':<15} {rec.get('short_name')}",
        f"{'质粒':<15} {rec.get('plasmid_name', 'N/A')}",
        f"{'质粒ID':<15} {rec.get('plasmid_id')}",
        f"{'盒子':<15} {rec.get('box')}",
        f"{'位置':<15} [{pos}]",
        f"{'冻存日期':<15} {rec.get('frozen_at')}",
    ]

    thaw_log = rec.get("thaw_log")
    if thaw_log:
        lines.append(f"{'取出记录':<15} {thaw_log}")
    note = rec.get("note")
    if note:
        lines.append(f"{'备注':<15} {note}")
    return "\n".join(lines)


def iter_entry_yaml_lines(entry: Mapping[str, object]) -> Iterable[str]:
    """Yield raw YAML lines for a single entry with adjusted indentation."""
    yaml_str = yaml.dump([dict(entry)], allow_unicode=True, default_flow_style=False, sort_keys=False)
    lines = yaml_str.split("\n")
    if lines and lines[0].startswith("- "):
        lines[0] = lines[0][2:]
    for line in lines:
        if not line:
            continue
        if line.startswith("  "):
            yield line[2:]
        else:
            yield line


def print_raw_entries(entries: Sequence[Mapping[str, object]]) -> None:
    """Print entries in canonical raw YAML view."""
    for index, entry in enumerate(entries):
        if index > 0:
            print()
        print(f"# === ID {entry['id']} ===")
        for line in iter_entry_yaml_lines(entry):
            print(line)

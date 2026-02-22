import pathlib
import re
from collections import defaultdict
from datetime import datetime, timedelta

import pandas as pd
import yaml


ROOT = pathlib.Path(__file__).resolve().parent
INPUT_DIR = ROOT / "inputs"
OUTPUT_DIR = ROOT / "output"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_YAML = OUTPUT_DIR / "ln2_inventory.yaml"
REPORT_MD = OUTPUT_DIR / "conversion_report.md"


def _clean_text(value):
    if pd.isna(value):
        return ""
    return str(value).strip()


def _parse_box(value):
    match = re.search(r"(\d+)", _clean_text(value))
    return int(match.group(1)) if match else None


def _parse_positions(value):
    tokens = []
    for token in re.split(r"[，,、;；/\s]+", _clean_text(value)):
        token = token.strip()
        if not token:
            continue
        match = re.search(r"(\d+)", token)
        if match:
            tokens.append(int(match.group(1)))
    return tokens


def _parse_date(value):
    if pd.isna(value):
        return None
    if isinstance(value, pd.Timestamp):
        return value.date().isoformat()

    text = str(value).strip()
    if not text:
        return None

    if re.fullmatch(r"\d+(?:\.\d+)?", text):
        serial = int(float(text))
        return (datetime(1899, 12, 30) + timedelta(days=serial)).date().isoformat()

    match = re.search(r"(20\d{2})[年/-](\d{1,2})[月/-](\d{1,2})", text)
    if match:
        return f"{int(match.group(1)):04d}-{int(match.group(2)):02d}-{int(match.group(3)):02d}"

    parsed = pd.to_datetime(text, errors="coerce")
    if pd.isna(parsed):
        return None
    return parsed.date().isoformat()


def _parse_takeout_events(value):
    text = _clean_text(value)
    if not text:
        return {}

    event_map = defaultdict(list)
    for year, month, day, position in re.findall(
        r"(20\d{2})年(\d{1,2})月(\d{1,2})日[^0-9]{0,16}?(\d+)号",
        text,
    ):
        date_text = f"{int(year):04d}-{int(month):02d}-{int(day):02d}"
        event_map[int(position)].append(date_text)
    return event_map


def main():
    source_xlsx = next(INPUT_DIR.glob("*.xlsx"))
    frame = pd.read_excel(str(source_xlsx), sheet_name="Sheet1", header=2)
    columns = list(frame.columns)
    frame = frame.rename(
        columns={
            columns[0]: "cell_line_raw",
            columns[1]: "short_name_raw",
            columns[2]: "plasmid_name_raw",
            columns[3]: "plasmid_id_raw",
            columns[4]: "box_raw",
            columns[5]: "positions_raw",
            columns[6]: "frozen_raw",
            columns[7]: "takeout_raw",
            columns[8]: "note_raw",
        }
    )
    frame = frame[frame["cell_line_raw"].notna()].copy()

    records = []
    parse_errors = []
    active_slots = {}
    conflicts = []
    next_id = 1

    for row_index, row in frame.iterrows():
        box = _parse_box(row.get("box_raw"))
        positions = _parse_positions(row.get("positions_raw"))
        frozen_at = _parse_date(row.get("frozen_raw"))
        takeout_map = _parse_takeout_events(row.get("takeout_raw"))

        if box is None:
            parse_errors.append(f"row {row_index + 1}: invalid box={row.get('box_raw')}")
            continue
        if not positions:
            parse_errors.append(f"row {row_index + 1}: no positions in {row.get('positions_raw')}")
            continue
        if not frozen_at:
            parse_errors.append(f"row {row_index + 1}: invalid frozen date={row.get('frozen_raw')}")
            continue

        cell_line = _clean_text(row.get("cell_line_raw")) or "Unknown"
        short_name = _clean_text(row.get("short_name_raw"))
        plasmid_name = _clean_text(row.get("plasmid_name_raw"))
        plasmid_id = _clean_text(row.get("plasmid_id_raw"))
        note = _clean_text(row.get("note_raw"))

        for position in positions:
            thaw_events = []
            for event_date in sorted(set(takeout_map.get(position, []))):
                thaw_events.append(
                    {
                        "action": "takeout",
                        "date": event_date,
                        "positions": [int(position)],
                    }
                )

            record = {
                "id": next_id,
                "box": int(box),
                "position": int(position),
                "frozen_at": frozen_at,
                "cell_line": cell_line,
                "short_name": short_name or None,
                "plasmid_name": plasmid_name or None,
                "plasmid_id": plasmid_id or None,
                "note": note or None,
                "thaw_events": thaw_events or None,
            }

            if not thaw_events:
                slot = (record["box"], record["position"])
                if slot in active_slots:
                    conflicts.append((slot, active_slots[slot], next_id))
                else:
                    active_slots[slot] = next_id

            records.append(record)
            next_id += 1

    max_box = max((rec["box"] for rec in records), default=5)
    payload = {
        "meta": {
            "box_layout": {
                "rows": 9,
                "cols": 9,
                "box_count": int(max_box),
                "indexing": "numeric",
            },
            "cell_line_required": True,
            "display_key": "short_name",
            "custom_fields": [
                {
                    "key": "plasmid_name",
                    "type": "str",
                    "label": "Plasmid Name",
                    "required": False,
                },
                {
                    "key": "plasmid_id",
                    "type": "str",
                    "label": "Plasmid ID",
                    "required": False,
                },
            ],
        },
        "inventory": records,
    }

    with open(OUTPUT_YAML, "w", encoding="utf-8") as handle:
        yaml.safe_dump(payload, handle, allow_unicode=True, sort_keys=False)

    active_count = sum(1 for rec in records if not rec.get("thaw_events"))
    consumed_count = len(records) - active_count
    report_lines = [
        "# Conversion Report",
        "",
        f"- Source file: {source_xlsx.name}",
        f"- Source rows (data rows): {len(frame)}",
        f"- Output records (tube-level): {len(records)}",
        f"- Active records: {active_count}",
        f"- Records with takeout history: {consumed_count}",
        f"- Parsing errors: {len(parse_errors)}",
        f"- Active slot conflicts: {len(conflicts)}",
        "",
    ]
    if parse_errors:
        report_lines.append("## Parsing Errors")
        report_lines.extend([f"- {item}" for item in parse_errors[:50]])
        report_lines.append("")
    if conflicts:
        report_lines.append("## Active Slot Conflicts")
        for (box, pos), first_id, second_id in conflicts[:50]:
            report_lines.append(
                f"- Box {box} Position {pos}: id={first_id} conflicts with id={second_id}"
            )
        report_lines.append("")

    with open(REPORT_MD, "w", encoding="utf-8") as handle:
        handle.write("\n".join(report_lines).rstrip() + "\n")

    print(f"OUTPUT_YAML={OUTPUT_YAML}")
    print(f"REPORT_MD={REPORT_MD}")
    print(f"RECORDS={len(records)}")
    print(f"ACTIVE_CONFLICTS={len(conflicts)}")
    print(f"PARSE_ERRORS={len(parse_errors)}")


if __name__ == "__main__":
    main()

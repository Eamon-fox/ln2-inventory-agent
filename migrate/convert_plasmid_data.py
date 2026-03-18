#!/usr/bin/env python3
"""
Convert plasmid Excel data to LN2 inventory YAML format.
Input: migrate/normalized/source/sheets/01_Sheet1.csv
Output: migrate/output/ln2_inventory.yaml
"""

import csv
import re
import yaml
from datetime import datetime
from pathlib import Path

def parse_date(date_str):
    """Convert YYYYMMDD to YYYY-MM-DD"""
    if not date_str or date_str == '-':
        return None
    try:
        # Handle integer or string
        date_str = str(date_str).strip()
        if len(date_str) == 8 and date_str.isdigit():
            return f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"
        return None
    except:
        return None

def extract_box_number(storage):
    """Extract box number from storage string like '1号盒子'"""
    if not storage or storage == '-':
        return None
    # Match Chinese pattern like "1号盒子", "2号盒子"
    match = re.search(r'(\d+)\s*号\s*盒', storage)
    if match:
        return int(match.group(1))
    # Also check for simple numbers
    if storage.isdigit():
        return int(storage)
    return None

def parse_positions(position_str):
    """Parse position string, can be single number or comma-separated list"""
    if not position_str or position_str == '-':
        return []
    
    positions = []
    # Remove quotes and whitespace
    pos_str = str(position_str).replace('"', '').strip()
    
    # Split by comma
    for part in pos_str.split(','):
        part = part.strip()
        if part and part.isdigit():
            positions.append(int(part))
    
    return positions

def main():
    csv_path = Path("normalized/source/sheets/01_Sheet1.csv")
    output_path = Path("output/ln2_inventory.yaml")
    
    # Read CSV
    records = []
    with open(csv_path, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            records.append(row)
    
    print(f"Read {len(records)} records from CSV")
    
    # Process records
    inventory = []
    record_id = 1
    
    for row in records:
        identifier = (row.get('Identifier') or '').strip()
        date_acquire = (row.get('DateOfAcquire') or '').strip()
        name = (row.get('Name') or '').strip()
        storage = (row.get('Storage') or '').strip()
        position = (row.get('Position') or '').strip()
        source = (row.get('Source') or '').strip()
        note = (row.get('Note') or '').strip()
        
        # Skip empty rows
        if identifier == '-' and name == '-':
            continue
        
        # Parse data
        frozen_at = parse_date(date_acquire)
        box = extract_box_number(storage)
        positions = parse_positions(position)
        
        # If no positions found, skip or set to null
        if not positions:
            positions = [None]
        
        # Combine source and note
        full_note = source
        if note and note != '-':
            if full_note:
                full_note += f" | {note}"
            else:
                full_note = note
        
        # Create one record per position
        for pos in positions:
            # Skip if no box number (e.g., "张咏妍", "杨乐" storage)
            if box is None:
                continue
                
            # Create inventory record
            record = {
                "id": record_id,
                "box": box,
                "position": pos,
                "frozen_at": frozen_at if frozen_at else "2022-01-01",  # Default if missing
                "cell_line": "Unknown",
                "short_name": identifier if identifier != '-' else name[:50],
                "note": full_note[:500] if full_note else "",
                "plasmid_name": name,
                "plasmid_id": identifier if identifier != '-' else f"p{record_id:06d}"
            }
            
            # Remove empty fields
            record = {k: v for k, v in record.items() if v not in (None, "", "-")}
            
            inventory.append(record)
            record_id += 1
    
    print(f"Generated {len(inventory)} inventory records")
    
    # Create YAML structure
    yaml_data = {
        "meta": {
            "box_layout": {
                "rows": 9,
                "cols": 9,
                "box_tags": {
                    "1": "1号盒子",
                    "2": "2号盒子",
                    "3": "3号盒子"
                }
            },
            "custom_fields": [
                {
                    "key": "plasmid_name",
                    "type": "string",
                    "label": "质粒名称",
                    "description": "质粒的完整名称"
                },
                {
                    "key": "plasmid_id",
                    "type": "string",
                    "label": "质粒ID",
                    "description": "质粒的唯一标识符"
                }
            ]
        },
        "inventory": inventory
    }
    
    # Write YAML
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        yaml.dump(yaml_data, f, allow_unicode=True, sort_keys=False, default_flow_style=False)
    
    print(f"Written to {output_path}")
    
    # Summary
    boxes = set(r["box"] for r in inventory)
    print(f"Boxes used: {sorted(boxes)}")
    print(f"Date range: {min(r['frozen_at'] for r in inventory)} to {max(r['frozen_at'] for r in inventory)}")

if __name__ == "__main__":
    main()
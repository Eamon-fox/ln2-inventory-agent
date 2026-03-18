#!/usr/bin/env python3
"""
Fix position conflicts in the inventory YAML.
"""

import yaml
from pathlib import Path

def main():
    yaml_path = Path("output/ln2_inventory.yaml")
    
    # Load YAML
    with open(yaml_path, 'r', encoding='utf-8') as f:
        data = yaml.safe_load(f)
    
    inventory = data['inventory']
    
    # Track occupied positions
    occupied = {}
    to_remove = []
    
    # First pass: find conflicts
    for i, record in enumerate(inventory):
        box = record['box']
        pos = record['position']
        
        if pos is None:
            continue
            
        key = (box, pos)
        if key in occupied:
            # Conflict found
            print(f"Conflict at Box {box} Position {pos}: IDs {occupied[key]} and {record['id']}")
            # Keep the first one, mark this one for removal
            to_remove.append(i)
        else:
            occupied[key] = record['id']
    
    # Remove duplicates (from end to start to preserve indices)
    for idx in sorted(to_remove, reverse=True):
        removed = inventory.pop(idx)
        print(f"Removed duplicate record ID {removed['id']} at Box {removed['box']} Position {removed['position']}")
    
    # Reassign IDs sequentially
    for i, record in enumerate(inventory, 1):
        record['id'] = i
    
    print(f"Removed {len(to_remove)} duplicate records")
    print(f"Total records after cleanup: {len(inventory)}")
    
    # Save back
    with open(yaml_path, 'w', encoding='utf-8') as f:
        yaml.dump(data, f, allow_unicode=True, sort_keys=False, default_flow_style=False)
    
    print(f"Saved to {yaml_path}")

if __name__ == "__main__":
    main()
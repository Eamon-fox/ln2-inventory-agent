#!/usr/bin/env python3
"""
Update cell_line field to Type with new options.
"""

import yaml
from pathlib import Path

def main():
    yaml_path = Path("../inventories/FYM_Plasmids_2026/inventory.yaml")
    
    # Load YAML
    with open(yaml_path, 'r', encoding='utf-8') as f:
        data = yaml.safe_load(f)
    
    # Update meta: rename cell_line to Type and update options
    for i, field in enumerate(data['meta']['custom_fields']):
        if field['key'] == 'cell_line':
            # Rename to Type
            field['key'] = 'type'
            field['label'] = 'Type'
            field['default'] = 'plasmid'
            # Update options
            field['options'] = ['plasmid', '基因组DNA', '其他']
            break
    
    # Update inventory records
    genomic_dna_keywords = ['genomic DNA', '基因组DNA', 'gDNA']
    for record in data['inventory']:
        # Check if this is genomic DNA
        is_genomic_dna = False
        short_name = record.get('short_name', '').lower()
        plasmid_name = record.get('plasmid_name', '').lower()
        
        for keyword in genomic_dna_keywords:
            if keyword in short_name or keyword in plasmid_name:
                is_genomic_dna = True
                break
        
        # Rename field and set value
        if 'cell_line' in record:
            if is_genomic_dna:
                record['type'] = '基因组DNA'
            else:
                record['type'] = 'plasmid'
            del record['cell_line']
    
    print(f"Updated {len(data['inventory'])} records")
    print("Field renamed: cell_line → type")
    print("Options: plasmid, 基因组DNA, 其他")
    
    # Save back
    with open(yaml_path, 'w', encoding='utf-8') as f:
        yaml.dump(data, f, allow_unicode=True, sort_keys=False, default_flow_style=False)
    
    print(f"Saved to {yaml_path}")

if __name__ == "__main__":
    main()
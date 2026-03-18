#!/usr/bin/env python3
"""
批量修复inventory.yaml文件，为所有记录添加cell_line字段
"""

import yaml
import re
from pathlib import Path

def infer_cell_line(record):
    """根据short_name推断细胞系类型"""
    short_name = record.get('short_name', '').lower()
    
    # 检查明显的细胞系类型
    if 'nccit' in short_name:
        return 'NCCIT'
    elif '293t' in short_name or '293' in short_name:
        return 'HEK293T'
    elif 'hela' in short_name:
        return 'HeLa'
    elif 'k562' in short_name:
        return 'K562'
    elif 'hepg2' in short_name:
        return 'HepG2'
    elif 'huh7' in short_name:
        return 'Huh7'
    elif 'jurkat' in short_name:
        return 'Jurkat'
    elif 'mcf7' in short_name:
        return 'MCF7'
    elif 'a549' in short_name:
        return 'A549'
    elif 'u2os' in short_name:
        return 'U2OS'
    elif 'hct116' in short_name:
        return 'HCT116'
    elif 'sw480' in short_name:
        return 'SW480'
    elif 'sw620' in short_name:
        return 'SW620'
    elif 'ht29' in short_name:
        return 'HT29'
    elif 'dld1' in short_name:
        return 'DLD1'
    elif 'rko' in short_name:
        return 'RKO'
    elif 'pc3' in short_name:
        return 'PC3'
    elif 'du145' in short_name:
        return 'DU145'
    elif 'lncap' in short_name:
        return 'LNCaP'
    elif 'a375' in short_name:
        return 'A375'
    elif 'sk-mel-28' in short_name:
        return 'SK-MEL-28'
    elif 'raji' in short_name:
        return 'Raji'
    elif 'thp-1' in short_name:
        return 'THP-1'
    elif 'mda-mb-231' in short_name:
        return 'MDA-MB-231'
    elif 'mesc' in short_name:
        return 'mESC'
    
    # 检查WT前缀
    if short_name.startswith('wt '):
        if 'nccit' in short_name:
            return 'NCCIT'
        elif '293' in short_name:
            return 'HEK293T'
        elif 'hela' in short_name:
            return 'HeLa'
    
    # 检查常见的工程细胞系（大多数是K562背景）
    # Cas13, Csm, StitchR, dTAG等通常是K562
    cas_keywords = ['cas13', 'csm', 'stitchr', 'dtag', 'apex2', 'ms2', 'gfp', 'bfp', 'mcherry', 'ha-', 'teton', 'pb-', 'l1', 'ef1a']
    for keyword in cas_keywords:
        if keyword in short_name:
            return 'K562'
    
    # 默认返回Unknown
    return 'Unknown'

def main():
    # 读取原始文件
    inventory_path = Path('../inventories/FYM_LN2_2026/inventory.yaml')
    with open(inventory_path, 'r', encoding='utf-8') as f:
        data = yaml.safe_load(f)
    
    print(f"总记录数: {len(data.get('inventory', []))}")
    
    # 修复每个记录
    fixed_count = 0
    for record in data.get('inventory', []):
        if 'cell_line' not in record:
            cell_line = infer_cell_line(record)
            record['cell_line'] = cell_line
            fixed_count += 1
            print(f"修复记录 {record.get('id')}: {record.get('short_name')} -> {cell_line}")
    
    print(f"\n修复了 {fixed_count} 个记录")
    
    # 写入修复后的文件
    output_path = Path('fixed_inventory.yaml')
    with open(output_path, 'w', encoding='utf-8') as f:
        yaml.dump(data, f, allow_unicode=True, sort_keys=False)
    
    print(f"修复后的文件已保存到: {output_path}")
    
    # 验证修复
    print("\n验证修复结果:")
    cell_line_counts = {}
    for record in data.get('inventory', []):
        cell_line = record.get('cell_line', 'Unknown')
        cell_line_counts[cell_line] = cell_line_counts.get(cell_line, 0) + 1
    
    for cell_line, count in sorted(cell_line_counts.items()):
        print(f"  {cell_line}: {count}")

if __name__ == '__main__':
    main()
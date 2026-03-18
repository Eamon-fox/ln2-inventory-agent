#!/usr/bin/env python3
"""
转换质粒索引表CSV为LN2库存YAML格式
"""

import csv
import re
import yaml
from datetime import datetime
from pathlib import Path

def parse_storage(storage_str):
    """解析Storage列，返回box编号"""
    if not storage_str or storage_str.strip() == '':
        return None
    
    storage = storage_str.strip()
    
    # 匹配数字盒子
    match = re.search(r'(\d+)号盒子', storage)
    if match:
        return int(match.group(1))
    
    # 特殊标签映射
    if storage == '张咏妍':
        return 4
    elif storage == '杨乐':
        return 5
    
    return None

def parse_positions(position_str):
    """解析Position列，返回位置整数列表"""
    if not position_str or position_str.strip() == '':
        return []
    
    positions = []
    # 处理逗号分隔的多个位置
    for part in position_str.split(','):
        part = part.strip()
        if part and part.isdigit():
            positions.append(int(part))
    
    return positions

def parse_date(date_str):
    """解析DateOfAcquire列，返回YYYY-MM-DD格式"""
    if not date_str or date_str.strip() == '' or date_str == '-':
        return '2023-01-01'  # 默认日期
    
    date_str = str(date_str).strip()
    
    # 如果是YYYYMMDD格式
    if date_str.isdigit() and len(date_str) == 8:
        try:
            dt = datetime.strptime(date_str, '%Y%m%d')
            return dt.strftime('%Y-%m-%d')
        except ValueError:
            return '2023-01-01'
    
    return '2023-01-01'

def convert_csv_to_inventory(csv_path, existing_inventory_path=None):
    """转换CSV为库存记录，创建全新数据集"""
    records = []
    next_id = 1
    position_map = {}  # 跟踪已占用的位置 (box, position) -> record_id
    
    with open(csv_path, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row_idx, row in enumerate(reader, 1):
            # 检查行是否为空
            if not any(row.values()):
                continue
            
            identifier = (row.get('Identifier') or '').strip()
            date_str = (row.get('DateOfAcquire') or '').strip()
            name = (row.get('Name') or '').strip()
            storage = (row.get('Storage') or '').strip()
            position_str = (row.get('Position') or '').strip()
            source = (row.get('Source') or '').strip()
            note = (row.get('Note') or '').strip()
            
            # 解析box
            box = parse_storage(storage)
            if box is None:
                print(f"警告：第{row_idx}行无法解析Storage: '{storage}'，跳过")
                continue
            
            # 解析位置
            positions = parse_positions(position_str)
            if not positions:
                print(f"警告：第{row_idx}行没有有效位置: '{position_str}'，跳过")
                continue
            
            # 解析日期
            frozen_at = parse_date(date_str)
            
            # 处理plasmid_id
            plasmid_id = identifier if identifier != '-' else ''
            
            # 为每个位置创建一条记录，检查位置冲突
            for pos in positions:
                key = (box, pos)
                if key in position_map:
                    print(f"警告：第{row_idx}行位置冲突，盒子{box}位置{pos}已占用（记录{position_map[key]}），跳过")
                    continue
                
                record = {
                    'id': next_id,
                    'box': box,
                    'position': pos,
                    'frozen_at': frozen_at,
                    'plasmid_id': plasmid_id,
                    'plasmid_name': name,
                    'source': source
                }
                
                if note:
                    record['note'] = note
                
                records.append(record)
                position_map[key] = next_id
                next_id += 1
    
    return records

def main():
    base_dir = Path(__file__).parent.parent
    csv_path = base_dir / 'migrate/normalized/source/sheets/01_Sheet1.csv'
    existing_inventory_path = base_dir / 'inventories/plasmid_test/inventory.yaml'
    output_path = base_dir / 'migrate/output/ln2_inventory.yaml'
    
    print(f"读取CSV文件: {csv_path}")
    records = convert_csv_to_inventory(csv_path, existing_inventory_path)
    print(f"转换完成，共生成 {len(records)} 条记录")
    
    # 读取现有库存的meta部分
    with open(existing_inventory_path, 'r', encoding='utf-8') as f:
        existing_data = yaml.safe_load(f)
    
    # 创建新的库存数据
    inventory_data = {
        'meta': existing_data['meta'],
        'inventory': records
    }
    
    # 写入YAML文件
    with open(output_path, 'w', encoding='utf-8') as f:
        yaml.dump(inventory_data, f, allow_unicode=True, sort_keys=False)
    
    print(f"YAML文件已保存: {output_path}")
    
    # 统计信息
    boxes = set(record['box'] for record in records)
    print(f"涉及盒子: {sorted(boxes)}")
    
    # 检查位置冲突
    position_map = {}
    conflicts = []
    for record in records:
        key = (record['box'], record['position'])
        if key in position_map:
            conflicts.append((key, position_map[key], record['id']))
        else:
            position_map[key] = record['id']
    
    if conflicts:
        print(f"警告：发现 {len(conflicts)} 个位置冲突:")
        for (box, pos), id1, id2 in conflicts:
            print(f"  盒子{box}位置{pos}: 记录{id1}和记录{id2}")
    else:
        print("位置检查：无冲突")

if __name__ == '__main__':
    main()
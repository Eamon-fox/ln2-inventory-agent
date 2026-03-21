#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import csv
import json
import re
from datetime import datetime, timedelta

# Excel序列号转日期
def excel_date_to_iso(excel_date):
    if not excel_date or excel_date == '冻存时间':
        return None
    try:
        excel_num = int(excel_date)
        base_date = datetime(1899, 12, 30)
        result_date = base_date + timedelta(days=excel_num)
        return result_date.strftime('%Y-%m-%d')
    except:
        return None

# 解析位置
def parse_positions(pos_str):
    if not pos_str or pos_str == '盒内序号':
        return []
    try:
        positions = []
        for p in str(pos_str).split(','):
            p = p.strip().strip('"')
            if p.isdigit():
                positions.append(int(p))
        return positions
    except:
        return []

# 解析盒子编号
def parse_box(box_str):
    if not box_str or box_str == '冻存盒':
        return None
    match = re.search(r'(\d+)', str(box_str))
    if match:
        return int(match.group(1))
    return None

# 读取CSV
records = []
record_id = 1
position_map = {}  # 用于检测位置冲突

with open('migrate/normalized/source/sheets/01_Sheet1.csv', 'r', encoding='utf-8-sig') as f:
    reader = csv.reader(f)
    rows = list(reader)

# 跳过前3行（标题和说明）
data_rows = rows[3:]

for row in data_rows:
    if len(row) < 7:
        continue
    
    cell_line = row[0].strip() if len(row) > 0 else ''
    short_name = row[1].strip() if len(row) > 1 else ''
    plasmid_name = row[2].strip() if len(row) > 2 else ''
    plasmid_id = row[3].strip() if len(row) > 3 else ''
    box_str = row[4].strip() if len(row) > 4 else ''
    pos_str = row[5].strip() if len(row) > 5 else ''
    frozen_date = row[6].strip() if len(row) > 6 else ''
    takeout_str = row[7].strip() if len(row) > 7 else ''
    note = row[8].strip() if len(row) > 8 else ''
    
    # 跳过空行或标题行
    if not cell_line or cell_line == '父细胞系':
        continue
    
    # 解析盒子
    box = parse_box(box_str)
    if box is None:
        continue
    
    # 解析位置
    positions = parse_positions(pos_str)
    if not positions:
        continue
    
    # 解析冻存日期
    frozen_at = excel_date_to_iso(frozen_date)
    if not frozen_at:
        continue
    
    # 构建Sample字段：细胞系 + 简称
    sample_parts = [cell_line]
    if short_name and short_name != 'none':
        sample_parts.append(short_name)
    sample = ' - '.join(sample_parts)
    
    # 构建备注信息
    note_parts = []
    if plasmid_name and plasmid_name != 'none':
        note_parts.append(f"质粒: {plasmid_name}")
    if plasmid_id and plasmid_id != 'none':
        note_parts.append(f"质粒编号: {plasmid_id}")
    if note:
        note_parts.append(note)
    if takeout_str and takeout_str != '取出时间':
        note_parts.append(f"取出记录: {takeout_str}")
    
    combined_note = '; '.join(note_parts) if note_parts else ''
    
    # 为每个位置创建记录
    for pos in positions:
        # 检查位置冲突
        pos_key = f"{box}-{pos}"
        if pos_key in position_map:
            # 如果位置已存在，合并信息到备注
            existing_record = position_map[pos_key]
            if combined_note:
                existing_record['note'] = f"{existing_record.get('note', '')}\n[重复] {sample}, {frozen_at}: {combined_note}".strip()
            continue
        
        record = {
            'id': record_id,
            'box': box,
            'position': pos,
            'frozen_at': frozen_at,
            'Sample': sample,
            'note': combined_note
        }
        
        position_map[pos_key] = record
        records.append(record)
        record_id += 1

# 构建YAML结构
yaml_data = {
    'meta': {
        'box_layout': {
            'rows': 9,
            'cols': 9,
            'box_count': 5,
            'box_numbers': [1, 2, 3, 4, 5],
            'box_tags': {
                '1': '杂物间液氮罐4号架子-1号盒',
                '2': '杂物间液氮罐4号架子-2号盒',
                '3': '杂物间液氮罐4号架子-3号盒',
                '4': '杂物间液氮罐4号架子-4号盒',
                '5': '杂物间液氮罐4号架子-5号盒'
            }
        },
        'custom_fields': [
            {'key': 'Sample', 'type': 'str', 'required': True, 'default': 'Unknown'},
            {'key': 'note', 'type': 'str', 'multiline': True}
        ]
    },
    'inventory': records
}

# 写入JSON（用于检查）
with open('migrate/output/inventory_preview.json', 'w', encoding='utf-8') as f:
    json.dump(yaml_data, f, ensure_ascii=False, indent=2)

print(f'Total records: {len(records)}')
print(f'Preview saved to migrate/output/inventory_preview.json')

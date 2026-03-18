import yaml
import re
from collections import defaultdict

try:
    from migrate.path_context import DEFAULT_SOURCE_SHEET, OUTPUT_YAML
except ImportError:
    from path_context import DEFAULT_SOURCE_SHEET, OUTPUT_YAML

# 读取生成的YAML文件
with OUTPUT_YAML.open('r', encoding='utf-8') as f:
    data = yaml.safe_load(f)

# 分析位置冲突
position_map = defaultdict(list)  # (box, position) -> [record_ids]
null_position_records = []

for record in data['inventory']:
    box = record['box']
    position = record['position']
    record_id = record['id']
    
    if position is None:
        null_position_records.append(record_id)
    else:
        position_map[(box, position)].append(record_id)

# 找出冲突的位置
conflicts = {}
for (box, position), record_ids in position_map.items():
    if len(record_ids) > 1:
        conflicts[(box, position)] = record_ids

print("位置冲突分析:")
for (box, position), record_ids in conflicts.items():
    print(f"  盒子{box} 位置{position}: 记录 {record_ids}")

print(f"\nposition为null的记录: {null_position_records}")

# 检查盒子3的具体冲突
print("\n盒子3的冲突记录详情:")
box3_conflicts = {k: v for k, v in conflicts.items() if k[0] == 3}
for (box, position), record_ids in box3_conflicts.items():
    print(f"  位置{position}: 记录 {record_ids}")
    for record_id in record_ids:
        record = next(r for r in data['inventory'] if r['id'] == record_id)
        print(f"    ID{record_id}: {record['identifier']} - {record['name']}")

# 检查源数据中盒子3的记录
print("\n检查源数据中盒子3的记录...")
import csv
with DEFAULT_SOURCE_SHEET.open('r', encoding='utf-8-sig') as f:
    reader = csv.DictReader(f)
    box3_records = []
    for row in reader:
        if '3号盒子' in row['Storage']:
            box3_records.append(row)

print(f"源数据中盒子3的记录数: {len(box3_records)}")

# 检查是否有重复的标识符
identifiers = [r['Identifier'] for r in box3_records if r['Identifier']]
dup_identifiers = [id for id in identifiers if identifiers.count(id) > 1]
if dup_identifiers:
    print(f"重复的标识符: {set(dup_identifiers)}")
    
    # 显示重复记录详情
    for dup_id in set(dup_identifiers):
        print(f"\n标识符 '{dup_id}' 的重复记录:")
        for r in box3_records:
            if r['Identifier'] == dup_id:
                print(f"  Storage: {r['Storage']}, Position: {r['Position']}, Name: {r['Name']}")
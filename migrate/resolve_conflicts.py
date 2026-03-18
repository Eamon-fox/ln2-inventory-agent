import yaml
import re
from collections import defaultdict

try:
    from migrate.path_context import OUTPUT_YAML, output_path
except ImportError:
    from path_context import OUTPUT_YAML, output_path

# 读取生成的YAML文件
with OUTPUT_YAML.open('r', encoding='utf-8') as f:
    data = yaml.safe_load(f)

# 找出盒子3的所有占用位置
box3_positions = set()
box3_records = []

for record in data['inventory']:
    if record['box'] == 3 and record['position'] is not None:
        box3_positions.add(record['position'])
        box3_records.append(record)

print(f"盒子3已占用位置数: {len(box3_positions)}")
print(f"盒子3总记录数: {len(box3_records)}")

# 找出盒子3的空位置（假设9x9=81个位置）
all_positions = set(range(1, 82))  # 1-81
empty_positions = sorted(list(all_positions - box3_positions))
print(f"盒子3空位置数: {len(empty_positions)}")
print(f"前20个空位置: {empty_positions[:20]}")

# 找出冲突的记录
conflict_records = []
position_counts = defaultdict(list)

for record in data['inventory']:
    if record['box'] == 3 and record['position'] is not None:
        position_counts[record['position']].append(record)

for position, records in position_counts.items():
    if len(records) > 1:
        print(f"\n位置{position}有{len(records)}个记录:")
        for r in records:
            print(f"  ID{r['id']}: {r['identifier']} - {r['name'][:50]}...")
        conflict_records.extend(records[1:])  # 保留第一个，其他需要重新分配

print(f"\n需要重新分配的冲突记录数: {len(conflict_records)}")

# 为冲突记录分配新位置
if conflict_records and empty_positions:
    # 按ID排序，确保一致性
    conflict_records.sort(key=lambda x: x['id'])
    
    # 分配前N个空位置
    for i, record in enumerate(conflict_records):
        if i < len(empty_positions):
            old_position = record['position']
            new_position = empty_positions[i]
            record['position'] = new_position
            
            # 在note中添加位置变更说明
            if 'note' not in record:
                record['note'] = ''
            position_note = f"原位置: {old_position} (与其他质粒共享)，已重新分配到位置{new_position}"
            if record['note']:
                record['note'] = position_note + "\n" + record['note']
            else:
                record['note'] = position_note
            
            print(f"ID{record['id']}: 从位置{old_position}移动到{new_position}")

# 处理position为null的记录（添加虚拟takeout事件）
null_position_ids = [67, 68, 69]
for record in data['inventory']:
    if record['id'] in null_position_ids:
        # 这些是个人存储或未分配记录，添加takeout事件
        record['thaw_events'] = [{
            'date': record['frozen_at'] if record['frozen_at'] else '2024-01-01',
            'action': 'takeout',
            'positions': [None]
        }]
        print(f"ID{record['id']}: 添加takeout事件")

# 保存修复后的文件
with output_path('ln2_inventory_fixed.yaml').open('w', encoding='utf-8') as f:
    yaml.dump(data, f, allow_unicode=True, sort_keys=False, default_flow_style=False)

print(f"\n修复完成，保存为: {output_path('ln2_inventory_fixed.yaml')}")

# 验证修复
print("\n修复后验证:")
box3_positions_fixed = set()
position_counts_fixed = defaultdict(int)

for record in data['inventory']:
    if record['box'] == 3 and record['position'] is not None:
        box3_positions_fixed.add(record['position'])
        position_counts_fixed[record['position']] += 1

# 检查是否还有冲突
conflicts_fixed = [pos for pos, count in position_counts_fixed.items() if count > 1]
if conflicts_fixed:
    print(f"仍有冲突的位置: {conflicts_fixed}")
else:
    print("所有位置冲突已解决")

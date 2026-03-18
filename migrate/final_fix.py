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

print("=== 全面冲突解决 ===")

# 1. 首先处理所有盒子的位置冲突
all_conflicts = defaultdict(list)
all_positions_used = defaultdict(set)  # box -> set of positions

for record in data['inventory']:
    if record['position'] is not None:
        box = record['box']
        position = record['position']
        all_positions_used[box].add(position)
        all_conflicts[(box, position)].append(record['id'])

# 找出所有冲突
conflict_items = {k: v for k, v in all_conflicts.items() if len(v) > 1}
print(f"总冲突数: {len(conflict_items)}")

# 2. 为每个盒子找出空位置
def find_empty_positions(box, max_position=81):
    used = all_positions_used.get(box, set())
    all_pos = set(range(1, max_position + 1))
    empty = sorted(list(all_pos - used))
    return empty

# 3. 解决冲突的策略：
# a. 首先尝试在同一个盒子内重新分配
# b. 如果不行，尝试分配到其他盒子（盒子5"未分配"或盒子6"个人存储"）
# c. 最后考虑标记为已取出

# 收集需要处理的冲突记录
records_to_fix = []
for (box, position), record_ids in conflict_items.items():
    # 保留第一个记录，其他需要处理
    for record_id in record_ids[1:]:
        record = next(r for r in data['inventory'] if r['id'] == record_id)
        records_to_fix.append({
            'record': record,
            'old_box': box,
            'old_position': position,
            'reason': f"与记录{record_ids[0]}冲突"
        })

print(f"需要处理的冲突记录数: {len(records_to_fix)}")

# 4. 处理冲突记录
for item in records_to_fix:
    record = item['record']
    old_box = item['old_box']
    old_position = item['old_position']
    
    # 首先尝试在同一个盒子找空位置
    empty_in_same_box = find_empty_positions(old_box)
    
    if empty_in_same_box:
        new_position = empty_in_same_box[0]
        record['position'] = new_position
        all_positions_used[old_box].add(new_position)
        
        # 更新note
        note_add = f"原位置: {old_position} (位置冲突)，已重新分配到位置{new_position}"
        if 'note' not in record or not record['note']:
            record['note'] = note_add
        else:
            record['note'] = note_add + "\n" + record['note']
        
        print(f"ID{record['id']}: 盒子{old_box}内从位置{old_position}移动到{new_position}")
    
    else:
        # 没有空位置，尝试分配到盒子5（未分配）
        empty_in_box5 = find_empty_positions(5)
        if empty_in_box5:
            new_box = 5
            new_position = empty_in_box5[0]
            record['box'] = new_box
            record['position'] = new_position
            all_positions_used[new_box].add(new_position)
            
            note_add = f"原位置: 盒子{old_box}位置{old_position} (位置冲突且盒子已满)，已分配到盒子5(未分配)位置{new_position}"
            if 'note' not in record or not record['note']:
                record['note'] = note_add
            else:
                record['note'] = note_add + "\n" + record['note']
            
            print(f"ID{record['id']}: 从盒子{old_box}位置{old_position}移动到盒子5位置{new_position}")
        
        else:
            # 盒子5也满了，标记为已取出
            record['position'] = None
            if 'frozen_at' in record and record['frozen_at']:
                takeout_date = record['frozen_at']
            else:
                takeout_date = '2024-01-01'
            
            record['thaw_events'] = [{
                'date': takeout_date,
                'action': 'takeout',
                'positions': [old_position]
            }]
            
            note_add = f"原位置: 盒子{old_box}位置{old_position} (位置冲突且无空位)，已标记为已取出"
            if 'note' not in record or not record['note']:
                record['note'] = note_add
            else:
                record['note'] = note_add + "\n" + record['note']
            
            print(f"ID{record['id']}: 盒子{old_box}位置{old_position}冲突，标记为已取出")

# 5. 处理原本position为null的记录（个人存储/未分配）
null_position_records = [r for r in data['inventory'] if r['position'] is None and 'thaw_events' not in r]
for record in null_position_records:
    if 'frozen_at' in record and record['frozen_at']:
        takeout_date = record['frozen_at']
    else:
        takeout_date = '2024-01-01'
    
    record['thaw_events'] = [{
        'date': takeout_date,
        'action': 'takeout',
        'positions': [None]
    }]
    
    print(f"ID{record['id']}: position为null，添加takeout事件")

# 6. 验证修复
print("\n=== 修复后验证 ===")
final_conflicts = defaultdict(list)
for record in data['inventory']:
    if record['position'] is not None:
        key = (record['box'], record['position'])
        final_conflicts[key].append(record['id'])

remaining_conflicts = {k: v for k, v in final_conflicts.items() if len(v) > 1}
if remaining_conflicts:
    print(f"仍有冲突: {len(remaining_conflicts)}个")
    for (box, pos), ids in remaining_conflicts.items():
        print(f"  盒子{box}位置{pos}: {ids}")
else:
    print("所有位置冲突已解决！")

# 7. 保存最终文件
with output_path('ln2_inventory_final.yaml').open('w', encoding='utf-8') as f:
    yaml.dump(data, f, allow_unicode=True, sort_keys=False, default_flow_style=False)

print(f"\n最终文件保存为: {output_path('ln2_inventory_final.yaml')}")

# 统计
box_counts = defaultdict(int)
for record in data['inventory']:
    box_counts[record['box']] += 1

print("\n各盒子记录分布:")
for box in sorted(box_counts.keys()):
    count = box_counts[box]
    box_name = {
        1: '1号盒子',
        2: '2号盒子',
        3: '3号盒子',
        5: '未分配',
        6: '个人存储'
    }.get(box, f'盒子{box}')
    print(f"  {box_name}: {count}条记录")

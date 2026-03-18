import yaml

try:
    from migrate.path_context import OUTPUT_YAML, output_path
except ImportError:
    from path_context import OUTPUT_YAML, output_path

# 读取YAML文件
with OUTPUT_YAML.open('r', encoding='utf-8') as f:
    data = yaml.safe_load(f)

print("修复thaw_events中的position问题...")

# 找出有thaw_events且position为None的记录
fixed_count = 0
for record in data['inventory']:
    if 'thaw_events' in record and record['position'] is None:
        # 这些是已取出的记录，thaw_events中的position应该是原来的位置
        # 但从note中提取原位置比较困难，我们设为1作为占位符
        for event in record['thaw_events']:
            if 'positions' in event:
                # 将None替换为1（占位符）
                event['positions'] = [1]
                fixed_count += 1

print(f"修复了 {fixed_count} 个thaw_events记录")

# 另外，对于个人存储和未分配记录，如果position为null但没有thaw_events
# 我们可以直接给它们分配一个位置，而不是添加thaw_events
for record in data['inventory']:
    if record['position'] is None and 'thaw_events' not in record:
        # 根据盒子分配位置
        if record['box'] == 5:  # 未分配
            # 盒子5中找空位置
            used_positions = set()
            for r in data['inventory']:
                if r['box'] == 5 and r['position'] is not None:
                    used_positions.add(r['position'])
            
            # 找第一个空位置
            for pos in range(1, 82):
                if pos not in used_positions:
                    record['position'] = pos
                    print(f"ID{record['id']}: 未分配记录分配到盒子5位置{pos}")
                    break
        
        elif record['box'] == 6:  # 个人存储
            # 盒子6中找空位置
            used_positions = set()
            for r in data['inventory']:
                if r['box'] == 6 and r['position'] is not None:
                    used_positions.add(r['position'])
            
            # 找第一个空位置
            for pos in range(1, 82):
                if pos not in used_positions:
                    record['position'] = pos
                    print(f"ID{record['id']}: 个人存储记录分配到盒子6位置{pos}")
                    break

# 保存修复后的文件
with output_path('ln2_inventory_fixed_thaw.yaml').open('w', encoding='utf-8') as f:
    yaml.dump(data, f, allow_unicode=True, sort_keys=False, default_flow_style=False)

print(f"保存为: {output_path('ln2_inventory_fixed_thaw.yaml')}")

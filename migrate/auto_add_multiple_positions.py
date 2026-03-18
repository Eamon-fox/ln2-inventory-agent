import csv
import yaml
from collections import defaultdict

print("=== 自动为多个位置的质粒创建缺失记录 ===")

# 1. 读取原始Excel数据
excel_data = []
with open('normalized/source/sheets/01_Sheet1.csv', 'r', encoding='utf-8-sig') as f:
    reader = csv.DictReader(f)
    for row in reader:
        excel_data.append(row)

print(f"Excel总记录数: {len(excel_data)}")

# 2. 读取当前库存数据
with open('../inventories/plasmid_test/inventory.yaml', 'r', encoding='utf-8') as f:
    inventory_data = yaml.safe_load(f)

# 3. 按标识符分组Excel数据
excel_by_identifier = defaultdict(list)
for row in excel_data:
    identifier = row['Identifier'].strip()
    if identifier:
        excel_by_identifier[identifier].append(row)

# 4. 按标识符分组库存数据
inventory_by_identifier = defaultdict(list)
for record in inventory_data['inventory']:
    identifier = record.get('identifier', '').strip()
    if identifier:
        inventory_by_identifier[identifier].append(record)

# 5. 分析每个有多个位置的质粒
print("\n=== 分析有多个位置的质粒 ===")
multiple_position_plasmids = []

for identifier, excel_rows in excel_by_identifier.items():
    # 收集所有位置
    all_positions = set()
    for row in excel_rows:
        positions = row['Position'].strip()
        if positions:
            for pos in positions.split(','):
                pos = pos.strip()
                if '(' in pos:
                    pos = pos.split('(')[0].strip()
                if pos and pos.isdigit():
                    all_positions.add(int(pos))
    
    if len(all_positions) > 1:
        # 获取库存中的位置
        inventory_positions = set()
        for record in inventory_by_identifier.get(identifier, []):
            if record.get('position'):
                inventory_positions.add(int(record['position']))
        
        # 检查缺失的位置
        missing_positions = all_positions - inventory_positions
        
        if missing_positions:
            # 获取质粒信息（取第一个Excel行作为参考）
            ref_row = excel_rows[0]
            multiple_position_plasmids.append({
                'identifier': identifier,
                'name': ref_row['Name'],
                'date': ref_row['DateOfAcquire'],
                'source': ref_row['Source'],
                'storage': ref_row['Storage'],
                'all_positions': sorted(all_positions),
                'inventory_positions': sorted(inventory_positions),
                'missing_positions': sorted(missing_positions),
                'note': ref_row['Note']
            })

print(f"发现 {len(multiple_position_plasmids)} 个有多个位置且缺失记录的质粒")

# 6. 生成add操作的脚本
print("\n=== 生成add操作脚本 ===")
add_operations = []

for plasmid in multiple_position_plasmids:
    # 确定盒子编号
    box = None
    if '1号盒子' in plasmid['storage']:
        box = 1
    elif '2号盒子' in plasmid['storage']:
        box = 2
    elif '3号盒子' in plasmid['storage']:
        box = 3
    elif '4号盒子' in plasmid['storage']:
        box = 4
    elif '5号盒子' in plasmid['storage']:
        box = 5
    
    if not box:
        print(f"⚠️  无法确定盒子编号: {plasmid['identifier']} - {plasmid['storage']}")
        continue
    
    # 处理日期
    date_str = plasmid['date']
    frozen_at = None
    
    if date_str and date_str != '-' and date_str != '':
        # 尝试解析日期格式
        if len(date_str) == 8 and date_str.isdigit():
            # YYYYMMDD格式
            frozen_at = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"
        else:
            # 使用默认日期
            frozen_at = "2023-01-01"
    else:
        # 使用默认日期
        frozen_at = "2023-01-01"
    
    # 为每个缺失位置创建操作
    for position in plasmid['missing_positions']:
        # 检查位置是否已被占用
        position_occupied = False
        for record in inventory_data['inventory']:
            if record.get('box') == box and record.get('position') == str(position):
                position_occupied = True
                break
        
        if position_occupied:
            print(f"⚠️  位置 {box}:{position} 已被占用，跳过 {plasmid['identifier']}")
            continue
        
        # 创建操作
        operation = {
            'box': box,
            'position': position,
            'frozen_at': frozen_at,
            'identifier': plasmid['identifier'],
            'name': plasmid['name'],
            'source': plasmid['source'],
            'note': f"备份位置（原位置{plasmid['inventory_positions'][0] if plasmid['inventory_positions'] else '未知'}）"
        }
        add_operations.append(operation)

print(f"需要创建 {len(add_operations)} 个add操作")

def _escape_single_quotes(value):
    return str(value).replace("\\", "\\\\").replace("'", "\\'")

# 7. 生成Python脚本
script_content = """# 自动生成的add操作脚本
# 为多个位置的质粒创建缺失记录

from ln2_inventory_agent.tools import add_entry

print("开始执行add操作...")

# 操作列表
operations = [
"""

for i, op in enumerate(add_operations):
    name = _escape_single_quotes(op['name'])
    source = _escape_single_quotes(op['source'])
    note = _escape_single_quotes(op['note'])
    script_content += f"""    # 操作 {i+1}: {op['identifier']} @ 盒子{op['box']}:{op['position']}
    {{
        'box': {op['box']},
        'positions': [{op['position']}],
        'frozen_at': '{op['frozen_at']}',
        'fields': {{
            'identifier': '{op['identifier']}',
            'name': '{name}',
            'source': '{source}',
            'note': '{note}'
        }}
    }},
"""

script_content += """]

# 执行操作
for i, op in enumerate(operations):
    print(f"执行操作 {i+1}/{len(operations)}: {op['fields']['identifier']} @ 盒子{op['box']}:{op['positions'][0]}")
    try:
        result = add_entry(
            box=op['box'],
            positions=op['positions'],
            frozen_at=op['frozen_at'],
            fields=op['fields']
        )
        if result.get('ok'):
            print(f"  ✅ 成功")
        else:
            print(f"  ❌ 失败: {result.get('error_code', '未知错误')}")
    except Exception as e:
        print(f"  ❌ 异常: {e}")

print("所有操作执行完成！")
"""

# 8. 保存脚本
with open('migrate/execute_add_operations.py', 'w', encoding='utf-8') as f:
    f.write(script_content)

print(f"\n✅ 已生成执行脚本: migrate/execute_add_operations.py")
print(f"   包含 {len(add_operations)} 个add操作")

# 9. 生成简化的手动操作指南
print("\n=== 手动操作指南 ===")
print("如果不想运行脚本，可以手动执行以下add_entry调用:")

for i, op in enumerate(add_operations[:10]):  # 只显示前10个作为示例
    print(f"\n# 操作 {i+1}: {op['identifier']}")
    print(f"add_entry(")
    print(f"    box={op['box']},")
    print(f"    positions=[{op['position']}],")
    print(f"    frozen_at='{op['frozen_at']}',")
    print(f"    fields={{")
    print(f"        'identifier': '{op['identifier']}',")
    print(f"        'name': '{op['name'][:50]}...',")
    print(f"        'source': '{op['source'][:30]}...',")
    print(f"        'note': '{op['note']}'")
    print(f"    }}")
    print(f")")

if len(add_operations) > 10:
    print(f"\n... 还有 {len(add_operations) - 10} 个操作")

# 10. 统计信息
print("\n=== 统计信息 ===")
print(f"总质粒数: {len(multiple_position_plasmids)}")
print(f"总操作数: {len(add_operations)}")

# 按盒子统计
box_stats = defaultdict(int)
for op in add_operations:
    box_stats[op['box']] += 1

print("\n按盒子统计:")
for box in sorted(box_stats.keys()):
    print(f"  盒子{box}: {box_stats[box]} 个操作")

print("\n✅ 脚本生成完成！请运行 migrate/execute_add_operations.py 执行所有操作")

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

# 3. 分析每个有多个位置的质粒
print("\n=== 分析有多个位置的质粒 ===")

# 收集所有有多个位置的质粒
multiple_position_plasmids = []

for row in excel_data:
    identifier = row['Identifier'].strip()
    positions = row['Position'].strip()
    
    if not positions or not identifier:
        continue
    
    # 解析所有位置
    all_positions = []
    for pos in positions.split(','):
        pos = pos.strip()
        if '(' in pos:
            pos = pos.split('(')[0].strip()
        if pos and pos.isdigit():
            all_positions.append(int(pos))
    
    if len(all_positions) > 1:
        # 获取库存中的位置
        inventory_positions = []
        for record in inventory_data['inventory']:
            if record.get('identifier') == identifier and record.get('position'):
                inventory_positions.append(int(record['position']))
        
        # 检查缺失的位置
        missing_positions = [p for p in all_positions if p not in inventory_positions]
        
        if missing_positions:
            # 确定盒子编号
            box = None
            storage = row['Storage']
            if '1号盒子' in storage:
                box = 1
            elif '2号盒子' in storage:
                box = 2
            elif '3号盒子' in storage:
                box = 3
            elif '4号盒子' in storage:
                box = 4
            elif '5号盒子' in storage:
                box = 5
            
            if box:
                multiple_position_plasmids.append({
                    'identifier': identifier,
                    'name': row['Name'],
                    'date': row['DateOfAcquire'],
                    'source': row['Source'],
                    'note': row['Note'],
                    'box': box,
                    'all_positions': all_positions,
                    'inventory_positions': inventory_positions,
                    'missing_positions': missing_positions
                })

print(f"发现 {len(multiple_position_plasmids)} 个有多个位置且缺失记录的质粒")

# 4. 生成add操作
print("\n=== 生成add操作 ===")
add_operations = []

for plasmid in multiple_position_plasmids:
    # 处理日期
    date_str = plasmid['date']
    frozen_at = None
    
    if date_str and date_str != '-' and date_str != '':
        if len(date_str) == 8 and date_str.isdigit():
            frozen_at = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"
        else:
            frozen_at = "2023-01-01"
    else:
        frozen_at = "2023-01-01"
    
    # 为每个缺失位置创建操作
    for position in plasmid['missing_positions']:
        # 检查位置是否已被占用
        position_occupied = False
        for record in inventory_data['inventory']:
            if record.get('box') == plasmid['box'] and record.get('position') == str(position):
                position_occupied = True
                break
        
        if position_occupied:
            print(f"⚠️  位置 {plasmid['box']}:{position} 已被占用，跳过 {plasmid['identifier']}")
            continue
        
        # 创建操作
        operation = {
            'box': plasmid['box'],
            'position': position,
            'frozen_at': frozen_at,
            'identifier': plasmid['identifier'],
            'name': plasmid['name'],
            'source': plasmid['source'],
            'note': f"备份位置（原位置{plasmid['inventory_positions'][0] if plasmid['inventory_positions'] else '未知'}）"
        }
        add_operations.append(operation)

print(f"需要创建 {len(add_operations)} 个add操作")

# 5. 生成Python脚本
print("\n=== 生成执行脚本 ===")

script_lines = [
    "# 自动生成的add操作脚本",
    "# 为多个位置的质粒创建缺失记录",
    "",
    "from ln2_inventory_agent.tools import add_entry",
    "",
    "print('开始执行add操作...')",
    "",
    "# 操作列表",
    "operations = ["
]

for i, op in enumerate(add_operations):
    # 转义字符串中的单引号
    name = str(op['name']).replace("'", "\\'") if op['name'] else ''
    source = str(op['source']).replace("'", "\\'") if op['source'] else ''
    note = str(op['note']).replace("'", "\\'") if op['note'] else ''
    
    script_lines.append(f"    # 操作 {i+1}: {op['identifier']} @ 盒子{op['box']}:{op['position']}")
    script_lines.append("    {")
    script_lines.append(f"        'box': {op['box']},")
    script_lines.append(f"        'positions': [{op['position']}],")
    script_lines.append(f"        'frozen_at': '{op['frozen_at']}',")
    script_lines.append("        'fields': {")
    script_lines.append(f"            'identifier': '{op['identifier']}',")
    script_lines.append(f"            'name': '{name}',")
    script_lines.append(f"            'source': '{source}',")
    script_lines.append(f"            'note': '{note}'")
    script_lines.append("        }")
    script_lines.append("    },")

script_lines.append("]")
script_lines.append("")
script_lines.append("# 执行操作")
script_lines.append("for i, op in enumerate(operations):")
script_lines.append(f"    print(f'执行操作 {{i+1}}/{{len(operations)}}: {{op[\"fields\"][\"identifier\"]}} @ 盒子{{op[\"box\"]}}:{{op[\"positions\"][0]}}')")
script_lines.append("    try:")
script_lines.append("        result = add_entry(")
script_lines.append("            box=op['box'],")
script_lines.append("            positions=op['positions'],")
script_lines.append("            frozen_at=op['frozen_at'],")
script_lines.append("            fields=op['fields']")
script_lines.append("        )")
script_lines.append("        if result.get('ok'):")
script_lines.append("            print('  ✅ 成功')")
script_lines.append("        else:")
script_lines.append("            print(f'  ❌ 失败: {{result.get(\"error_code\", \"未知错误\")}}')")
script_lines.append("    except Exception as e:")
script_lines.append("        print(f'  ❌ 异常: {{e}}')")
script_lines.append("")
script_lines.append("print('所有操作执行完成！')")

# 保存脚本
with open('execute_add_operations.py', 'w', encoding='utf-8') as f:
    f.write('\n'.join(script_lines))

print(f"✅ 已生成执行脚本: migrate/execute_add_operations.py")
print(f"   包含 {len(add_operations)} 个add操作")

# 6. 统计信息
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

# 7. 显示前几个操作作为示例
print("\n=== 操作示例（前5个）===")
for i, op in enumerate(add_operations[:5]):
    print(f"\n操作 {i+1}:")
    print(f"  add_entry(")
    print(f"    box={op['box']},")
    print(f"    positions=[{op['position']}],")
    print(f"    frozen_at='{op['frozen_at']}',")
    print(f"    fields={{")
    print(f"        'identifier': '{op['identifier']}',")
    print(f"        'name': '{op['name'][:30]}...',")
    print(f"        'source': '{op['source'][:30]}...',")
    print(f"        'note': '{op['note']}'")
    print(f"    }}")
    print(f"  )")

if len(add_operations) > 5:
    print(f"\n... 还有 {len(add_operations) - 5} 个操作")

print("\n✅ 脚本生成完成！请运行 migrate/execute_add_operations.py 执行所有操作")
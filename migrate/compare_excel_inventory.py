import csv
import yaml
from collections import defaultdict

print("=== 原始Excel数据与当前库存比对 ===")

# 1. 读取原始Excel数据（盒子3）
excel_data = []
with open('normalized/source/sheets/01_Sheet1.csv', 'r', encoding='utf-8-sig') as f:
    reader = csv.DictReader(f)
    for row in reader:
        if '3号盒子' in row['Storage']:
            excel_data.append(row)

print(f"原始Excel中盒子3的记录数: {len(excel_data)}")

# 2. 读取当前库存数据
with open('../inventories/plasmid_test/inventory.yaml', 'r', encoding='utf-8') as f:
    inventory_data = yaml.safe_load(f)

# 获取盒子3的库存记录
inventory_records = []
for record in inventory_data['inventory']:
    if record['box'] == 3:
        inventory_records.append(record)

print(f"当前库存中盒子3的记录数: {len(inventory_records)}")

# 3. 按位置建立映射
excel_by_position = defaultdict(list)
inventory_by_position = defaultdict(list)

for row in excel_data:
    positions = row['Position'].strip()
    if positions:
        # 处理多个位置的情况
        pos_list = []
        for pos in positions.split(','):
            pos = pos.strip()
            # 处理"20(已双酶切)"这种情况
            if '(' in pos:
                pos = pos.split('(')[0].strip()
            if pos and pos.isdigit():
                pos_list.append(int(pos))
        
        for pos in pos_list:
            excel_by_position[pos].append({
                'identifier': row['Identifier'],
                'name': row['Name'],
                'date': row['DateOfAcquire'],
                'source': row['Source'],
                'note': row['Note']
            })

for record in inventory_records:
    if record['position'] is not None:
        pos = int(record['position'])
        inventory_by_position[pos].append({
            'id': record['id'],
            'identifier': record.get('identifier', ''),
            'name': record.get('name', ''),
            'frozen_at': record.get('frozen_at', ''),
            'source': record.get('source', ''),
            'note': record.get('note', ''),
            'status': 'active' if record.get('position') else 'inactive'
        })

# 4. 比对每个位置
print("\n=== 位置比对结果 ===")
all_positions = set(list(excel_by_position.keys()) + list(inventory_by_position.keys()))

for pos in sorted(all_positions):
    excel_items = excel_by_position.get(pos, [])
    inventory_items = inventory_by_position.get(pos, [])
    
    print(f"\n位置 {pos}:")
    
    # Excel中的记录
    if excel_items:
        print(f"  Excel ({len(excel_items)}条):")
        for item in excel_items:
            print(f"    - {item['identifier']}: {item['name'][:50]}... (日期: {item['date']})")
    else:
        print(f"  Excel: 无记录")
    
    # 库存中的记录
    if inventory_items:
        print(f"  库存 ({len(inventory_items)}条):")
        for item in inventory_items:
            status = "活跃" if item['status'] == 'active' else "已取出"
            print(f"    - ID{item['id']}: {item['identifier']}: {item['name'][:50]}... (日期: {item['frozen_at']}, 状态: {status})")
    else:
        print(f"  库存: 无记录")
    
    # 检查一致性
    if len(excel_items) > 0 and len(inventory_items) > 0:
        # 检查标识符是否匹配
        excel_ids = {item['identifier'] for item in excel_items}
        inventory_ids = {item['identifier'] for item in inventory_items}
        
        if excel_ids == inventory_ids:
            print(f"  ✅ 标识符匹配")
        else:
            print(f"  ⚠️  标识符不匹配: Excel={excel_ids}, 库存={inventory_ids}")
    
    elif len(excel_items) > 0 and len(inventory_items) == 0:
        print(f"  ⚠️  Excel有记录但库存无记录")
    
    elif len(excel_items) == 0 and len(inventory_items) > 0:
        print(f"  ⚠️  库存有记录但Excel无记录")

# 5. 检查冲突位置（库存中多个活跃记录）
print("\n=== 冲突位置检查 ===")
conflict_positions = []
for pos, items in inventory_by_position.items():
    active_items = [item for item in items if item['status'] == 'active']
    if len(active_items) > 1:
        conflict_positions.append((pos, active_items))

if conflict_positions:
    print(f"发现 {len(conflict_positions)} 个冲突位置:")
    for pos, items in conflict_positions:
        print(f"  位置 {pos}:")
        for item in items:
            print(f"    - ID{item['id']}: {item['identifier']}")
else:
    print("✅ 无冲突位置")

# 6. 检查Excel中有但库存中没有的标识符
print("\n=== 缺失记录检查 ===")
excel_identifiers = set()
for items in excel_by_position.values():
    for item in items:
        excel_identifiers.add(item['identifier'])

inventory_identifiers = set()
for items in inventory_by_position.values():
    for item in items:
        inventory_identifiers.add(item['identifier'])

missing_in_excel = inventory_identifiers - excel_identifiers
missing_in_inventory = excel_identifiers - inventory_identifiers

if missing_in_excel:
    print(f"库存中有但Excel中无的标识符 ({len(missing_in_excel)}个):")
    for identifier in sorted(missing_in_excel):
        print(f"  - {identifier}")

if missing_in_inventory:
    print(f"Excel中有但库存中无的标识符 ({len(missing_in_inventory)}个):")
    for identifier in sorted(missing_in_inventory):
        print(f"  - {identifier}")

if not missing_in_excel and not missing_in_inventory:
    print("✅ 所有标识符都匹配")
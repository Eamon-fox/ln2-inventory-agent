import csv
import yaml

print("=== 检查所有有多个位置的质粒 ===")

# 读取原始Excel数据
with open('normalized/source/sheets/01_Sheet1.csv', 'r', encoding='utf-8-sig') as f:
    reader = csv.DictReader(f)
    rows = list(reader)

# 读取当前库存数据
with open('../inventories/plasmid_test/inventory.yaml', 'r', encoding='utf-8') as f:
    inventory_data = yaml.safe_load(f)

# 收集所有有多个位置的质粒
multiple_position_records = []

for row in rows:
    positions = row['Position'].strip()
    if positions and ',' in positions:
        # 检查是否有多个位置
        pos_list = []
        for pos in positions.split(','):
            pos = pos.strip()
            if '(' in pos:
                pos = pos.split('(')[0].strip()
            if pos and pos.isdigit():
                pos_list.append(int(pos))
        
        if len(pos_list) > 1:
            multiple_position_records.append({
                'identifier': row['Identifier'],
                'name': row['Name'],
                'positions': pos_list,
                'storage': row['Storage'],
                'date': row['DateOfAcquire'],
                'source': row['Source']
            })

print(f"Excel中有多个位置的质粒数量: {len(multiple_position_records)}")

# 检查库存中这些质粒的记录情况
for record in multiple_position_records:
    print(f"\n{record['identifier']}: {record['name'][:50]}...")
    print(f"  Excel位置: {record['positions']}")
    print(f"  存储: {record['storage']}")
    
    # 在库存中查找这个标识符
    inventory_positions = []
    for inv_record in inventory_data['inventory']:
        if inv_record.get('identifier') == record['identifier']:
            if inv_record.get('position'):
                inventory_positions.append(int(inv_record['position']))
    
    if inventory_positions:
        print(f"  库存位置: {inventory_positions}")
        
        # 检查缺失的位置
        missing_positions = []
        for pos in record['positions']:
            if pos not in inventory_positions:
                missing_positions.append(pos)
        
        if missing_positions:
            print(f"  ⚠️  缺失位置: {missing_positions}")
        else:
            print(f"  ✅ 所有位置都已记录")
    else:
        print(f"  ⚠️  库存中无此记录")

# 特别检查盒子1中的多个位置质粒
print("\n=== 盒子1中的多个位置质粒 ===")
for record in multiple_position_records:
    if '1号盒子' in record['storage']:
        print(f"\n{record['identifier']}: {record['name'][:50]}...")
        print(f"  位置: {record['positions']}")
        
        # 检查库存
        inventory_positions = []
        for inv_record in inventory_data['inventory']:
            if inv_record.get('identifier') == record['identifier'] and inv_record.get('box') == 1:
                if inv_record.get('position'):
                    inventory_positions.append(int(inv_record['position']))
        
        if inventory_positions:
            print(f"  库存位置: {inventory_positions}")
            
            # 检查缺失的位置
            missing_positions = []
            for pos in record['positions']:
                if pos not in inventory_positions:
                    missing_positions.append(pos)
            
            if missing_positions:
                print(f"  ⚠️  缺失位置: {missing_positions}")
            else:
                print(f"  ✅ 所有位置都已记录")
        else:
            print(f"  ⚠️  库存中无此记录")

# 检查盒子2中的多个位置质粒
print("\n=== 盒子2中的多个位置质粒 ===")
for record in multiple_position_records:
    if '2号盒子' in record['storage']:
        print(f"\n{record['identifier']}: {record['name'][:50]}...")
        print(f"  位置: {record['positions']}")
        
        # 检查库存
        inventory_positions = []
        for inv_record in inventory_data['inventory']:
            if inv_record.get('identifier') == record['identifier'] and inv_record.get('box') == 2:
                if inv_record.get('position'):
                    inventory_positions.append(int(inv_record['position']))
        
        if inventory_positions:
            print(f"  库存位置: {inventory_positions}")
            
            # 检查缺失的位置
            missing_positions = []
            for pos in record['positions']:
                if pos not in inventory_positions:
                    missing_positions.append(pos)
            
            if missing_positions:
                print(f"  ⚠️  缺失位置: {missing_positions}")
            else:
                print(f"  ✅ 所有位置都已记录")
        else:
            print(f"  ⚠️  库存中无此记录")
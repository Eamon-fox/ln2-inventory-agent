import csv

print("=== 检查缺失记录详情 ===")

# 读取原始Excel数据
with open('normalized/source/sheets/01_Sheet1.csv', 'r', encoding='utf-8-sig') as f:
    reader = csv.DictReader(f)
    rows = list(reader)

# 检查缺失的标识符
missing_identifiers = [
    '',  # 位置27: C-MYL6-dTAG-PGEMT
    '-',  # 位置79: K562 genomic DNA
    'p241231-1', 'p241231-2', 'p241231-3', 'p241231-5', 'p241231-6', 'p241231-7',
    'p250403-1', 'p250403-2', 'p250403-3', 'p250403-4', 'p250403-5', 'p250403-6', 'p250403-7', 'p250403-8'
]

print("缺失记录的详细信息:")
for identifier in missing_identifiers:
    for row in rows:
        if row['Identifier'] == identifier and '3号盒子' in row['Storage']:
            print(f"\n标识符: '{identifier}'")
            print(f"  名称: {row['Name']}")
            print(f"  日期: {row['DateOfAcquire']}")
            print(f"  存储: {row['Storage']}")
            print(f"  位置: {row['Position']}")
            print(f"  来源: {row['Source']}")
            if row['Note']:
                print(f"  备注: {row['Note'][:100]}...")

# 特别检查位置27和79
print("\n=== 特别检查位置27和79 ===")
for row in rows:
    if '3号盒子' in row['Storage']:
        positions = row['Position'].strip()
        if positions:
            pos_list = []
            for pos in positions.split(','):
                pos = pos.strip()
                if '(' in pos:
                    pos = pos.split('(')[0].strip()
                if pos and (pos == '27' or pos == '79'):
                    print(f"\n位置{pos}:")
                    print(f"  标识符: '{row['Identifier']}'")
                    print(f"  名称: {row['Name']}")
                    print(f"  日期: {row['DateOfAcquire']}")

# 检查p241106-5/6/7的多个位置
print("\n=== 检查p241106-5/6/7的多个位置 ===")
for identifier in ['p241106-5', 'p241106-6', 'p241106-7']:
    for row in rows:
        if row['Identifier'] == identifier:
            print(f"\n{identifier}: {row['Name']}")
            print(f"  位置: {row['Position']}")
            print(f"  备注: {row['Note'][:100] if row['Note'] else '无'}")

# 检查p241231-1的多个位置
print("\n=== 检查p241231-1的多个位置 ===")
for row in rows:
    if row['Identifier'] == 'p241231-1':
        print(f"\np241231-1: {row['Name']}")
        print(f"  位置: {row['Position']}")
        print(f"  备注: {row['Note'][:100] if row['Note'] else '无'}")
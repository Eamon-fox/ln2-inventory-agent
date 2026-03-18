import csv
import re
from collections import Counter

try:
    from migrate.path_context import DEFAULT_SOURCE_SHEET
except ImportError:
    from path_context import DEFAULT_SOURCE_SHEET

# 读取CSV文件
with DEFAULT_SOURCE_SHEET.open('r', encoding='utf-8-sig') as f:
    reader = csv.DictReader(f)
    rows = list(reader)

print(f"总记录数: {len(rows)}")

# 分析Storage字段
storage_counts = Counter()
for row in rows:
    storage = row['Storage'].strip()
    storage_counts[storage] += 1

print("\nStorage字段分布:")
for storage, count in storage_counts.most_common():
    print(f"  {storage}: {count}")

# 分析个人存储的记录
personal_storage = []
for row in rows:
    storage = row['Storage'].strip()
    if storage and not re.search(r'\d+号盒子', storage):
        personal_storage.append(row)

print(f"\n个人存储记录数: {len(personal_storage)}")
for row in personal_storage[:10]:  # 显示前10个
    print(f"  {row['Identifier']}: {row['Storage']} - {row['Name']}")

# 分析Position字段格式
position_formats = Counter()
for row in rows:
    pos = row['Position'].strip()
    if not pos:
        position_formats['空'] += 1
    elif ',' in pos:
        position_formats['多位置'] += 1
    else:
        position_formats['单位置'] += 1

print("\nPosition字段格式:")
for fmt, count in position_formats.items():
    print(f"  {fmt}: {count}")

# 检查日期格式
date_formats = Counter()
for row in rows:
    date = row['DateOfAcquire'].strip()
    if date:
        if len(date) == 8 and date.isdigit():
            date_formats['YYYYMMDD'] += 1
        else:
            date_formats['其他'] += 1
    else:
        date_formats['空'] += 1

print("\nDateOfAcquire字段格式:")
for fmt, count in date_formats.items():
    print(f"  {fmt}: {count}")

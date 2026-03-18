import csv
import yaml

print("=== 智能添加缺失位置 ===")

# 读取当前库存数据
with open('../inventories/plasmid_test/inventory.yaml', 'r', encoding='utf-8') as f:
    inventory_data = yaml.safe_load(f)

# 检查位置是否被占用
def is_position_occupied(box, position):
    for record in inventory_data['inventory']:
        if record.get('box') == box and record.get('position') == str(position):
            return True
    return False

# 操作列表（从之前的脚本中提取）
operations = [
    # 盒子1的操作
    {'box': 1, 'position': 34, 'frozen_at': '2022-11-02', 'identifier': 'p221102-1', 'name': 'pSPAX2', 'source': '张涛', 'note': '备份位置（原位置32）'},
    {'box': 1, 'position': 35, 'frozen_at': '2022-11-02', 'identifier': 'p221102-2', 'name': 'pMD2G', 'source': '张涛', 'note': '备份位置（原位置33）'},
    {'box': 1, 'position': 6, 'frozen_at': '2023-04-03', 'identifier': 'p230403-2', 'name': 'PX330-VPR-dCas9-GFP', 'source': '别路垚。于艺丹在三轮轮转期间构建', 'note': '备份位置（原位置5）'},
    {'box': 1, 'position': 45, 'frozen_at': '2023-04-03', 'identifier': 'p230403-2', 'name': 'PX330-VPR-dCas9-GFP', 'source': '别路垚。于艺丹在三轮轮转期间构建', 'note': '备份位置（原位置5）'},
    {'box': 1, 'position': 46, 'frozen_at': '2023-04-03', 'identifier': 'p230403-2', 'name': 'PX330-VPR-dCas9-GFP', 'source': '别路垚。于艺丹在三轮轮转期间构建', 'note': '备份位置（原位置5）'},
    {'box': 1, 'position': 8, 'frozen_at': '2023-04-03', 'identifier': 'p230403-3', 'name': 'PX330-KRAB-dCas9-GFP', 'source': '别路垚。于艺丹在三轮轮转期间构建', 'note': '备份位置（原位置7）'},
    {'box': 1, 'position': 47, 'frozen_at': '2023-04-03', 'identifier': 'p230403-3', 'name': 'PX330-KRAB-dCas9-GFP', 'source': '别路垚。于艺丹在三轮轮转期间构建', 'note': '备份位置（原位置7）'},
    {'box': 1, 'position': 40, 'frozen_at': '2023-05-02', 'identifier': 'p230502-1', 'name': 'pLentiCas9-tagBFP', 'source': '严小涵', 'note': '备份位置（原位置18）'},
    {'box': 1, 'position': 42, 'frozen_at': '2023-05-11', 'identifier': 'p230511-1', 'name': 'pCS2-NLS-zCas9', 'source': '孟安明实验室李晗处借得', 'note': '备份位置（原位置41）'},
    {'box': 1, 'position': 57, 'frozen_at': '2023-05-20', 'identifier': 'p230520-1', 'name': 'PX458-mCherry', 'source': '别路垚', 'note': '备份位置（原位置56）'},
    {'box': 1, 'position': 51, 'frozen_at': '2023-07-04', 'identifier': 'p230704-1', 'name': 'pCS2-VPR-dCas9', 'source': '樊一鸣构建', 'note': '备份位置（原位置50）'},
    {'box': 1, 'position': 53, 'frozen_at': '2023-07-04', 'identifier': 'p230704-2', 'name': 'pCS2-KRAB-dCas9', 'source': '樊一鸣构建', 'note': '备份位置（原位置52）'},
    {'box': 1, 'position': 73, 'frozen_at': '2023-07-26', 'identifier': 'p230726-6', 'name': 'Des-MCP-APEX2', 'source': '樊一鸣构建', 'note': '备份位置（原位置72）'},
    {'box': 1, 'position': 39, 'frozen_at': '2023-08-14', 'identifier': 'p230814-1', 'name': 'LNC5', 'source': '王洋冰箱', 'note': '备份位置（原位置36）'},
    
    # 盒子2的操作
    {'box': 2, 'position': 4, 'frozen_at': '2023-09-23', 'identifier': 'p231008-3', 'name': 'LNC5-PJM105-L1-as5UTR-tagBFP-MSx4', 'source': '樊一鸣构建', 'note': '备份位置（原位置3）'},
    {'box': 2, 'position': 5, 'frozen_at': '2023-09-23', 'identifier': 'p231008-3', 'name': 'LNC5-PJM105-L1-as5UTR-tagBFP-MSx4', 'source': '樊一鸣构建', 'note': '备份位置（原位置3）'},
    {'box': 2, 'position': 7, 'frozen_at': '2023-10-05', 'identifier': 'p231008-4', 'name': 'LNC5-PJM105-L1-5UTR-ORF1-tagBFP-ORF2-3UTR-MSx4', 'source': '樊一鸣构建', 'note': '备份位置（原位置6）'},
    {'box': 2, 'position': 8, 'frozen_at': '2023-10-05', 'identifier': 'p231008-4', 'name': 'LNC5-PJM105-L1-5UTR-ORF1-tagBFP-ORF2-3UTR-MSx4', 'source': '樊一鸣构建', 'note': '备份位置（原位置6）'},
    {'box': 2, 'position': 12, 'frozen_at': '2023-12-28', 'identifier': 'p231228-2', 'name': 'PB-TetOn-APEX2-V5-RTCB-BSD', 'source': '杨乐构建', 'note': '备份位置（原位置11）'},
    {'box': 2, 'position': 9, 'frozen_at': '2023-01-01', 'identifier': '-', 'name': 'NCCIT genomic DNA', 'source': '', 'note': '备份位置（原位置未知）'},
    {'box': 2, 'position': 10, 'frozen_at': '2023-01-01', 'identifier': '-', 'name': 'NCCIT genomic DNA', 'source': '', 'note': '备份位置（原位置未知）'},
    {'box': 2, 'position': 22, 'frozen_at': '2024-07-01', 'identifier': 'p240701-1', 'name': 'PDAC439', 'source': '池天课题组赠', 'note': '备份位置（原位置21）'},
    {'box': 2, 'position': 50, 'frozen_at': '2024-07-01', 'identifier': 'p240701-2', 'name': 'PDAC446', 'source': 'addgene购买', 'note': '备份位置（原位置23）'},
    {'box': 2, 'position': 29, 'frozen_at': '2024-07-03', 'identifier': 'p240703-3', 'name': 'P320-Cas13DR-mCherry', 'source': '杨乐', 'note': '备份位置（原位置28）'},
    {'box': 2, 'position': 33, 'frozen_at': '2024-07-05', 'identifier': 'p240705-3', 'name': 'P320-CsmDR-mCherry', 'source': '樊一鸣构建', 'note': '备份位置（原位置32）'},
    
    # 盒子3的操作
    {'box': 3, 'position': 20, 'frozen_at': '2024-12-31', 'identifier': 'p241231-1', 'name': 'P320-Cas9DR-NeoR-T2A-mCherry(sg: WDR18)', 'source': '樊一鸣构建', 'note': '备份位置（原位置36）'},
]

print(f"总操作数: {len(operations)}")

# 检查每个位置
available_operations = []
occupied_positions = []

for op in operations:
    if is_position_occupied(op['box'], op['position']):
        occupied_positions.append((op['box'], op['position'], op['identifier']))
    else:
        available_operations.append(op)

print(f"\n可执行的操作: {len(available_operations)}")
print(f"已被占用的位置: {len(occupied_positions)}")

if occupied_positions:
    print("\n已被占用的位置:")
    for box, pos, identifier in occupied_positions:
        print(f"  盒子{box}:{pos} - {identifier}")

# 生成可执行的add_entry调用
print("\n=== 可执行的add_entry调用 ===")

for i, op in enumerate(available_operations):
    print(f"\n# 操作 {i+1}: {op['identifier']} @ 盒子{op['box']}:{op['position']}")
    print(f"add_entry(")
    print(f"    box={op['box']},")
    print(f"    positions=[{op['position']}],")
    print(f"    frozen_at='{op['frozen_at']}',")
    print(f"    fields={{")
    print(f"        'identifier': '{op['identifier']}',")
    print(f"        'name': '{op['name']}',")
    print(f"        'source': '{op['source']}',")
    print(f"        'note': '{op['note']}'")
    print(f"    }}")
    print(f")")

print(f"\n✅ 共 {len(available_operations)} 个可执行操作")
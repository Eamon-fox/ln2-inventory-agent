# 自动生成的add操作脚本
# 为多个位置的质粒创建缺失记录

from ln2_inventory_agent.tools import add_entry

print('开始执行add操作...')

# 操作列表
operations = [
    # 操作 1: p221102-1 @ 盒子1:34
    {
        'box': 1,
        'positions': [34],
        'frozen_at': '2022-11-02',
        'fields': {
            'identifier': 'p221102-1',
            'name': 'pSPAX2',
            'source': '张涛',
            'note': '备份位置（原位置32）'
        }
    },
    # 操作 2: p221102-2 @ 盒子1:35
    {
        'box': 1,
        'positions': [35],
        'frozen_at': '2022-11-02',
        'fields': {
            'identifier': 'p221102-2',
            'name': 'pMD2G',
            'source': '张涛',
            'note': '备份位置（原位置33）'
        }
    },
    # 操作 3: p230403-2 @ 盒子1:6
    {
        'box': 1,
        'positions': [6],
        'frozen_at': '2023-04-03',
        'fields': {
            'identifier': 'p230403-2',
            'name': 'PX330-VPR-dCas9-GFP',
            'source': '别路垚。于艺丹在三轮轮转期间构建',
            'note': '备份位置（原位置5）'
        }
    },
    # 操作 4: p230403-2 @ 盒子1:45
    {
        'box': 1,
        'positions': [45],
        'frozen_at': '2023-04-03',
        'fields': {
            'identifier': 'p230403-2',
            'name': 'PX330-VPR-dCas9-GFP',
            'source': '别路垚。于艺丹在三轮轮转期间构建',
            'note': '备份位置（原位置5）'
        }
    },
    # 操作 5: p230403-2 @ 盒子1:46
    {
        'box': 1,
        'positions': [46],
        'frozen_at': '2023-04-03',
        'fields': {
            'identifier': 'p230403-2',
            'name': 'PX330-VPR-dCas9-GFP',
            'source': '别路垚。于艺丹在三轮轮转期间构建',
            'note': '备份位置（原位置5）'
        }
    },
    # 操作 6: p230403-3 @ 盒子1:8
    {
        'box': 1,
        'positions': [8],
        'frozen_at': '2023-04-03',
        'fields': {
            'identifier': 'p230403-3',
            'name': 'PX330-KRAB-dCas9-GFP',
            'source': '别路垚。于艺丹在三轮轮转期间构建',
            'note': '备份位置（原位置7）'
        }
    },
    # 操作 7: p230403-3 @ 盒子1:47
    {
        'box': 1,
        'positions': [47],
        'frozen_at': '2023-04-03',
        'fields': {
            'identifier': 'p230403-3',
            'name': 'PX330-KRAB-dCas9-GFP',
            'source': '别路垚。于艺丹在三轮轮转期间构建',
            'note': '备份位置（原位置7）'
        }
    },
    # 操作 8: p230502-1 @ 盒子1:40
    {
        'box': 1,
        'positions': [40],
        'frozen_at': '2023-05-02',
        'fields': {
            'identifier': 'p230502-1',
            'name': 'pLentiCas9-tagBFP',
            'source': '严小涵',
            'note': '备份位置（原位置18）'
        }
    },
    # 操作 9: p230511-1 @ 盒子1:42
    {
        'box': 1,
        'positions': [42],
        'frozen_at': '2023-05-11',
        'fields': {
            'identifier': 'p230511-1',
            'name': 'pCS2-NLS-zCas9',
            'source': '孟安明实验室李晗处借得',
            'note': '备份位置（原位置41）'
        }
    },
    # 操作 10: p230520-1 @ 盒子1:57
    {
        'box': 1,
        'positions': [57],
        'frozen_at': '2023-05-20',
        'fields': {
            'identifier': 'p230520-1',
            'name': 'PX458-mCherry',
            'source': '别路垚',
            'note': '备份位置（原位置56）'
        }
    },
    # 操作 11: p230704-1 @ 盒子1:51
    {
        'box': 1,
        'positions': [51],
        'frozen_at': '2023-07-04',
        'fields': {
            'identifier': 'p230704-1',
            'name': 'pCS2-VPR-dCas9',
            'source': '樊一鸣构建',
            'note': '备份位置（原位置50）'
        }
    },
    # 操作 12: p230704-2 @ 盒子1:53
    {
        'box': 1,
        'positions': [53],
        'frozen_at': '2023-07-04',
        'fields': {
            'identifier': 'p230704-2',
            'name': 'pCS2-KRAB-dCas9',
            'source': '樊一鸣构建',
            'note': '备份位置（原位置52）'
        }
    },
    # 操作 13: p230726-6 @ 盒子1:73
    {
        'box': 1,
        'positions': [73],
        'frozen_at': '2023-07-26',
        'fields': {
            'identifier': 'p230726-6',
            'name': 'Des-MCP-APEX2',
            'source': '樊一鸣构建',
            'note': '备份位置（原位置72）'
        }
    },
    # 操作 14: p230814-1 @ 盒子1:39
    {
        'box': 1,
        'positions': [39],
        'frozen_at': '2023-08-14',
        'fields': {
            'identifier': 'p230814-1',
            'name': 'LNC5',
            'source': '王洋冰箱',
            'note': '备份位置（原位置36）'
        }
    },
    # 操作 15: p231008-3 @ 盒子2:4
    {
        'box': 2,
        'positions': [4],
        'frozen_at': '2023-09-23',
        'fields': {
            'identifier': 'p231008-3',
            'name': 'LNC5-PJM105-L1-as5UTR-tagBFP-MSx4',
            'source': '樊一鸣构建',
            'note': '备份位置（原位置3）'
        }
    },
    # 操作 16: p231008-3 @ 盒子2:5
    {
        'box': 2,
        'positions': [5],
        'frozen_at': '2023-09-23',
        'fields': {
            'identifier': 'p231008-3',
            'name': 'LNC5-PJM105-L1-as5UTR-tagBFP-MSx4',
            'source': '樊一鸣构建',
            'note': '备份位置（原位置3）'
        }
    },
    # 操作 17: p231008-4 @ 盒子2:7
    {
        'box': 2,
        'positions': [7],
        'frozen_at': '2023-10-05',
        'fields': {
            'identifier': 'p231008-4',
            'name': 'LNC5-PJM105-L1-5UTR-ORF1-tagBFP-ORF2-3UTR-MSx4',
            'source': '樊一鸣构建',
            'note': '备份位置（原位置6）'
        }
    },
    # 操作 18: p231008-4 @ 盒子2:8
    {
        'box': 2,
        'positions': [8],
        'frozen_at': '2023-10-05',
        'fields': {
            'identifier': 'p231008-4',
            'name': 'LNC5-PJM105-L1-5UTR-ORF1-tagBFP-ORF2-3UTR-MSx4',
            'source': '樊一鸣构建',
            'note': '备份位置（原位置6）'
        }
    },
    # 操作 19: p231228-2 @ 盒子2:12
    {
        'box': 2,
        'positions': [12],
        'frozen_at': '2023-12-28',
        'fields': {
            'identifier': 'p231228-2',
            'name': 'PB-TetOn-APEX2-V5-RTCB-BSD',
            'source': '杨乐构建',
            'note': '备份位置（原位置11）'
        }
    },
    # 操作 20: - @ 盒子2:9
    {
        'box': 2,
        'positions': [9],
        'frozen_at': '2023-01-01',
        'fields': {
            'identifier': '-',
            'name': 'NCCIT genomic DNA',
            'source': '',
            'note': '备份位置（原位置未知）'
        }
    },
    # 操作 21: - @ 盒子2:10
    {
        'box': 2,
        'positions': [10],
        'frozen_at': '2023-01-01',
        'fields': {
            'identifier': '-',
            'name': 'NCCIT genomic DNA',
            'source': '',
            'note': '备份位置（原位置未知）'
        }
    },
    # 操作 22: p240701-1 @ 盒子2:22
    {
        'box': 2,
        'positions': [22],
        'frozen_at': '2024-07-01',
        'fields': {
            'identifier': 'p240701-1',
            'name': 'PDAC439',
            'source': '池天课题组赠',
            'note': '备份位置（原位置21）'
        }
    },
    # 操作 23: p240701-2 @ 盒子2:50
    {
        'box': 2,
        'positions': [50],
        'frozen_at': '2024-07-01',
        'fields': {
            'identifier': 'p240701-2',
            'name': 'PDAC446',
            'source': 'addgene购买',
            'note': '备份位置（原位置23）'
        }
    },
    # 操作 24: p240703-3 @ 盒子2:29
    {
        'box': 2,
        'positions': [29],
        'frozen_at': '2024-07-03',
        'fields': {
            'identifier': 'p240703-3',
            'name': 'P320-Cas13DR-mCherry',
            'source': '杨乐',
            'note': '备份位置（原位置28）'
        }
    },
    # 操作 25: p240705-3 @ 盒子2:33
    {
        'box': 2,
        'positions': [33],
        'frozen_at': '2024-07-05',
        'fields': {
            'identifier': 'p240705-3',
            'name': 'P320-CsmDR-mCherry',
            'source': '樊一鸣构建',
            'note': '备份位置（原位置32）'
        }
    },
    # 操作 26: p241231-1 @ 盒子3:20
    {
        'box': 3,
        'positions': [20],
        'frozen_at': '2024-12-31',
        'fields': {
            'identifier': 'p241231-1',
            'name': 'P320-Cas9DR-NeoR-T2A-mCherry(sg: WDR18)',
            'source': '樊一鸣构建',
            'note': '备份位置（原位置36）'
        }
    },
]

# 执行操作
for i, op in enumerate(operations):
    print(f'执行操作 {i+1}/{len(operations)}: {op["fields"]["identifier"]} @ 盒子{op["box"]}:{op["positions"][0]}')
    try:
        result = add_entry(
            box=op['box'],
            positions=op['positions'],
            frozen_at=op['frozen_at'],
            fields=op['fields']
        )
        if result.get('ok'):
            print('  ✅ 成功')
        else:
            print(f'  ❌ 失败: {{result.get("error_code", "未知错误")}}')
    except Exception as e:
        print(f'  ❌ 异常: {{e}}')

print('所有操作执行完成！')
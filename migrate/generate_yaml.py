#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import json
import yaml

# 读取JSON数据
with open('migrate/output/inventory_preview.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

# 添加缺失的meta字段
data['meta']['box_layout']['box_count'] = 5
data['meta']['box_layout']['box_numbers'] = [1, 2, 3, 4, 5]

# 自定义YAML格式化
def str_representer(dumper, data):
    if '\n' in data:
        return dumper.represent_scalar('tag:yaml.org,2002:str', data, style='|')
    return dumper.represent_scalar('tag:yaml.org,2002:str', data)

yaml.add_representer(str, str_representer)

# 写入YAML
with open('migrate/output/ln2_inventory.yaml', 'w', encoding='utf-8') as f:
    yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False, width=1000)

print('YAML file updated with box_count and box_numbers')

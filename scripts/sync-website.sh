#!/bin/bash
# 快速同步版本到网站（不构建）
cd ~/snowfox
python3 scripts/sync_website_version.py
python3 scripts/update_history_versions.py
echo "✅ 网站版本已同步"

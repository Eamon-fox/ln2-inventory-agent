#!/bin/bash
# 通过 SSH 将最新版本元数据同步到网站服务器，并在服务器端重建 dist
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WEBSITE_HOST="${WEBSITE_HOST:-ecs}"
WEBSITE_DIR="${WEBSITE_DIR:-/var/www/snowfox.bio}"
LOCAL_LATEST_JSON="$REPO_ROOT/latest.json"
SSH_OPTS=(-o ForwardX11=no)

if [[ ! -f "$LOCAL_LATEST_JSON" ]]; then
    echo "❌ 找不到 $LOCAL_LATEST_JSON"
    exit 1
fi

LOCAL_VERSION="$(python3 - "$LOCAL_LATEST_JSON" <<'PY'
import json
import pathlib
import sys

payload = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
print(payload["version"])
PY
)"

echo "🌐 同步网站版本"
echo "================"
echo "版本: v$LOCAL_VERSION"
echo "目标主机: $WEBSITE_HOST"
echo "目标目录: $WEBSITE_DIR"
echo ""

echo "1️⃣  复制 latest.json 到网站服务器..."
scp "${SSH_OPTS[@]}" "$LOCAL_LATEST_JSON" "${WEBSITE_HOST}:${WEBSITE_DIR}/latest.json"

echo ""
echo "2️⃣  在网站服务器重建 dist/ ..."
ssh "${SSH_OPTS[@]}" "$WEBSITE_HOST" "cd '$WEBSITE_DIR' && node scripts/build.js"

echo ""
echo "3️⃣  校验 dist/latest.json 版本..."
REMOTE_VERSION="$(ssh "${SSH_OPTS[@]}" "$WEBSITE_HOST" "python3 - <<'PY'
import json
from pathlib import Path

payload = json.loads(Path('$WEBSITE_DIR/dist/latest.json').read_text(encoding='utf-8'))
print(payload['version'])
PY
")"

if [[ "$REMOTE_VERSION" != "$LOCAL_VERSION" ]]; then
    echo "❌ 校验失败：本地版本是 v$LOCAL_VERSION，服务器 dist/latest.json 是 v$REMOTE_VERSION"
    exit 1
fi

echo "✅ 网站已同步到 v$REMOTE_VERSION"
echo "   建议验收: https://snowfox.bio/download.html"

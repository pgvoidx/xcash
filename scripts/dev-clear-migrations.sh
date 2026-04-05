#!/usr/bin/env bash
# 删除所有 app 的迁移文件（保留 __init__.py），用于开发环境重建迁移。
set -euo pipefail

APPS_DIR="$(cd "$(dirname "$0")/../xcash" && pwd)"

count=0
for migrations_dir in "$APPS_DIR"/*/migrations; do
    [ -d "$migrations_dir" ] || continue
    for f in "$migrations_dir"/*; do
        [ -f "$f" ] || continue
        [ "$(basename "$f")" = "__init__.py" ] && continue
        rm "$f"
        count=$((count + 1))
    done
done

echo "已删除 ${count} 个迁移文件"

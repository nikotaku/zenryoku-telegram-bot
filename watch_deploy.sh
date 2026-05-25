#!/bin/bash
# バックグラウンドで30秒ごとにデプロイチェックするウォッチャー
REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
while true; do
    bash "$REPO_DIR/autodeploy.sh"
    sleep 30
done

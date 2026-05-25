#!/bin/bash
# 自動デプロイスクリプト: mainブランチに変更があれば自動でpull & 再起動
set -e

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$REPO_DIR/deploy.log"
BRANCH="main"

cd "$REPO_DIR"

git fetch origin "$BRANCH" --quiet

LOCAL=$(git rev-parse HEAD)
REMOTE=$(git rev-parse "origin/$BRANCH")

if [ "$LOCAL" = "$REMOTE" ]; then
    exit 0
fi

echo "[$(date '+%Y-%m-%d %H:%M:%S')] 新しいコミットを検出: $REMOTE" | tee -a "$LOG"

git reset --hard "origin/$BRANCH" >> "$LOG" 2>&1

# 既存プロセスを停止
pkill -f "python.*bot\.py" 2>/dev/null || true
pkill -f "python.*start\.py" 2>/dev/null || true
sleep 2

# 再起動
nohup python "$REPO_DIR/bot.py" >> "$REPO_DIR/bot.log" 2>&1 &
echo "[$(date '+%Y-%m-%d %H:%M:%S')] bot再起動 PID=$!" | tee -a "$LOG"

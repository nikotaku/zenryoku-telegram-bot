#!/bin/bash
# 自動デプロイスクリプト: mainブランチに変更があれば自動でpull & 再起動

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$REPO_DIR/deploy.log"
BRANCH="main"

cd "$REPO_DIR"

git fetch origin "$BRANCH" --quiet 2>/dev/null || exit 0

LOCAL=$(git rev-parse HEAD)
REMOTE=$(git rev-parse "origin/$BRANCH")

if [ "$LOCAL" = "$REMOTE" ]; then
    exit 0
fi

echo "[$(date '+%Y-%m-%d %H:%M:%S')] 新しいコミットを検出: $REMOTE" | tee -a "$LOG"

git reset --hard "origin/$BRANCH" >> "$LOG" 2>&1

# 既存プロセスを停止（確実にKILLして解放を待つ）
pkill -TERM -f "bot\.py" 2>/dev/null || true
sleep 2
pkill -KILL -f "bot\.py" 2>/dev/null || true
sleep 1

# 使用するpythonを自動検出
if [ -f "$REPO_DIR/venv/bin/python" ]; then
    PYTHON="$REPO_DIR/venv/bin/python"
elif command -v python3 &>/dev/null; then
    PYTHON="python3"
else
    PYTHON="python"
fi

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Python: $PYTHON" | tee -a "$LOG"
nohup "$PYTHON" "$REPO_DIR/bot.py" >> "$REPO_DIR/bot.log" 2>&1 &
echo "[$(date '+%Y-%m-%d %H:%M:%S')] bot再起動 PID=$!" | tee -a "$LOG"

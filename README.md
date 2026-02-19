# 全力エステ Telegram Bot

全力エステのTelegramボットです。

## 機能

- 📢 出勤ツイート
- 📅 スケジュール確認
- 👤 プロフィール作成

## デプロイ方法

### Railway

1. GitHubリポジトリをRailwayに接続
2. 環境変数 `TELEGRAM_BOT_TOKEN` を設定
3. デプロイ

## 環境変数

- `TELEGRAM_BOT_TOKEN`: TelegramボットのAPIトークン

## ローカル実行

```bash
export TELEGRAM_BOT_TOKEN="your_token_here"
pip install -r requirements.txt
python bot.py
```

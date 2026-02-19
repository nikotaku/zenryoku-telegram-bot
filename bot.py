#!/usr/bin/env python3
"""
Telegram Bot - メニューボタン付きボット
機能:
  - 出勤ツイート
  - スケジュール確認
  - プロフィール作成
"""

import os
import logging
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
from telegram.request import HTTPXRequest

# ─── 設定 ───────────────────────────────────────────────
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")

if not BOT_TOKEN:
    raise ValueError("環境変数 TELEGRAM_BOT_TOKEN が設定されていません")

# ログ設定
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ─── メニューキーボード ─────────────────────────────────
MENU_KEYBOARD = ReplyKeyboardMarkup(
    [
        [KeyboardButton("📢 出勤ツイート")],
        [KeyboardButton("📅 スケジュール確認")],
        [KeyboardButton("👤 プロフィール作成")],
    ],
    resize_keyboard=True,
    one_time_keyboard=False,
)


# ─── ハンドラー ─────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /start コマンド — メニューを表示する
    """
    welcome_text = (
        "こんにちは！ボットへようこそ 🎉\n\n"
        "以下のメニューから操作を選んでください。"
    )
    await update.message.reply_text(welcome_text, reply_markup=MENU_KEYBOARD)


async def handle_attendance_tweet(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    出勤ツイート — プレースホルダー応答
    """
    await update.message.reply_text(
        "📢 【出勤ツイート】\n\n"
        "出勤ツイート機能は現在準備中です。\n"
        "今後、ここから出勤報告を投稿できるようになります。",
        reply_markup=MENU_KEYBOARD,
    )


async def handle_schedule_check(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    スケジュール確認 — プレースホルダー応答
    """
    await update.message.reply_text(
        "📅 【スケジュール確認】\n\n"
        "スケジュール確認機能は現在準備中です。\n"
        "今後、ここから本日のスケジュールを確認できるようになります。",
        reply_markup=MENU_KEYBOARD,
    )


async def handle_profile_create(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    プロフィール作成 — プレースホルダー応答
    """
    await update.message.reply_text(
        "👤 【プロフィール作成】\n\n"
        "プロフィール作成機能は現在準備中です。\n"
        "今後、ここからプロフィールを登録・編集できるようになります。",
        reply_markup=MENU_KEYBOARD,
    )


async def handle_unknown(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    未知のメッセージ — メニューを再表示
    """
    await update.message.reply_text(
        "メニューから操作を選んでください。",
        reply_markup=MENU_KEYBOARD,
    )


# ─── メイン ─────────────────────────────────────────────
def main() -> None:
    """ボットを起動する"""
    # タイムアウトとリトライを設定した HTTPXRequest を使用
    request = HTTPXRequest(
        connect_timeout=30.0,
        read_timeout=30.0,
        write_timeout=30.0,
        pool_timeout=30.0,
        connection_pool_size=8,
    )

    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .request(request)
        .get_updates_request(
            HTTPXRequest(
                connect_timeout=30.0,
                read_timeout=30.0,
                write_timeout=30.0,
                pool_timeout=30.0,
            )
        )
        .build()
    )

    # /start コマンド
    app.add_handler(CommandHandler("start", start))

    # メニューボタンに対応するメッセージハンドラー
    app.add_handler(
        MessageHandler(filters.Regex(r"^📢 出勤ツイート$"), handle_attendance_tweet)
    )
    app.add_handler(
        MessageHandler(filters.Regex(r"^📅 スケジュール確認$"), handle_schedule_check)
    )
    app.add_handler(
        MessageHandler(filters.Regex(r"^👤 プロフィール作成$"), handle_profile_create)
    )

    # その他のメッセージ
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_unknown))

    # ポーリング開始（ボットが常駐動作）
    logger.info("ボットを起動しました。Ctrl+C で停止します。")
    app.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True,
        poll_interval=2.0,
        bootstrap_retries=5,
    )


if __name__ == "__main__":
    main()

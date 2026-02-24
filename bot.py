#!/usr/bin/env python3
"""
全力エステ Telegram Bot (@zenryoku_bot)
機能:
  - 出勤ツイート（プレースホルダー）
  - スケジュール確認（キャスカン連携）
  - プロフィール作成（プレースホルダー）
  - 📸 プロフィール写真管理（Notion連携）
  - 🏪 キャスカン ハブ（売上・スケジュール・予約確認）
  - 🌟 エスたま ハブ（ダッシュボード・ご案内状況・アピール）
"""

import os
import logging
from datetime import datetime

from telegram import (
    Update,
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)
from telegram.request import HTTPXRequest

from notion_client import (
    get_therapist_list,
    get_therapist_page_id,
    append_image_to_page,
)
from image_uploader import upload_telegram_photo
from caskan_client import CaskanClient
from estama_client import EstamaClient

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

# クライアントインスタンス（遅延初期化）
_caskan_client = None
_estama_client = None


def get_caskan():
    global _caskan_client
    if _caskan_client is None:
        _caskan_client = CaskanClient()
    return _caskan_client


def get_estama():
    global _estama_client
    if _estama_client is None:
        _estama_client = EstamaClient()
    return _estama_client


# ─── メニューキーボード ─────────────────────────────────
MENU_KEYBOARD = ReplyKeyboardMarkup(
    [
        [KeyboardButton("📢 出勤ツイート"), KeyboardButton("📅 スケジュール確認")],
        [KeyboardButton("👤 プロフィール作成"), KeyboardButton("📸 写真管理")],
        [KeyboardButton("🏪 キャスカン"), KeyboardButton("🌟 エスたま")],
    ],
    resize_keyboard=True,
    one_time_keyboard=False,
)


# ─── /start コマンド ─────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """メニューを表示する"""
    welcome_text = (
        "こんにちは！全力エステBotへようこそ 💪\n\n"
        "以下のメニューから操作を選んでください。\n\n"
        "📸 写真を送信すると、セラピストのNotionページに保存できます。\n"
        "🏪 キャスカン・🌟 エスたまの情報も確認できます。"
    )
    await update.message.reply_text(welcome_text, reply_markup=MENU_KEYBOARD)


# ─── 既存機能（プレースホルダー） ─────────────────────────
async def handle_attendance_tweet(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """出勤ツイート"""
    # キャスカンから本日の出勤情報を取得して表示
    try:
        caskan = get_caskan()
        info = caskan.get_home_info()
        if "error" not in info and info.get("attendance_text"):
            await update.message.reply_text(
                f"📢 【出勤ツイート】\n\n"
                f"キャスカンの出勤情報:\n{info['attendance_text']}\n\n"
                f"※ この内容をX/Blueskyに投稿するにはキャスカン管理画面をご利用ください。",
                reply_markup=MENU_KEYBOARD,
            )
            return
    except Exception as e:
        logger.error(f"出勤情報取得エラー: {e}")

    await update.message.reply_text(
        "📢 【出勤ツイート】\n\n"
        "出勤ツイート機能は現在準備中です。\n"
        "今後、ここから出勤報告を投稿できるようになります。",
        reply_markup=MENU_KEYBOARD,
    )


async def handle_schedule_check(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """スケジュール確認 — キャスカンから取得"""
    await update.message.reply_text("📅 スケジュールを取得中...", reply_markup=MENU_KEYBOARD)

    try:
        caskan = get_caskan()
        data = caskan.get_schedule()
        if "error" in data:
            await update.message.reply_text(
                f"📅 【スケジュール確認】\n\n❌ エラー: {data['error']}",
                reply_markup=MENU_KEYBOARD,
            )
        else:
            text = data.get("schedule_text", "情報なし")
            # 長すぎる場合は切り詰め
            if len(text) > 3000:
                text = text[:3000] + "\n\n... (続きはキャスカン管理画面で確認)"
            await update.message.reply_text(
                f"📅 【週間スケジュール】\n{text}",
                reply_markup=MENU_KEYBOARD,
            )
    except Exception as e:
        logger.error(f"スケジュール取得エラー: {e}")
        await update.message.reply_text(
            "📅 【スケジュール確認】\n\n"
            "スケジュールの取得に失敗しました。後でもう一度お試しください。",
            reply_markup=MENU_KEYBOARD,
        )


async def handle_profile_create(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """プロフィール作成"""
    await update.message.reply_text(
        "👤 【プロフィール作成】\n\n"
        "プロフィール作成機能は現在準備中です。\n"
        "今後、ここからプロフィールを登録・編集できるようになります。",
        reply_markup=MENU_KEYBOARD,
    )


# ─── 📸 写真管理機能 ─────────────────────────────────────
async def handle_photo_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """写真管理メニュー"""
    await update.message.reply_text(
        "📸 【写真管理】\n\n"
        "セラピストのプロフィール写真をNotionに保存します。\n\n"
        "📷 画像を送信してください。\n"
        "送信後、保存先のセラピストを選択できます。",
        reply_markup=MENU_KEYBOARD,
    )


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """画像が送信された時の処理 — セラピスト選択ボタンを表示"""
    if not update.message.photo:
        return

    # 最高解像度の画像を取得
    photo = update.message.photo[-1]
    file_id = photo.file_id

    # file_id をコンテキストに保存
    context.user_data["pending_photo_file_id"] = file_id

    # セラピスト選択ボタンを生成
    therapists = get_therapist_list()
    keyboard = []
    row = []
    for name in therapists:
        row.append(InlineKeyboardButton(name, callback_data=f"photo_save:{name}"))
        if len(row) == 3:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)

    # キャンセルボタン
    keyboard.append([InlineKeyboardButton("❌ キャンセル", callback_data="photo_save:cancel")])

    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        "📸 画像を受け取りました！\n\n"
        "保存先のセラピストを選択してください:",
        reply_markup=reply_markup,
    )


async def handle_photo_save_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """セラピスト選択コールバック — 画像をNotionに保存"""
    query = update.callback_query
    await query.answer()

    data = query.data
    if not data.startswith("photo_save:"):
        return

    therapist_name = data.replace("photo_save:", "")

    if therapist_name == "cancel":
        context.user_data.pop("pending_photo_file_id", None)
        await query.edit_message_text("❌ 写真の保存をキャンセルしました。")
        return

    file_id = context.user_data.get("pending_photo_file_id")
    if not file_id:
        await query.edit_message_text("⚠️ 保存する画像が見つかりません。もう一度画像を送信してください。")
        return

    page_id = get_therapist_page_id(therapist_name)
    if not page_id:
        await query.edit_message_text(f"⚠️ セラピスト「{therapist_name}」のNotionページが見つかりません。")
        return

    await query.edit_message_text(f"⏳ {therapist_name}のNotionページに画像を保存中...")

    # 画像をアップロードしてURLを取得
    bot = context.bot
    image_url = await upload_telegram_photo(bot, file_id)

    if not image_url:
        await query.edit_message_text("❌ 画像のアップロードに失敗しました。")
        return

    # Notionページに画像を追加
    caption = f"プロフィール写真 ({datetime.now().strftime('%Y-%m-%d %H:%M')})"
    success = append_image_to_page(page_id, image_url, caption)

    if success:
        context.user_data.pop("pending_photo_file_id", None)
        await query.edit_message_text(
            f"✅ {therapist_name}のNotionページに画像を保存しました！\n\n"
            f"📎 Notion: https://www.notion.so/{page_id.replace('-', '')}"
        )
    else:
        await query.edit_message_text(
            f"❌ Notionへの保存に失敗しました。\n"
            f"NOTION_API_KEY が正しく設定されているか確認してください。"
        )


# ─── 🏪 キャスカン ハブ ──────────────────────────────────
async def handle_caskan_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """キャスカンメニュー"""
    keyboard = [
        [
            InlineKeyboardButton("📊 売上確認", callback_data="caskan:sales"),
            InlineKeyboardButton("📅 スケジュール", callback_data="caskan:schedule"),
        ],
        [
            InlineKeyboardButton("📋 予約一覧", callback_data="caskan:reservations"),
            InlineKeyboardButton("👥 キャスト一覧", callback_data="caskan:casts"),
        ],
        [
            InlineKeyboardButton("🏠 ホーム情報", callback_data="caskan:home"),
        ],
        [
            InlineKeyboardButton("🔗 管理画面を開く", url="https://my.caskan.jp/"),
        ],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        "🏪 【キャスカン ハブ】\n\n"
        "キャスカン管理画面の情報を確認できます。\n"
        "操作を選択してください:",
        reply_markup=reply_markup,
    )


async def handle_caskan_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """キャスカンコールバック処理"""
    query = update.callback_query
    await query.answer()

    data = query.data
    if not data.startswith("caskan:"):
        return

    action = data.replace("caskan:", "")
    caskan = get_caskan()

    if action == "sales" or action == "home":
        await query.edit_message_text("⏳ キャスカンから情報を取得中...")
        info = caskan.get_home_info()

        if "error" in info:
            await query.edit_message_text(f"❌ エラー: {info['error']}")
            return

        sales = info.get("sales", {})
        text_parts = ["🏪 【キャスカン ホーム情報】\n"]

        if sales:
            text_parts.append("📊 売上サマリー:")
            for key, val in sales.items():
                label = {"today": "本日", "yesterday": "昨日", "this_month": "今月", "last_month": "先月"}.get(key, key)
                text_parts.append(f"  {label}: {val}")

        if info.get("attendance_text"):
            text_parts.append(f"\n📢 出勤情報:\n{info['attendance_text']}")

        if info.get("guidance_text"):
            text_parts.append(f"\n📍 案内状況:\n{info['guidance_text']}")

        await query.edit_message_text("\n".join(text_parts))

    elif action == "schedule":
        await query.edit_message_text("⏳ スケジュールを取得中...")
        data = caskan.get_schedule()

        if "error" in data:
            await query.edit_message_text(f"❌ エラー: {data['error']}")
            return

        text = data.get("schedule_text", "情報なし")
        if len(text) > 3500:
            text = text[:3500] + "\n\n... (続きは管理画面で確認)"

        await query.edit_message_text(f"📅 【キャスカン スケジュール】\n{text}")

    elif action == "reservations":
        await query.edit_message_text("⏳ 予約情報を取得中...")
        data = caskan.get_reservations()

        if "error" in data:
            await query.edit_message_text(f"❌ エラー: {data['error']}")
            return

        reservations = data.get("reservations", [])
        if reservations:
            text = "📋 【キャスカン 予約一覧】\n\n"
            for r in reservations[:15]:
                text += f"• {r}\n"
            text += f"\n合計: {data.get('count', 0)}件"
        else:
            text = "📋 【キャスカン 予約一覧】\n\n予約データが見つかりません。"

        if len(text) > 4000:
            text = text[:4000] + "\n..."

        await query.edit_message_text(text)

    elif action == "casts":
        await query.edit_message_text("⏳ キャスト一覧を取得中...")
        casts = caskan.get_cast_list()

        if casts:
            text = "👥 【キャスカン キャスト一覧】\n\n"
            for i, cast in enumerate(casts, 1):
                text += f"{i}. {cast}\n"
        else:
            text = "👥 【キャスカン キャスト一覧】\n\nキャスト情報の取得に失敗しました。"

        if len(text) > 4000:
            text = text[:4000] + "\n..."

        await query.edit_message_text(text)


# ─── 🌟 エスたま ハブ ────────────────────────────────────
async def handle_estama_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """エスたまメニュー"""
    keyboard = [
        [
            InlineKeyboardButton("📊 ダッシュボード", callback_data="estama:dashboard"),
            InlineKeyboardButton("📍 ご案内状況", callback_data="estama:guidance"),
        ],
        [
            InlineKeyboardButton("📅 出勤表", callback_data="estama:schedule"),
            InlineKeyboardButton("📋 予約確認", callback_data="estama:reservations"),
        ],
        [
            InlineKeyboardButton("🎯 ワンクリックアピール", callback_data="estama:appeal"),
        ],
        [
            InlineKeyboardButton("📰 ニュース一覧", callback_data="estama:news"),
        ],
        [
            InlineKeyboardButton("🔗 管理画面を開く", url="https://estama.jp/admin/"),
        ],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        "🌟 【エスたま ハブ】\n\n"
        "エスたま管理画面の情報を確認・操作できます。\n"
        "操作を選択してください:",
        reply_markup=reply_markup,
    )


async def handle_estama_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """エスたまコールバック処理"""
    query = update.callback_query
    await query.answer()

    data = query.data
    if not data.startswith("estama:"):
        return

    action = data.replace("estama:", "")
    estama = get_estama()

    if action == "dashboard":
        await query.edit_message_text("⏳ エスたまから情報を取得中...")
        info = estama.get_dashboard()

        if "error" in info:
            await query.edit_message_text(f"❌ エラー: {info['error']}")
            return

        text_parts = ["🌟 【エスたま ダッシュボード】\n"]

        if info.get("shop_name"):
            text_parts.append(f"🏪 {info['shop_name']}")
        if info.get("access_count"):
            text_parts.append(f"👀 前日アクセス数: {info['access_count']}")
        if info.get("ranking"):
            text_parts.append(f"🏆 ランキング: {info['ranking']}")
        if info.get("guidance_status"):
            text_parts.append(f"📍 案内状況: {info['guidance_status']}")
        if info.get("attendance_count"):
            text_parts.append(f"👥 出勤セラピスト: {info['attendance_count']}")

        if info.get("notifications"):
            text_parts.append("\n🔔 通知:")
            for notif in info["notifications"][:5]:
                text_parts.append(f"  • {notif}")

        await query.edit_message_text("\n".join(text_parts))

    elif action == "guidance":
        await query.edit_message_text("⏳ ご案内状況を取得中...")
        info = estama.get_guidance_status()

        if "error" in info:
            await query.edit_message_text(f"❌ エラー: {info['error']}")
            return

        text = f"📍 【エスたま ご案内状況】\n\nステータス: {info.get('status', '不明')}"
        await query.edit_message_text(text)

    elif action == "schedule":
        await query.edit_message_text("⏳ 出勤表を取得中...")
        data = estama.get_schedule()

        if "error" in data:
            await query.edit_message_text(f"❌ エラー: {data['error']}")
            return

        text = data.get("schedule_text", "情報なし")
        if len(text) > 3500:
            text = text[:3500] + "\n\n... (続きは管理画面で確認)"

        await query.edit_message_text(f"📅 【エスたま 出勤表】\n\n{text}")

    elif action == "reservations":
        await query.edit_message_text("⏳ 予約情報を取得中...")
        data = estama.get_reservations()

        if "error" in data:
            await query.edit_message_text(f"❌ エラー: {data['error']}")
            return

        reservations = data.get("reservations", [])
        if reservations:
            text = "📋 【エスたま 予約一覧】\n\n"
            for r in reservations[:15]:
                text += f"• {r}\n"
            text += f"\n合計: {data.get('count', 0)}件"
        else:
            text = "📋 【エスたま 予約一覧】\n\n予約データが見つかりません。"

        if len(text) > 4000:
            text = text[:4000] + "\n..."

        await query.edit_message_text(text)

    elif action == "appeal":
        # 確認ボタンを表示
        keyboard = [
            [
                InlineKeyboardButton("✅ 実行する", callback_data="estama_confirm:appeal_yes"),
                InlineKeyboardButton("❌ キャンセル", callback_data="estama_confirm:appeal_no"),
            ]
        ]
        await query.edit_message_text(
            "🎯 【集客ワンクリックアピール】\n\n"
            "アピールを実行しますか？\n"
            "エスたまの集客ワンクリックアピールが送信されます。",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

    elif action == "news":
        await query.edit_message_text("⏳ ニュース一覧を取得中...")
        news = estama.get_news_list()

        if news:
            text = "📰 【エスたま ニュース一覧】\n\n"
            for item in news:
                text += f"📌 {item.get('title', '不明')} ({item.get('date', '')})\n"
        else:
            text = "📰 【エスたま ニュース一覧】\n\nニュースが見つかりません。"

        await query.edit_message_text(text)


async def handle_estama_confirm_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """エスたま確認コールバック"""
    query = update.callback_query
    await query.answer()

    data = query.data
    if not data.startswith("estama_confirm:"):
        return

    action = data.replace("estama_confirm:", "")

    if action == "appeal_yes":
        await query.edit_message_text("⏳ アピールを実行中...")
        estama = get_estama()
        success = estama.click_appeal()

        if success:
            await query.edit_message_text("✅ 集客ワンクリックアピールを実行しました！")
        else:
            await query.edit_message_text(
                "❌ アピールの実行に失敗しました。\n"
                "エスたま管理画面から直接実行してください。\n"
                "🔗 https://estama.jp/admin/"
            )

    elif action == "appeal_no":
        await query.edit_message_text("❌ アピールをキャンセルしました。")


# ─── その他 ──────────────────────────────────────────────
async def handle_unknown(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """未知のテキストメッセージ"""
    await update.message.reply_text(
        "メニューから操作を選んでください。\n"
        "📸 画像を送信するとセラピストのNotionに保存できます。",
        reply_markup=MENU_KEYBOARD,
    )


# ─── メイン ─────────────────────────────────────────────
def main() -> None:
    """ボットを起動する"""
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

    # メニューボタン — テキストメッセージ
    app.add_handler(
        MessageHandler(filters.Regex(r"^📢 出勤ツイート$"), handle_attendance_tweet)
    )
    app.add_handler(
        MessageHandler(filters.Regex(r"^📅 スケジュール確認$"), handle_schedule_check)
    )
    app.add_handler(
        MessageHandler(filters.Regex(r"^👤 プロフィール作成$"), handle_profile_create)
    )
    app.add_handler(
        MessageHandler(filters.Regex(r"^📸 写真管理$"), handle_photo_menu)
    )
    app.add_handler(
        MessageHandler(filters.Regex(r"^🏪 キャスカン$"), handle_caskan_menu)
    )
    app.add_handler(
        MessageHandler(filters.Regex(r"^🌟 エスたま$"), handle_estama_menu)
    )

    # 画像メッセージ — 写真管理
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))

    # インラインボタンコールバック
    app.add_handler(CallbackQueryHandler(handle_photo_save_callback, pattern=r"^photo_save:"))
    app.add_handler(CallbackQueryHandler(handle_caskan_callback, pattern=r"^caskan:"))
    app.add_handler(CallbackQueryHandler(handle_estama_callback, pattern=r"^estama:"))
    app.add_handler(CallbackQueryHandler(handle_estama_confirm_callback, pattern=r"^estama_confirm:"))

    # その他のテキストメッセージ
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_unknown))

    # ポーリング開始
    logger.info("全力エステBot を起動しました。Ctrl+C で停止します。")
    app.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True,
        poll_interval=2.0,
        bootstrap_retries=5,
    )


if __name__ == "__main__":
    main()

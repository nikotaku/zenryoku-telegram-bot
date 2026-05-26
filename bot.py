import os
from dotenv import load_dotenv
load_dotenv()
#!/usr/bin/env python3
"""
全力エステ Telegram Bot (@zenryoku_bot)
機能:
  - /start  : メインメニューを表示
  - /news   : ニュース投稿文面を生成
  - /images : 画像管理（セラピスト写真をNotionに保存）
  - /expense: 経費を入力してGoogleスプレッドシートに記録
"""

import os
import logging
from datetime import datetime, time
import pytz

from telegram import (
    Update,
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    BotCommand,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)
from telegram.request import HTTPXRequest

from notion_client import (
    get_therapist_list,
    get_therapist_page_id,
    append_image_to_page,
)
from sheets_client import append_expense_to_sheet
from image_uploader import upload_telegram_photo
from seo_article import (
    generate_seo_article,
    get_template_preview,
    SEO_CHECKLIST,
    TEMPLATE_1_INFO,
    TEMPLATE_2_INFO,
)

import browser_agent
import notion_shift_client
from datetime import datetime, time
import pytz
from bitbank_client import (
    get_portfolio,
    format_portfolio_message,
    get_ticker,
    get_asset_free_amount,
    place_market_order,
    JPY_PAIRS,
    ASSET_NAMES,
    AMOUNT_PRECISION,
)

# ─── 設定 ───────────────────────────────────────────────
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
PHOTO_CHANNEL_ID = int(os.environ.get("PHOTO_CHANNEL_ID", "-5269472642"))

if not BOT_TOKEN:
    raise ValueError("環境変数 TELEGRAM_BOT_TOKEN が設定されていません")

# ログ設定
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

try:
    import rion_auto_poster
    RION_ENABLED = True
except ImportError as e:
    logger.warning(f"rion_auto_poster import失敗（tweepy未インストール？）: {e}")
    RION_ENABLED = False


# ─── ブログ一斉投稿 ConversationHandler ステート ────────────────
POST_NAME, POST_TEMPLATE, POST_TITLE, POST_BODY, POST_PHOTO = range(20, 25)
POST_TITLE_FREE = 25  # 自由入力タイトル待ち
POST_DRIVE_CAT = 26   # Drive カテゴリ選択待ち
POST_DRIVE_FOLDER = 27  # Drive フォルダ内画像選択待ち

# タイトルプリセット
POST_TITLE_PRESETS = [
    "本日の出勤情報",
    "お礼日記",
    "お知らせ",
    "キャンペーン情報",
    "新人セラピスト紹介",
    "スタッフ日記",
]

# ─── 出稼ぎスケジュール登録 ConversationHandler ステート ────────────────
GUEST_NAME, GUEST_START_DATE, GUEST_END_DATE, GUEST_START_TIME, GUEST_END_TIME, GUEST_EXPENSE, GUEST_X_ACCOUNT = range(10, 17)

def get_calendar_keyboard(year: int, month: int, prefix: str):
    import calendar
    keyboard = []
    
    # ヘッダー (年月)
    keyboard.append([
        InlineKeyboardButton("<", callback_data=f"{prefix}:prev:{year}:{month}"),
        InlineKeyboardButton(f"{year}年{month}月", callback_data="ignore"),
        InlineKeyboardButton(">", callback_data=f"{prefix}:next:{year}:{month}")
    ])
    
    # 曜日
    week_days = ["月", "火", "水", "木", "金", "土", "日"]
    keyboard.append([InlineKeyboardButton(day, callback_data="ignore") for day in week_days])
    
    # カレンダー本体
    cal = calendar.monthcalendar(year, month)
    for week in cal:
        row = []
        for day in week:
            if day == 0:
                row.append(InlineKeyboardButton(" ", callback_data="ignore"))
            else:
                date_str = f"{year}-{month:02d}-{day:02d}"
                row.append(InlineKeyboardButton(str(day), callback_data=f"{prefix}:select:{date_str}"))
        keyboard.append(row)
        
    return InlineKeyboardMarkup(keyboard)

def get_time_keyboard(prefix: str):
    keyboard = []
    times = ["11:00", "12:00", "13:00", "14:00", "15:00", "16:00", "17:00", "18:00", "19:00", "20:00", "21:00", "22:00", "23:00", "24:00", "25:00", "26:00"]
    row = []
    for t in times:
        row.append(InlineKeyboardButton(t, callback_data=f"{prefix}:select:{t}"))
        if len(row) == 4:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    return InlineKeyboardMarkup(keyboard)

# ─── 経費入力 ConversationHandler ステート ────────────────
EXPENSE_DATE, EXPENSE_AMOUNT, EXPENSE_CONTENT, EXPENSE_MEMO = range(4)


# ─── メニューキーボード ─────────────────────────────────
MENU_KEYBOARD = ReplyKeyboardMarkup(
    [
        [KeyboardButton("📲 ブログ一斉投稿")],
        [KeyboardButton("💼 出稼ぎスケジュール登録")],
        [KeyboardButton("📸 画像管理"), KeyboardButton("💴 経費を入力")],
        [KeyboardButton("🗣️ AIでシフト操作"), KeyboardButton("🤖 エージェント")],
        [KeyboardButton("💰 仮想通貨"), KeyboardButton("📅 シフトDB")],
        [KeyboardButton("🔗 掲載ページ確認"), KeyboardButton("⚙️ 各種管理画面")],
        [KeyboardButton("🌸 りおん自動運用")],
    ],
    resize_keyboard=True,
    one_time_keyboard=False,
)

# メニューボタンの正規表現（会話状態でも常に効くようにするため）
MENU_BUTTONS_REGEX = r"^(📲 ブログ一斉投稿|💼 出稼ぎスケジュール登録|📸 画像管理|💴 経費を入力|🗣️ AIでシフト操作|🤖 エージェント|💰 仮想通貨|📅 シフトDB|🔗 掲載ページ確認|⚙️ 各種管理画面|🌸 りおん自動運用|❌ キャンセル|/start|/cancel)$"


async def force_exit_conv(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """会話を強制終了してメニューに戻す。メッセージ自体は他ハンドラに渡らないので、押し直しを促す。"""
    text = update.message.text if update.message else ""
    await update.message.reply_text(
        f"⏹ 進行中の操作を中断しました。\n「{text}」をもう一度押してください。"
    )
    return ConversationHandler.END

# Notion セラピストDB URL
NOTION_THERAPIST_DB_URL = "https://www.notion.so/20af9507f0cf811a9397000b1fd6918d"

# Notionリンクボタン付きメインメニュー
MENU_INLINE_KEYBOARD = InlineKeyboardMarkup([
    [InlineKeyboardButton("🗒 Notion セラピスト一覧", url=NOTION_THERAPIST_DB_URL)],
])

# ─── /start コマンド ───────────────────────────────────────────

async def handle_api_update(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = (
        "【APIキー更新手順】\n\n"
        "1. Termiusを開き、サーバー(162.43.7.223)に接続\n"
        "2. 黒い画面の末尾に以下を貼り付けてEnter\n\n"
        "`update_api 新しいAPIキー`\n\n"
        "※例: `update_api AIzaSyAum9UY0Y1na...`\n\n"
        "実行後、数秒でBotが再起動して復旧します。"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/start — メインメニューを表示"""
    await update.message.reply_text(
        "💫 全力エステ Botへようこそ！\n\n"
        "下のメニューから操作を選んでください。\n\n"
        "📅 シフトDB\n"
        "　NotionシフトDBをマスタに、キャスカン・エスたまへ同期\n\n"
        "🤖 エージェント\n"
        "　自然言語でシフト登録・同期操作（例: 『明日りおんをキャスカンに登録』）\n\n"
        "💰 仮想通貨\n"
        "　bitbankの保有資産を確認\n\n"
        "💴 経費を入力\n"
        "　Googleスプレッドシートに経費を記録\n\n"
        "📸 画像管理\n"
        "　セラピスト写真をGoogle Driveに保存・取得",
        reply_markup=MENU_KEYBOARD,
    )


# ─── /news コマンド ─────────────────────────────────────
async def handle_news(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """ニュース投稿文面を生成"""
    await update.message.reply_text(
        "📰 【ニュース生成】\n\n"
        "エスたま用のニュース投稿文面を生成します。\n\n"
        "生成したいニュースの内容・テーマを入力してください。\n"
        "例: 「新人セラピスト紹介」「期間限定クーポン」「お盆期間の営業案内」",
        reply_markup=MENU_KEYBOARD,
    )
    context.user_data["awaiting_news_topic"] = True


async def handle_news_topic(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """ニューストピックを受け取って文面を生成"""
    if not context.user_data.get("awaiting_news_topic"):
        return False

    topic = update.message.text.strip()
    context.user_data.pop("awaiting_news_topic", None)

    # Gemini APIでニュース文面を生成
    try:
        import google.generativeai as genai
        genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))

        model = genai.GenerativeModel("gemini-2.5-flash")

        system_prompt = (
            "あなたは仙台のメンズエステ「全力エステ」のスタッフです。"
            "エスたま（メンズエステポータルサイト）のニュース投稿文面を作成してください。"
            "タイトルは30文字以内、本文は1000〜1500文字で作成してください。"
            "文体は丁寧で親しみやすく、集客効果が高い内容にしてください。"
            "出力形式: 【タイトル】と【本文】を分けて記載してください。"
        )

        response = model.generate_content(
            contents=[{"role": "user", "parts": [{"text": f"{system_prompt}\n\nテーマ: {topic}"}]}],
            generation_config=genai.types.GenerationConfig(
                max_output_tokens=1500,
            ),
        )
        result = response.text
        await update.message.reply_text(
            f"📰 【ニュース文面】\n\n{result}",
            reply_markup=MENU_KEYBOARD,
        )
    except Exception as e:
        logger.error(f"ニュース生成エラー: {e}")
        await update.message.reply_text(
            "📰 ニュース文面の生成に失敗しました。\n"
            "GEMINI_API_KEY が設定されているか確認してください。",
            reply_markup=MENU_KEYBOARD,
        )
    return True


# ─── /images コマンド（写真管理） ────────────────────────
async def handle_images(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/images コマンド — 写真管理メニュー"""
    keyboard = [
        [InlineKeyboardButton("⬆️ 画像アップロード", callback_data="img_up")],
        [InlineKeyboardButton("⬇️ 画像ダウンロード", callback_data="img_dl")]
    ]
    await update.message.reply_text(
        "📸 【画像管理】\n\n操作を選択してください。\n※アップロードする場合は、このまま画像を送信するだけでも可能です。",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """画像が送信された時の処理 — photo_storageのカテゴリ選択を表示"""
    if not update.message.photo:
        return

    file_id = update.message.photo[-1].file_id
    context.user_data["pending_photo_file_id"] = file_id

    from photo_storage import get_all_names
    names = get_all_names()

    keyboard = []
    row = []
    for name in names:
        row.append(InlineKeyboardButton(name[:15], callback_data=f"photo_save:{name}"))
        if len(row) == 3:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    keyboard.append([InlineKeyboardButton("➕ 新しいカテゴリ名で保存", callback_data="photo_save:__new__")])
    keyboard.append([InlineKeyboardButton("❌ キャンセル", callback_data="photo_save:cancel")])

    await update.message.reply_text(
        "📸 画像を受け取りました！\n\n保存先を選択してください:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )



async def handle_img_up_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    await query.message.reply_text("📷 アップロードしたい画像を送信してください。送信後、保存先のセラピストを選択できます。")

async def handle_img_dl_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """画像DL: photo_storageのカテゴリ一覧を表示"""
    query = update.callback_query
    await query.answer()

    from photo_storage import get_all_names
    names = get_all_names()

    if not names:
        await query.edit_message_text(
            "📭 登録済みの写真がありません。\n\n"
            "チャンネルに写真を「セラピスト名」キャプション付きで投稿すると自動登録されます。",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("❌ 閉じる", callback_data="dl_therapist:cancel")
            ]])
        )
        return

    keyboard = []
    row = []
    for name in names:
        row.append(InlineKeyboardButton(name[:14], callback_data=f"dl_photo:{name}"))
        if len(row) == 3:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    keyboard.append([InlineKeyboardButton("❌ キャンセル", callback_data="dl_therapist:cancel")])

    await query.edit_message_text(
        "⬇️ 【画像ダウンロード】\nカテゴリを選択してください：",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def handle_dl_photo_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """選択したカテゴリの写真を全件送信"""
    query = update.callback_query
    await query.answer()
    name = query.data.replace("dl_photo:", "")

    from photo_storage import get_photos
    file_ids = get_photos(name)

    if not file_ids:
        await query.edit_message_text(f"❌ {name}の写真が登録されていません。")
        return

    await query.edit_message_text(f"⏳ {name}の写真 {len(file_ids)}枚を送信中...")
    success = 0
    for fid in file_ids:
        try:
            await context.bot.send_photo(chat_id=query.message.chat_id, photo=fid, caption=name)
            success += 1
        except Exception as e:
            logger.error(f"写真送信エラー {fid}: {e}")

    await query.message.reply_text(f"✅ {name}の写真 {success}枚を送信しました。")


async def handle_channel_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """チャンネルへの写真投稿を受け取ってphoto_storageに登録"""
    post = update.channel_post
    if not post or post.chat.id != PHOTO_CHANNEL_ID:
        return
    if not post.photo:
        return
    caption = (post.caption or "").strip()
    if not caption:
        logger.warning("チャンネル写真にキャプションなし: スキップ")
        return
    file_id = post.photo[-1].file_id
    from photo_storage import add_photo
    add_photo(caption, file_id)
    logger.info(f"チャンネル写真登録: {caption}")


async def handle_dl_cat_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """フォルダを開く: サブフォルダがあれば一覧、なければ画像を全件送信"""
    query = update.callback_query
    await query.answer()

    parts = query.data.replace("dl_cat:", "").split(":", 1)
    folder_id = parts[0]
    folder_name = parts[1] if len(parts) > 1 else folder_id

    await query.edit_message_text(f"⏳ {folder_name} を確認中...")

    import asyncio as _asyncio
    from image_uploader import list_drive_folders, get_image_list_by_folder_id, download_image_from_drive

    # サブフォルダ確認
    try:
        subfolders = await _asyncio.wait_for(
            _asyncio.get_running_loop().run_in_executor(None, list_drive_folders, folder_id),
            timeout=8.0
        )
    except Exception:
        subfolders = []

    if subfolders:
        keyboard = []
        row = []
        for f in subfolders:
            row.append(InlineKeyboardButton(
                f["name"][:14],
                callback_data=f"dl_cat:{f['id']}:{f['name'][:12]}"
            ))
            if len(row) == 3:
                keyboard.append(row)
                row = []
        if row:
            keyboard.append(row)
        keyboard.append([
            InlineKeyboardButton("🔙 戻る", callback_data="img_dl"),
            InlineKeyboardButton("❌ キャンセル", callback_data="dl_therapist:cancel"),
        ])
        await query.edit_message_text(
            f"📁 {folder_name}\nフォルダを選択してください：",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    # 画像を直接送信
    await query.edit_message_text(f"⏳ {folder_name}の画像を取得中...")
    try:
        files = await _asyncio.wait_for(
            _asyncio.get_event_loop().run_in_executor(None, get_image_list_by_folder_id, folder_id, 50),
            timeout=30.0
        )
    except _asyncio.TimeoutError:
        await query.edit_message_text("❌ タイムアウト（30秒）。")
        return
    except Exception as e:
        await query.edit_message_text(f"❌ 取得エラー: {str(e)[:200]}")
        return

    if not files:
        await query.edit_message_text(
            f"❌ {folder_name}に画像がありません。\n\n"
            "・Driveフォルダがサービスアカウントに未共有\n"
            "・フォルダに画像がない"
        )
        return

    await query.edit_message_text(f"⏳ {folder_name}の画像 {len(files)}枚を送信中...")

    success = 0
    for f in files:
        try:
            img_bytes = await _asyncio.wait_for(
                _asyncio.get_event_loop().run_in_executor(None, download_image_from_drive, f["id"]),
                timeout=60.0
            )
            if img_bytes:
                await context.bot.send_photo(
                    chat_id=query.message.chat_id,
                    photo=img_bytes,
                    caption=f["name"]
                )
                success += 1
        except Exception as e:
            logger.error(f"DL error {f['id']}: {e}")

    if success:
        await query.message.reply_text(f"✅ {folder_name}の画像 {success}枚を送信しました。")
    else:
        await query.message.reply_text("❌ 画像の送信に失敗しました。")


async def handle_dl_therapist_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """dl_therapist:cancel のみ処理（旧互換）"""
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("❌ ダウンロードをキャンセルしました。")


async def handle_photo_save_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """カテゴリ選択コールバック — photo_storageに保存してチャンネルに転送"""
    query = update.callback_query
    await query.answer()

    data = query.data.replace("photo_save:", "")

    if data == "cancel":
        context.user_data.pop("pending_photo_file_id", None)
        await query.edit_message_text("❌ 写真の保存をキャンセルしました。")
        return

    if data == "__new__":
        context.user_data["photo_save_awaiting_name"] = True
        await query.edit_message_text("📝 新しいカテゴリ名を入力してください（例：りな、スクエアバナー）：")
        return

    file_id = context.user_data.get("pending_photo_file_id")
    if not file_id:
        await query.edit_message_text("⚠️ 保存する画像が見つかりません。もう一度送信してください。")
        return

    await _save_photo_to_storage(query.edit_message_text, context, file_id, data)


async def handle_photo_name_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """新しいカテゴリ名の入力を受け取る"""
    if not context.user_data.get("photo_save_awaiting_name"):
        return
    context.user_data.pop("photo_save_awaiting_name", None)
    name = update.message.text.strip()
    file_id = context.user_data.get("pending_photo_file_id")
    if not file_id:
        await update.message.reply_text("⚠️ 保存する画像が見つかりません。もう一度送信してください。")
        return
    await _save_photo_to_storage(update.message.reply_text, context, file_id, name)


async def _save_photo_to_storage(reply_fn, context, file_id: str, name: str):
    """photo_storageに登録してチャンネルに転送"""
    from photo_storage import add_photo
    add_photo(name, file_id)
    context.user_data.pop("pending_photo_file_id", None)

    # チャンネルに転送（他デバイスからも参照できるようにする）
    try:
        await context.bot.send_photo(
            chat_id=PHOTO_CHANNEL_ID,
            photo=file_id,
            caption=name
        )
    except Exception as e:
        logger.warning(f"チャンネル転送失敗: {e}")

    await reply_fn(f"✅ 「{name}」に写真を保存しました！")


# ─── 写メ日記テンプレート ────────────────────────────────
# Notionから取得した8種のテンプレートをハードコード（高速表示のため）
PHOTO_DIARY_TEMPLATES = [
    {
        "id": "1",
        "title": "1️⃣ お礼日記（新規・リピーター向け）",
        "short": "○○さん、ありがとうございました",
        "text": (
            "○○さん、本日はご来店ありがとうございました\n"
            "初めてで緊張したと思いますが、最後はリラックスした表情を見られて嬉しかったです\n"
            "お仕事の話、とても興味深かったです！また色々聞かせてくださいね\n"
            "寒いので暖かくして休んでください。またお会いできるのを楽しみにしています"
        ),
    },
    {
        "id": "2",
        "title": "2️⃣ 出勤告知",
        "short": "本日出勤します 会いに来てね",
        "text": (
            "こんにちは！○○です\n"
            "本日《18:00〜24:00》で出勤します！\n"
            "急に寒くなりましたね…人肌恋しい季節、○○が心を込めて温めます\n"
            "お仕事で疲れた心と体を癒しに来てくださいね。\n"
            "ご予約お待ちしております"
        ),
    },
    {
        "id": "3",
        "title": "3️⃣ 自己紹介（新人向け）",
        "short": "はじめまして！新人セラピストの○○です",
        "text": (
            "はじめまして！\n"
            "この度、○○（店名）でお世話になることになりました、新人の○○です\n"
            "マッサージは勉強中ですが、お客様に癒しをお届けしたい気持ちは誰にも負けません！\n"
            "趣味はアニメを見ることで、休日は一日中見ています(笑)\n"
            "おすすめのアニメがあったらぜひ教えてください\n"
            "緊張でガチガチかもしれませんが、優しくしていただけると嬉しいです\n"
            "皆様にお会いできるのを楽しみにしています！"
        ),
    },
    {
        "id": "4",
        "title": "4️⃣ 日常投稿（親近感UP）",
        "short": "最近ハマってること",
        "text": (
            "お疲れ様です、○○です\n"
            "最近、○○にハマっていて、昨日も食べちゃいました\n"
            "本当に美味しくて、毎日でも食べたいくらい…！\n"
            "皆さんの最近のマイブームは何ですか？\n"
            "今度お店に来た時に、ぜひ教えてくださいね"
        ),
    },
    {
        "id": "5",
        "title": "5️⃣ クーポン告知（店舗型）",
        "short": "エス魂限定！特別クーポン",
        "text": (
            "ご覧いただきましてありがとうございます\n"
            "1万円以内で厳選されたセラピストと夢のような癒しのひとときをお過ごし頂けます\n\n"
            "オトクなクーポン情報\n"
            "【お得に70分お試しコース】\n"
            "通常60分 10,000円 → 70分 10,000円（時間延長）\n\n"
            "ご利用条件：予約時にエステ魂のクーポン利用とお伝えください\n\n"
            "店名：○○\n"
            "営業時間：○○\n"
            "電話番号：○○"
        ),
    },
    {
        "id": "6",
        "title": "6️⃣ 癒されたいお客様向けお礼",
        "short": "今日もありがとうございました",
        "text": (
            "今日もありがとうございました！\n"
            "○○さんの笑顔に、私の方が癒されちゃいました(笑)\n"
            "またいつでもリフレッシュしに来てくださいね！\n"
            "心よりお待ちしております"
        ),
    },
    {
        "id": "7",
        "title": "7️⃣ おやすみ日記",
        "short": "今日はゆっくり休みます",
        "text": (
            "お疲れ様です、○○です！\n"
            "今日は一日お休みをいただいています。\n"
            "明日からまた元気に頑張りますので、ぜひ会いに来てくださいね！\n"
            "皆様も良い夜をお過ごしください"
        ),
    },
    {
        "id": "8",
        "title": "8️⃣ 出勤前の一言",
        "short": "もうすぐ出勤です！",
        "text": (
            "皆様こんにちは、○○です！\n"
            "もうすぐ出勤します。今日も一日、心を込めて皆様を癒します！\n"
            "ぜひお立ち寄りください。お待ちしております！"
        ),
    },
]


async def handle_photo_diary(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """写メ日記テンプレートメニューを表示"""
    keyboard = []
    for template in PHOTO_DIARY_TEMPLATES:
        keyboard.append([InlineKeyboardButton(template["title"], callback_data=f"diary:{template['id']}")])

    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        "📓 【写メ日記テンプレート】\n\n"
        "投稿したいテンプレートを選択してください。\n"
        "選択すると、文面が表示されます。",
        reply_markup=reply_markup,
    )


async def handle_diary_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """テンプレート詳細を表示"""
    query = update.callback_query
    await query.answer()

    template_id = query.data.replace("diary:", "")
    template = next((t for t in PHOTO_DIARY_TEMPLATES if t["id"] == template_id), None)

    if not template:
        await query.edit_message_text("⚠️ テンプレートが見つかりません。")
        return

    message_text = (
        f"📓 【{template['title']}】\n\n"
        f"タイトル:\n{template['short']}\n\n"
        f"本文:\n{template['text']}\n\n"
        "👆 この文面をコピーしてエスたまの写メ日記投稿にお使いください。"
    )

    keyboard = [[InlineKeyboardButton("🔙 戻る", callback_data="diary:back")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(message_text, reply_markup=reply_markup)


async def handle_diary_back_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """テンプレート一覧に戻る"""
    query = update.callback_query
    await query.answer()

    keyboard = []
    for template in PHOTO_DIARY_TEMPLATES:
        keyboard.append([InlineKeyboardButton(template["title"], callback_data=f"diary:{template['id']}")])

    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(
        "📓 【写メ日記テンプレート】\n\n"
        "投稿したいテンプレートを選択してください。\n"
        "選択すると、文面が表示されます。",
        reply_markup=reply_markup,
    )




# ─── ブログ一斉投稿ハンドラー ─────────────────────────────────────
async def post_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()

    keyboard = []
    for preset in POST_TITLE_PRESETS:
        keyboard.append([InlineKeyboardButton(preset, callback_data=f"post_title:{preset}")])
    keyboard.append([InlineKeyboardButton("✏️ 自由入力", callback_data="post_title:__free__")])
    keyboard.append([InlineKeyboardButton("❌ キャンセル", callback_data="post_title:__cancel__")])

    await update.message.reply_text(
        "📲 【ブログ一斉投稿】\n\n"
        "HP・エスたま・02に一斉投稿します。\n\n"
        "【タイトル】を選択してください：",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return POST_NAME


async def post_name_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """タイトル選択コールバック"""
    query = update.callback_query
    await query.answer()

    data = query.data.replace("post_title:", "")
    if data == "__cancel__":
        await query.edit_message_text("❌ 一斉投稿をキャンセルしました。")
        return ConversationHandler.END

    if data == "__free__":
        await query.edit_message_text("✏️ タイトルを入力してください：")
        return POST_TITLE_FREE

    context.user_data["post_title"] = data
    await query.edit_message_text(
        f"✅ タイトル：{data}\n\n【本文】を入力してください："
    )
    return POST_BODY


async def post_title_free_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """自由入力タイトル受付"""
    text = update.message.text.strip()
    if text == "キャンセル":
        await update.message.reply_text("❌ 一斉投稿をキャンセルしました。", reply_markup=MENU_KEYBOARD)
        return ConversationHandler.END
    context.user_data["post_title"] = text
    await update.message.reply_text(f"✅ タイトル：{text}\n\n【本文】を入力してください：")
    return POST_BODY


async def post_body_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    if text == "キャンセル":
        await update.message.reply_text("❌ 一斉投稿をキャンセルしました。", reply_markup=MENU_KEYBOARD)
        return ConversationHandler.END

    context.user_data["post_body"] = text
    title = context.user_data["post_title"]

    from photo_storage import get_all_names
    names = get_all_names()

    rows = []
    row = []
    for name in names:
        row.append(InlineKeyboardButton(name[:14], callback_data=f"post_ch:{name}"))
        if len(row) == 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton("📷 写真を直接送る", callback_data="post_photo:manual")])
    rows.append([InlineKeyboardButton("📤 画像なしで投稿", callback_data="post_photo:skip")])

    msg = (
        f"✅ 本文を設定しました。\n\n"
        f"【タイトル】{title}\n"
        f"【本文】{text[:100]}{'...' if len(text) > 100 else ''}\n\n"
    )
    if names:
        msg += "📸 カテゴリを選ぶか、写真を直接送ってください："
    else:
        msg += "📷 写真を直接送るか、画像なしで投稿してください\n（先にチャンネルに写真を登録してください）"

    await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(rows))
    return POST_PHOTO


async def _execute_post(title: str, body: str, image_bytes: bytes | None, send_msg) -> str:
    """HP/エスたま/02に一斉投稿して結果テキストを返す"""
    results = []

    try:
        from caskan_browser import CaskanBrowser
        caskan = CaskanBrowser()
        r = await caskan.post_news(title=title, body=body)
        results.append(f"{'✅' if r.get('success') else '❌'} HP(キャスカン): {r.get('message','')}")
    except Exception as e:
        results.append(f"❌ HP(キャスカン): {str(e)[:80]}")
    finally:
        try: await caskan.close()
        except: pass

    try:
        import asyncio as _asyncio
        from estama_client import EstamaClient
        estama = EstamaClient()
        r = await _asyncio.get_event_loop().run_in_executor(
            None, estama.post_diary, title, body, image_bytes or b""
        )
        results.append(f"{'✅' if r.get('success') else '❌'} エスたま: {r.get('message','')}")
    except Exception as e:
        results.append(f"❌ エスたま: {str(e)[:80]}")

    try:
        import tempfile, os as _os
        from zerotwo_browser import ZeroTwoBrowser
        zerotwo = ZeroTwoBrowser()
        image_path = None
        if image_bytes:
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".jpg")
            tmp.write(image_bytes)
            tmp.close()
            image_path = tmp.name
        full_content = f"【{title}】\n\n{body}"
        r = await zerotwo.post_news(content=full_content, image_path=image_path)
        results.append(f"{'✅' if r.get('success') else '❌'} 02: {r.get('message','')}")
        if image_path:
            try: _os.unlink(image_path)
            except: pass
    except Exception as e:
        results.append(f"❌ 02: {str(e)[:80]}")
    finally:
        try: await zerotwo.close()
        except: pass

    result_text = "\n".join(results)
    await send_msg(
        f"📲 【一斉投稿 完了】\n\n"
        f"タイトル: {title}\n\n"
        f"{result_text}",
        reply_markup=MENU_KEYBOARD
    )
    return result_text


async def post_channel_name_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """チャンネル写真カテゴリ選択 → 写真一覧を表示して選択させる"""
    query = update.callback_query
    await query.answer()
    name = query.data.replace("post_ch:", "")

    from photo_storage import get_photos
    file_ids = get_photos(name)

    if not file_ids:
        await query.edit_message_text(
            f"❌ {name}の写真が登録されていません。\n"
            "チャンネルに写真を投稿してください。",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 戻る", callback_data="post_ch_back")
            ]])
        )
        return POST_PHOTO

    await query.edit_message_text(f"📸 {name}の写真（{len(file_ids)}枚）を送信します...")

    for i, fid in enumerate(file_ids[-10:], 1):
        try:
            await query.message.reply_photo(
                photo=fid,
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton(f"✅ この写真を使う", callback_data=f"post_ch_pick:{fid}")
                ]])
            )
        except Exception as e:
            logger.error(f"写真送信エラー: {e}")

    await query.message.reply_text(
        "上の写真から選んでください。",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📤 画像なしで投稿", callback_data="post_photo:skip")],
        ])
    )
    return POST_PHOTO


async def post_channel_pick_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """チャンネル写真を選択して一斉投稿"""
    query = update.callback_query
    await query.answer()
    file_id = query.data.replace("post_ch_pick:", "")
    title = context.user_data.get("post_title", "")
    body = context.user_data.get("post_body", "")

    await query.edit_message_reply_markup(reply_markup=None)
    msg = await query.message.reply_text("⏳ 写真をダウンロード中...")

    try:
        tg_file = await context.bot.get_file(file_id)
        import io, httpx
        async with httpx.AsyncClient() as client:
            resp = await client.get(tg_file.file_path, timeout=30)
        image_bytes = resp.content
    except Exception as e:
        await msg.edit_text(f"❌ 写真取得エラー: {str(e)[:100]}")
        return POST_PHOTO

    await msg.edit_text(f"⏳ 「{title}」を一斉投稿中...")
    await _execute_post(title, body, image_bytes, msg.reply_text)
    return ConversationHandler.END


async def post_ch_back_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """写真選択から戻る"""
    query = update.callback_query
    await query.answer()
    from photo_storage import get_all_names
    names = get_all_names()
    title = context.user_data.get("post_title", "")
    body = context.user_data.get("post_body", "")
    rows = []
    row = []
    for name in names:
        row.append(InlineKeyboardButton(name[:14], callback_data=f"post_ch:{name}"))
        if len(row) == 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton("📷 写真を直接送る", callback_data="post_photo:manual")])
    rows.append([InlineKeyboardButton("📤 画像なしで投稿", callback_data="post_photo:skip")])
    await query.edit_message_text(
        f"【タイトル】{title}\n【本文】{body[:80]}...\n\n📸 カテゴリを選んでください：",
        reply_markup=InlineKeyboardMarkup(rows)
    )
    return POST_PHOTO

    await query.edit_message_text(f"⏳ 「{title}」を一斉投稿中...")
    await _execute_post(title, body, image_bytes, query.message.reply_text)
    return ConversationHandler.END


async def post_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    title = context.user_data.get("post_title", "")
    body = context.user_data.get("post_body", "")
    image_bytes = None

    if update.callback_query:
        data = update.callback_query.data
        await update.callback_query.answer()
        if data == "post_photo:manual":
            await update.callback_query.edit_message_text(
                "📷 写真を送信してください："
            )
            return POST_PHOTO
        # post_photo:skip → post without image
        await update.callback_query.edit_message_text(f"⏳ 「{title}」を一斉投稿中...")
        send_msg = update.callback_query.message.reply_text
    else:
        if not update.message.photo:
            await update.message.reply_text("⚠️ 写真を送信するか「画像なしで投稿」を押してください。")
            return POST_PHOTO
        photo = update.message.photo[-1]
        tg_file = await context.bot.get_file(photo.file_id)
        import requests as _req
        url = tg_file.file_path if tg_file.file_path.startswith("http") else f"https://api.telegram.org/file/bot{context.bot.token}/{tg_file.file_path}"
        image_bytes = _req.get(url, timeout=30).content
        await update.message.reply_text(f"⏳ 「{title}」を一斉投稿中...")
        send_msg = update.message.reply_text

    await _execute_post(title, body, image_bytes, send_msg)
    return ConversationHandler.END


async def post_photo_skip(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """画像なしで投稿ボタン"""
    return await post_photo(update, context)

# ─── 出稼ぎスケジュール登録ハンドラー ─────────────────────────────────────
async def guest_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()  # リセット
    
    therapists = get_therapist_list()
    keyboard = []
    row = []
    for name in therapists:
        row.append(InlineKeyboardButton(name, callback_data=f"guest_name:{name}"))
        if len(row) == 3:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    keyboard.append([InlineKeyboardButton("❌ キャンセル", callback_data="guest_name:cancel")])
    
    await update.message.reply_text(
        "💼 【出稼ぎスケジュール登録】\n\n"
        "登録するセラピスト（源氏名）を選択してください：",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return GUEST_NAME

async def guest_name_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    
    if not query.data.startswith("guest_name:"):
        return GUEST_NAME
        
    name = query.data.replace("guest_name:", "")
    if name == "cancel":
        await query.edit_message_text("❌ 登録をキャンセルしました。")
        return ConversationHandler.END
        
    context.user_data["guest_name"] = name
    
    now = datetime.now()
    keyboard = get_calendar_keyboard(now.year, now.month, "guest_start_date")
    
    await query.edit_message_text(
        f"✅ 選択: {name}\n\n"
        "次に、【開始日】をカレンダーから選択してください：",
        reply_markup=keyboard
    )
    return GUEST_START_DATE

async def guest_start_date_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    
    data = query.data.split(":")
    if len(data) < 3 or data[0] != "guest_start_date":
        return GUEST_START_DATE
        
    action = data[1]
    
    if action in ["prev", "next"]:
        year, month = int(data[2]), int(data[3])
        if action == "prev":
            month -= 1
            if month == 0:
                month = 12
                year -= 1
        else:
            month += 1
            if month == 13:
                month = 1
                year += 1
        keyboard = get_calendar_keyboard(year, month, "guest_start_date")
        await query.edit_message_reply_markup(reply_markup=keyboard)
        return GUEST_START_DATE
        
    elif action == "select":
        date_str = data[2]
        context.user_data["guest_start_date"] = date_str
        
        # 終了日選択へ
        d = datetime.strptime(date_str, "%Y-%m-%d")
        keyboard = get_calendar_keyboard(d.year, d.month, "guest_end_date")
        await query.edit_message_text(
            f"✅ 開始日: {date_str}\n\n"
            "次に、【終了日】をカレンダーから選択してください：",
            reply_markup=keyboard
        )
        return GUEST_END_DATE
        
    return GUEST_START_DATE

async def guest_end_date_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    
    data = query.data.split(":")
    if len(data) < 3 or data[0] != "guest_end_date":
        return GUEST_END_DATE
        
    action = data[1]
    
    if action in ["prev", "next"]:
        year, month = int(data[2]), int(data[3])
        if action == "prev":
            month -= 1
            if month == 0:
                month = 12
                year -= 1
        else:
            month += 1
            if month == 13:
                month = 1
                year += 1
        keyboard = get_calendar_keyboard(year, month, "guest_end_date")
        await query.edit_message_reply_markup(reply_markup=keyboard)
        return GUEST_END_DATE
        
    elif action == "select":
        date_str = data[2]
        context.user_data["guest_end_date"] = date_str
        
        keyboard = get_time_keyboard("guest_in_time")
        await query.edit_message_text(
            f"✅ 終了日: {date_str}\n\n"
            "次に、【出勤時間(IN)】を選択してください：",
            reply_markup=keyboard
        )
        return GUEST_START_TIME
        
    return GUEST_END_DATE

async def guest_in_time_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    
    data = query.data.split(":")
    if len(data) < 3 or data[0] != "guest_in_time":
        return GUEST_START_TIME
        
    in_time = data[2]
    context.user_data["guest_in_time"] = in_time
    
    keyboard = get_time_keyboard("guest_out_time")
    await query.edit_message_text(
        f"✅ IN: {in_time}\n\n"
        "次に、【退勤時間(OUT)】を選択してください：",
        reply_markup=keyboard
    )
    return GUEST_END_TIME

async def guest_out_time_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    
    data = query.data.split(":")
    if len(data) < 3 or data[0] != "guest_out_time":
        return GUEST_END_TIME
        
    out_time = data[2]
    context.user_data["guest_out_time"] = out_time
    
    # テキスト入力に切り替え
    await query.edit_message_text(
        f"✅ OUT: {out_time}\n\n"
        "次に、【交通費支給金額】をチャットに入力してください。\n"
        "（例：「上限10,000円」「全額支給」など）\n\n"
        "※キャンセルする場合は「キャンセル」と入力してください。"
    )
    return GUEST_EXPENSE

async def guest_expense_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    if text == "キャンセル":
        await update.message.reply_text("❌ 登録をキャンセルしました。", reply_markup=MENU_KEYBOARD)
        return ConversationHandler.END
        
    context.user_data["guest_expense"] = text
    
    await update.message.reply_text(
        "✅ 交通費を記録しました。\n\n"
        "最後に、【現在使用中のXアカウント】を入力してください。\n"
        "（例：「@nzm_zr」「なし」など）"
    )
    return GUEST_X_ACCOUNT

async def guest_x_account_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    if text == "キャンセル":
        await update.message.reply_text("❌ 登録をキャンセルしました。", reply_markup=MENU_KEYBOARD)
        return ConversationHandler.END
        
    context.user_data["guest_x_account"] = text
    
    # 最終確認と出力
    name = context.user_data["guest_name"]
    start_d = context.user_data["guest_start_date"]
    end_d = context.user_data["guest_end_date"]
    in_time = context.user_data["guest_in_time"]
    out_time = context.user_data["guest_out_time"]
    expense = context.user_data["guest_expense"]
    x_account = context.user_data["guest_x_account"]
    
    # 日付のフォーマット変換 (YYYY-MM-DD -> M/D)
    try:
        s_date = datetime.strptime(start_d, "%Y-%m-%d")
        e_date = datetime.strptime(end_d, "%Y-%m-%d")
        date_str = f"{s_date.month}/{s_date.day}-{e_date.month}/{e_date.day}"
        days_count = (e_date - s_date).days + 1
    except:
        date_str = f"{start_d}〜{end_d}"
        days_count = 0
        
    # メッセージ生成
    result_text = f"""【派遣詳細(リピート用)】

■源氏名：{name}
■日程：{date_str}
■実働：{days_count}日間
■交通費支給金額：{expense}
■現在使用中のXアカウント：{x_account}
(ない場合やログインできない場合は日程確定の段階で作成お願いいたします)


-------------------------"""
    
    await update.message.reply_text("⏳ キャスカンのシステムに予定を直接登録中...")
    
    # キャスカンへ登録
    import browser_agent
    from datetime import timedelta
    import asyncio
    
    success_count = 0
    fail_details = []
    try:
        agent = browser_agent.BrowserAgent()
        caskan = await agent._get_caskan()
        
        s_date = datetime.strptime(start_d, "%Y-%m-%d")
        e_date = datetime.strptime(end_d, "%Y-%m-%d")
        current = s_date
        while current <= e_date:
            curr_str = current.strftime("%Y-%m-%d")
            # キャスカンに登録
            res = await caskan.register_shift(
                cast_name=name,
                date_str=curr_str,
                start_time=in_time,
                end_time=out_time
            )
            if res.get("success"):
                success_count += 1
            else:
                fail_details.append(f"{curr_str}: {res.get('message', '不明なエラー')}")
                
            current += timedelta(days=1)
            await asyncio.sleep(1) # 連投防止
            
        await agent.close()
            
        if fail_details:
            fail_text = "\n".join(fail_details)
            await update.message.reply_text(f"✅ キャスカンに {success_count} 日分のシフト（{in_time}〜{out_time}）を登録しました！\n\n⚠️ 一部失敗:\n{fail_text}")
        else:
            await update.message.reply_text(f"✅ キャスカンに {success_count} 日分のシフト（{in_time}〜{out_time}）を登録しました！")
    except Exception as e:
        await update.message.reply_text(f"⚠️ キャスカン登録中にエラーが発生しました: {e}")
        
    # 最終出力を送信
    await update.message.reply_text(
        "完成したフォーマットはこちらです👇 コピーして使ってください！",
        reply_markup=MENU_KEYBOARD
    )
    await update.message.reply_text(result_text)
    
    return ConversationHandler.END


async def ai_shift_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "🗣️ 【AIでシフト操作】\n\n"
        "シフトの追加や削除を、普通の言葉で入力してください。\n"
        "（例：「明日のさくらのシフトを12時から20時で入れて」「今日のなおのシフトを消して」など）\n\n"
        "※キャンセルする場合は「キャンセル」と送信してください。"
    )
    context.user_data["ai_shift_awaiting"] = True

async def handle_ai_shift_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if not context.user_data.get("ai_shift_awaiting"):
        return False
        
    text = update.message.text.strip()
    context.user_data.pop("ai_shift_awaiting", None)
    
    if text == "キャンセル":
        await update.message.reply_text("❌ キャンセルしました。", reply_markup=MENU_KEYBOARD)
        return True
        
    await update.message.reply_text("🧠 AIが指示を解析中...")
    
    import browser_agent
    try:
        confirmation, action_json = await browser_agent.process_agent_command(text)
        if confirmation:
            keyboard = [
                [InlineKeyboardButton("✅ 実行する", callback_data=f"ai_exec:yes")],
                [InlineKeyboardButton("❌ キャンセル", callback_data=f"ai_exec:no")]
            ]
            context.user_data["ai_pending_action"] = action_json
            await update.message.reply_text(confirmation, reply_markup=InlineKeyboardMarkup(keyboard))
        else:
            await update.message.reply_text("⚠️ 意図をうまく解析できませんでした。")
    except Exception as e:
        await update.message.reply_text(f"❌ エラーが発生しました: {e}")
        
    return True

async def ai_exec_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    
    data = query.data
    if not data.startswith("ai_exec:"):
        return
        
    action = data.split(":")[1]
    if action == "no":
        context.user_data.pop("ai_pending_action", None)
        await query.edit_message_text("❌ 実行をキャンセルしました。")
        return
        
    action_json = context.user_data.get("ai_pending_action")
    if not action_json:
        await query.edit_message_text("⚠️ 期限切れです。もう一度入力してください。")
        return
        
    await query.edit_message_text("⏳ キャスカンのシステムで実行中...")
    import browser_agent
    try:
        import json
        intent = json.loads(action_json)
        # NLPがNotion向けに解析したアクションをキャスカン用にすり替える
        if intent.get("action") == "notion_add_shift":
            intent["action"] = "caskan_register_shift"
            if "name" in intent.get("params", {}) and "cast_name" not in intent["params"]:
                intent["params"]["cast_name"] = intent["params"]["name"]
        elif intent.get("action") == "notion_delete_shift":
            intent["action"] = "caskan_delete_shift"
            if "name" in intent.get("params", {}) and "cast_name" not in intent["params"]:
                intent["params"]["cast_name"] = intent["params"]["name"]
                
        action_json = json.dumps(intent, ensure_ascii=False)
        result = await browser_agent.execute_confirmed(action_json)
        await query.edit_message_text(result)
    except Exception as e:
        await query.edit_message_text(f"❌ 実行エラー: {e}")


async def handle_imasugu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """イマスグ情報のツイート文面を生成する"""
    await update.message.reply_text("⏳ 今日のシフトとXアカウント情報を取得中...")
    
    try:
        from datetime import datetime, time
        import pytz
        import notion_shift_client
        import requests
        import os
        
        today_str = datetime.now().strftime("%Y-%m-%d")
        shifts = notion_shift_client.query_shifts(date_str=today_str)
        
        if not shifts:
            await update.message.reply_text("⚠️ 本日のシフトデータがありません。")
            return
            
        # マスタDBから情報を取得
        MASTER_DB_ID = os.environ.get("NOTION_MASTER_DB_ID", "")
        NOTION_API_KEY = os.environ.get("NOTION_API_KEY", "")
        headers = {
            "Authorization": f"Bearer {NOTION_API_KEY}",
            "Notion-Version": "2022-06-28",
            "Content-Type": "application/json"
        }
        
        # 名前でソートして、時間を抽出
        # 同じ子が複数入っている場合は1つにする（一番早い時間）
        shift_dict = {}
        for s in shifts:
            name = s["name"]
            start = s["start"]
            if not start:
                continue
            if name not in shift_dict or start < shift_dict[name]:
                shift_dict[name] = start
                
        # 時間順にソート
        sorted_therapists = sorted(shift_dict.items(), key=lambda x: x[1])
        
        result_text = "🔔イマスグ情報🔔\n\n"
        
        for name, start_time in sorted_therapists:
            # マスタDB検索
            body = {
                "filter": {
                    "property": "名前",
                    "title": {"contains": name}
                }
            }
            resp = requests.post(f"https://api.notion.com/v1/databases/{MASTER_DB_ID}/query", headers=headers, json=body)
            data = resp.json()
            
            x_url = ""
            catchphrase = ""
            
            if data.get("results"):
                props = data["results"][0]["properties"]
                
                # Xアカウント取得
                x_prop = props.get("Xアカウント", {})
                if x_prop.get("type") == "rich_text" and x_prop.get("rich_text"):
                    x_url = x_prop["rich_text"][0].get("plain_text", "")
                    # https://twitter.com/ や https://x.com/ が含まれているか確認
                    if x_url and not x_url.startswith("http"):
                        x_url = f"https://x.com/{x_url}"
                
                # キャッチフレーズ（「テキスト」または「お店コメント」または「テキスト 1」）
                for field in ["テキスト", "お店コメント", "テキスト 1"]:
                    cp_prop = props.get(field, {})
                    if cp_prop.get("type") == "rich_text" and cp_prop.get("rich_text"):
                        catchphrase = cp_prop["rich_text"][0].get("plain_text", "")
                        break
            
            if catchphrase:
                result_text += f"{catchphrase}\n"
                
            x_display = f"({x_url})" if x_url else ""
            result_text += f"🌻{name}{x_display}\n"
            result_text += f"🕐最短{start_time}〜\n\n"
            
        result_text += "お問い合わせお待ちしております✨"
        
        # メッセージを分けて送信（コピーしやすくするため）
        await update.message.reply_text("✅ イマスグ情報を作成しました！👇 コピーして使ってください！")
        await update.message.reply_text(result_text)
        
    except Exception as e:
        await update.message.reply_text(f"❌ エラーが発生しました: {str(e)[:200]}")


async def cmd_chatid(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """現在のチャットIDを返す（グループ登録用）"""
    chat_id = update.effective_chat.id
    await update.message.reply_text(f"このチャット（グループ）のIDは以下です：\n`{chat_id}`\nこれをシステムに登録してください。", parse_mode="Markdown")

async def scheduled_sync(context: ContextTypes.DEFAULT_TYPE) -> None:
    """定期実行される同期ジョブ"""
    import os
    import browser_agent
    
    chat_id = os.environ.get("LOG_GROUP_ID")
    if not chat_id:
        logger.error("LOG_GROUP_ID が設定されていないため、定期同期ログを送信できません。")
        return
        
    try:
        await context.bot.send_message(chat_id=chat_id, text="🔄 【定期実行】 1週間分のシフト自動同期を開始します...")
        agent = browser_agent.BrowserAgent()
        result = await agent._sync_all_week()
        
        # ログが長い場合、分割して送る（Telegramの制限対策）
        if len(result) > 4000:
            result = result[:4000] + "\n...（文字数制限のため省略）"
            
        await context.bot.send_message(chat_id=chat_id, text=result)
    except Exception as e:
        logger.error(f"定期同期エラー: {e}")
        await context.bot.send_message(chat_id=chat_id, text=f"❌ 【定期実行エラー】\n{str(e)[:300]}")

# ─── 経費入力ハンドラー ─────────────────────────────────────
async def expense_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """経費入力開始"""
    # キャンセルボタン付きのキーボード
    keyboard = [[KeyboardButton("今日"), KeyboardButton("昨日")], [KeyboardButton("❌ キャンセル")]]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)

    await update.message.reply_text(
        "💴 【経費入力】\n\n"
        "Notionの経費管理ページおよびGoogleスプレッドシートに記録します。\n"
        "まず、日付を入力してください（例: 2026-03-20）",
        reply_markup=reply_markup,
    )
    return EXPENSE_DATE


async def expense_date(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """日付を受け取る"""
    text = update.message.text.strip()

    if text == "❌ キャンセル":
        await update.message.reply_text("❌ 経費入力をキャンセルしました。", reply_markup=MENU_KEYBOARD)
        return ConversationHandler.END

    if text == "今日":
        date_str = datetime.now().strftime("%Y-%m-%d")
    elif text == "昨日":
        from datetime import timedelta
        date_str = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    else:
        # 簡易的な日付バリデーション
        import re
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", text):
            await update.message.reply_text("⚠️ 日付は YYYY-MM-DD 形式で入力してください（例: 2026-03-20）")
            return EXPENSE_DATE
        date_str = text

    context.user_data["expense_date"] = date_str

    await update.message.reply_text(
        f"📅 日付: {date_str}\n\n"
        "次に、金額を入力してください（例: 3500）",
        reply_markup=ReplyKeyboardMarkup([[KeyboardButton("❌ キャンセル")]], resize_keyboard=True),
    )
    return EXPENSE_AMOUNT


async def expense_amount(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """金額を受け取る"""
    text = update.message.text.strip()

    if text == "❌ キャンセル":
        await update.message.reply_text("❌ 経費入力をキャンセルしました。", reply_markup=MENU_KEYBOARD)
        return ConversationHandler.END

    # 数字以外を除去
    import re
    amount_str = re.sub(r"[^\d]", "", text)

    if not amount_str:
        await update.message.reply_text(
            "⚠️ 金額は数字で入力してください。\n例: 3500",
        )
        return EXPENSE_AMOUNT

    amount = int(amount_str)
    context.user_data["expense_amount"] = amount

    # 6カテゴリのボタン選択
    category_buttons = [
        [KeyboardButton("地代家賃"), KeyboardButton("水道光熱費")],
        [KeyboardButton("広告宣伝費"), KeyboardButton("備品購入費")],
        [KeyboardButton("接待交通費"), KeyboardButton("交通費")],
        [KeyboardButton("❌ キャンセル")],
    ]

    await update.message.reply_text(
        f"📅 日付: {context.user_data['expense_date']}\n"
        f"💴 金額: ¥{amount:,}\n\n"
        "📌 内容を選んでください:",
        reply_markup=ReplyKeyboardMarkup(category_buttons, resize_keyboard=True, one_time_keyboard=True),
    )
    return EXPENSE_CONTENT


async def expense_content(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """内容を受け取る"""
    text = update.message.text.strip()

    if text == "❌ キャンセル":
        await update.message.reply_text("❌ 経費入力をキャンセルしました。", reply_markup=MENU_KEYBOARD)
        return ConversationHandler.END

    # 有効なカテゴリのみ受け付ける
    valid_categories = ["地代家賃", "水道光熱費", "広告宣伝費", "備品購入費", "接待交通費", "交通費"]
    if text not in valid_categories:
        category_buttons = [
            [KeyboardButton("地代家賃"), KeyboardButton("水道光熱費")],
            [KeyboardButton("広告宣伝費"), KeyboardButton("備品購入費")],
            [KeyboardButton("接待交通費"), KeyboardButton("交通費")],
            [KeyboardButton("❌ キャンセル")],
        ]
        await update.message.reply_text(
            "⚠️ 下のボタンから選んでください:",
            reply_markup=ReplyKeyboardMarkup(category_buttons, resize_keyboard=True, one_time_keyboard=True),
        )
        return EXPENSE_CONTENT

    context.user_data["expense_content"] = text

    await update.message.reply_text(
        f"📅 日付: {context.user_data['expense_date']}\n"
        f"💴 金額: ¥{context.user_data['expense_amount']:,}\n"
        f"📌 内容: {text}\n\n"
        "📝 メモを入力してください（任意）:\n"
        "不要な場合は「なし」または「スキップ」と入力してください。",
        reply_markup=ReplyKeyboardMarkup(
            [[KeyboardButton("スキップ"), KeyboardButton("❌ キャンセル")]],
            resize_keyboard=True,
            one_time_keyboard=True,
        ),
    )
    return EXPENSE_MEMO


async def expense_memo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """メモを受け取り、Googleスプレッドシートに保存する"""
    text = update.message.text.strip()

    if text == "❌ キャンセル":
        await update.message.reply_text("❌ 経費入力をキャンセルしました。", reply_markup=MENU_KEYBOARD)
        return ConversationHandler.END

    memo = "" if text in ("スキップ", "なし", "skip", "") else text

    # 入力内容を取得
    date_str = context.user_data.get("expense_date", datetime.now().strftime("%Y-%m-%d"))
    amount = context.user_data.get("expense_amount", 0)
    content = context.user_data.get("expense_content", "")

    # 確認メッセージ
    confirm_text = (
        "💴 【経費入力確認】\n\n"
        f"📅 日付: {date_str}\n"
        f"💴 金額: ¥{amount:,}\n"
        f"📌 内容: {content}\n"
    )
    if memo:
        confirm_text += f"📝 メモ: {memo}\n"

    confirm_text += "\nGoogleスプレッドシートに保存しますか？"

    # 確認ボタン
    keyboard = [
        [
            InlineKeyboardButton("✅ 保存する", callback_data=f"expense_confirm:yes"),
            InlineKeyboardButton("❌ キャンセル", callback_data="expense_confirm:no"),
        ]
    ]

    # データをコンテキストに保存
    context.user_data["expense_memo"] = memo

    await update.message.reply_text(
        confirm_text,
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    # メインメニューに戻す（確認ボタンはインライン）
    await update.message.reply_text("メニューに戻ります。", reply_markup=MENU_KEYBOARD)
    return ConversationHandler.END


async def expense_confirm_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """経費保存確認コールバック"""
    query = update.callback_query
    await query.answer()

    data = query.data
    if not data.startswith("expense_confirm:"):
        return

    action = data.replace("expense_confirm:", "")

    if action == "no":
        await query.edit_message_text("❌ 経費の保存をキャンセルしました。")
        return

    # Notionに保存
    date_str = context.user_data.get("expense_date", datetime.now().strftime("%Y-%m-%d"))
    amount = context.user_data.get("expense_amount", 0)
    content = context.user_data.get("expense_content", "")
    memo = context.user_data.get("expense_memo", "")

    await query.edit_message_text("⏳ Googleスプレッドシートに経費を保存中...")

    # Googleスプレッドシートに保存
    sheet_success = append_expense_to_sheet(
        date=date_str,
        amount=amount,
        content=content,
        memo=memo,
    )

    if sheet_success:
        # コンテキストをクリア
        for key in ("expense_date", "expense_amount", "expense_content", "expense_memo"):
            context.user_data.pop(key, None)

        await query.edit_message_text(
            f"✅ 経費を記録しました！\n\n"
            f"📅 {date_str}　💴 ¥{amount:,}\n"
            f"📌 {content}"
            + (f"\n📝 {memo}" if memo else "")
            + "\n\n📊 Googleスプレッドシート: 保存完了"
        )
    else:
        await query.edit_message_text(
            "❌ 保存に失敗しました。\n\n"
            "『Googleスプレッドシート』: GOOGLE_SERVICE_ACCOUNT_JSON または "
            "GOOGLE_APPLICATION_CREDENTIALS が正しく設定されているか確認してください。"
        )


async def expense_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """経費入力をキャンセル"""
    await update.message.reply_text("❌ 経費入力をキャンセルしました。", reply_markup=MENU_KEYBOARD)
    return ConversationHandler.END


# ─── ✍️ SEO記事作成 ────────────────────────────────────────
async def handle_seo_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """SEO記事作成メニューを表示"""
    keyboard = [
        [
            InlineKeyboardButton(
                f"{TEMPLATE_1_INFO['emoji']} ランキング紹介風",
                callback_data="seo:select:ranking",
            ),
        ],
        [
            InlineKeyboardButton(
                f"{TEMPLATE_2_INFO['emoji']} お悩み解決型ハウツー",
                callback_data="seo:select:howto",
            ),
        ],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        "✍️ 【SEO記事作成】\n\n"
        "SEOテンプレートに沿って、全力エステの情報を埋め込んだ\n"
        "記事ドラフトをAIが自動生成します。\n\n"
        "テンプレートを選択してください:",
        reply_markup=reply_markup,
    )


async def handle_seo_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """SEO記事作成コールバック処理"""
    query = update.callback_query
    await query.answer()

    data = query.data
    if not data.startswith("seo:"):
        return

    parts = data.split(":")
    action = parts[1] if len(parts) > 1 else ""

    if action == "select":
        template_type = parts[2] if len(parts) > 2 else ""
        if template_type not in ("ranking", "howto"):
            await query.edit_message_text("⚠️ 不明なテンプレートです。")
            return

        # テンプレートプレビューを表示
        preview = get_template_preview(template_type)

        # プレビューが長い場合は切り詰め
        if len(preview) > 3500:
            preview = preview[:3500] + "\n..."

        keyboard = [
            [
                InlineKeyboardButton(
                    "🚀 この記事を生成する",
                    callback_data=f"seo:generate:{template_type}",
                ),
            ],
            [
                InlineKeyboardButton(
                    "📝 キーワードを指定して生成",
                    callback_data=f"seo:keyword:{template_type}",
                ),
            ],
            [
                InlineKeyboardButton(
                    "🔙 テンプレート選択に戻る",
                    callback_data="seo:back",
                ),
            ],
        ]

        await query.edit_message_text(
            preview,
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

    elif action == "generate":
        template_type = parts[2] if len(parts) > 2 else ""
        if template_type not in ("ranking", "howto"):
            await query.edit_message_text("⚠️ 不明なテンプレートです。")
            return

        template_name = TEMPLATE_1_INFO['title'] if template_type == 'ranking' else TEMPLATE_2_INFO['title']
        await query.edit_message_text(
            f"⏳ 【{template_name}】の記事を生成中...\n\n"
            "AIが全力エステの情報を埋め込んだ記事ドラフトを作成しています。\n"
            "少々お待ちください（30秒〜1分程度）。"
        )

        custom_keyword = context.user_data.pop("seo_custom_keyword", "")

        try:
            article = await generate_seo_article(template_type, custom_keyword)

            # Telegramメッセージの文字数制限（4096文字）対策
            header = f"✍️ 【SEO記事ドラフト — {template_name}】\n\n"
            footer = f"\n\n{'─' * 30}\n{SEO_CHECKLIST}"

            full_text = header + article + footer

            # 長い場合は分割送信
            if len(full_text) <= 4096:
                await query.message.chat.send_message(full_text)
            else:
                # 記事本文を分割
                chunks = _split_text(article, 3800)
                for i, chunk in enumerate(chunks):
                    if i == 0:
                        await query.message.chat.send_message(header + chunk)
                    else:
                        await query.message.chat.send_message(chunk)
                # チェックリストを最後に送信
                await query.message.chat.send_message(SEO_CHECKLIST)

            # 再生成・別テンプレートボタン
            keyboard = [
                [
                    InlineKeyboardButton(
                        "🔄 同じテンプレートで再生成",
                        callback_data=f"seo:generate:{template_type}",
                    ),
                ],
                [
                    InlineKeyboardButton(
                        "📋 別のテンプレートを選ぶ",
                        callback_data="seo:back",
                    ),
                ],
            ]
            await query.message.chat.send_message(
                "👆 生成された記事ドラフトをコピーしてお使いください。",
                reply_markup=InlineKeyboardMarkup(keyboard),
            )

        except Exception as e:
            logger.error(f"SEO記事生成エラー: {e}")
            await query.message.chat.send_message(
                "❌ 記事の生成に失敗しました。\n\n"
                "考えられる原因:\n"
                "• GEMINI_API_KEY が設定されていない\n"
                "• APIの利用制限に達している\n\n"
                f"エラー: {str(e)[:200]}",
                reply_markup=MENU_KEYBOARD,
            )

    elif action == "keyword":
        template_type = parts[2] if len(parts) > 2 else ""
        context.user_data["seo_awaiting_keyword"] = template_type

        await query.edit_message_text(
            "📝 【キーワード指定】\n\n"
            "記事に追加で意識したいSEOキーワードを入力してください。\n\n"
            "例: 「国分町 深夜営業 個室」「初回限定 クーポン」\n\n"
            "入力後、自動的に記事が生成されます。"
        )

    elif action == "back":
        # テンプレート選択に戻る
        keyboard = [
            [
                InlineKeyboardButton(
                    f"{TEMPLATE_1_INFO['emoji']} ランキング紹介風",
                    callback_data="seo:select:ranking",
                ),
            ],
            [
                InlineKeyboardButton(
                    f"{TEMPLATE_2_INFO['emoji']} お悩み解決型ハウツー",
                    callback_data="seo:select:howto",
                ),
            ],
        ]
        await query.edit_message_text(
            "✍️ 【SEO記事作成】\n\n"
            "テンプレートを選択してください:",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )


async def handle_seo_keyword_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """SEOキーワード入力を受け取って記事を生成"""
    template_type = context.user_data.get("seo_awaiting_keyword")
    if not template_type:
        return False

    keyword = update.message.text.strip()
    context.user_data.pop("seo_awaiting_keyword", None)
    context.user_data["seo_custom_keyword"] = keyword

    template_name = TEMPLATE_1_INFO['title'] if template_type == 'ranking' else TEMPLATE_2_INFO['title']

    await update.message.reply_text(
        f"⏳ 【{template_name}】の記事を生成中...\n"
        f"追加キーワード: {keyword}\n\n"
        "AIが全力エステの情報を埋め込んだ記事ドラフトを作成しています。\n"
        "少々お待ちください（30秒〜1分程度）。",
        reply_markup=MENU_KEYBOARD,
    )

    try:
        article = await generate_seo_article(template_type, keyword)

        header = f"✍️ 【SEO記事ドラフト — {template_name}】\n追加キーワード: {keyword}\n\n"
        footer = f"\n\n{'─' * 30}\n{SEO_CHECKLIST}"

        full_text = header + article + footer

        if len(full_text) <= 4096:
            await update.message.reply_text(full_text, reply_markup=MENU_KEYBOARD)
        else:
            chunks = _split_text(article, 3800)
            for i, chunk in enumerate(chunks):
                if i == 0:
                    await update.message.reply_text(header + chunk)
                else:
                    await update.message.reply_text(chunk)
            await update.message.reply_text(SEO_CHECKLIST, reply_markup=MENU_KEYBOARD)

        # 再生成ボタン
        keyboard = [
            [
                InlineKeyboardButton(
                    "🔄 同じテンプレートで再生成",
                    callback_data=f"seo:generate:{template_type}",
                ),
            ],
            [
                InlineKeyboardButton(
                    "📋 別のテンプレートを選ぶ",
                    callback_data="seo:back",
                ),
            ],
        ]
        await update.message.reply_text(
            "👆 生成された記事ドラフトをコピーしてお使いください。",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

    except Exception as e:
        logger.error(f"SEO記事生成エラー: {e}")
        await update.message.reply_text(
            "❌ 記事の生成に失敗しました。\n"
            f"エラー: {str(e)[:200]}",
            reply_markup=MENU_KEYBOARD,
        )

    return True


def _split_text(text: str, max_length: int) -> list:
    """テキストを指定文字数で分割する（改行で区切る）"""
    chunks = []
    current = ""
    for line in text.split("\n"):
        if len(current) + len(line) + 1 > max_length:
            if current:
                chunks.append(current)
            current = line
        else:
            current = current + "\n" + line if current else line
    if current:
        chunks.append(current)
    return chunks

# ─── 💰 仮想通貨（bitbank ポートフォリオ＋自然言語取引）────────────────────

# ─── Gemini による取引インテント解析 ──────────────────────────────────────

CRYPTO_TRADE_SYSTEM_PROMPT = """あなたは仮想通貨取引アシスタントです。
ユーザーの自然言語の取引指示を解析し、bitbank取引所での注文内容をJSON形式で返してください。

## 対応する取引指示の例
- 「XRPを1000円分買って」→ JPY金額指定の買い注文
- 「BTCを0.001売って」→ 数量指定の売り注文
- 「XLMを全部売って」→ 保有全量の売り注文
- 「ETHを5000円買いたい」→ JPY金額指定の買い注文
- 「ドージコインを100枚買って」→ 数量指定の買い注文

## 通貨名の対応
- ビットコイン/BTC → btc
- イーサリアム/ETH → eth
- リップル/XRP → xrp
- ステラルーメン/XLM → xlm
- ライトコイン/LTC → ltc
- ドージコイン/DOGE → doge
- ソラナ/SOL → sol
- ポルカドット/DOT → dot
- アバランチ/AVAX → avax
- その他は英語シンボルをそのまま小文字で使用

## 出力形式
必ず以下のJSON形式で返してください。余計なテキストは含めないでください。

```json
{
  "asset": "通貨シンボル（小文字）",
  "side": "buy または sell",
  "amount_type": "quantity（数量指定）または jpy（JPY金額指定）または all（全量売り）",
  "amount": 数値（数量またはJPY金額。allの場合は0）,
  "confidence": 0.0〜1.0（解析の確信度）,
  "error": null または "エラーメッセージ"
}
```

## 注意事項
- 取引指示でない場合は error に「取引指示ではありません」を設定してください
- 通貨が特定できない場合は error に「通貨が特定できません」を設定してください
- 数量が不明な場合は error に「数量または金額を指定してください」を設定してください
- JPYペアが存在しない通貨の場合は error に「JPYペアが存在しない通貨です」を設定してください
"""


async def parse_trade_intent(user_message: str) -> dict:
    """
    Gemini APIでユーザーの自然言語取引指示を解析する。

    Returns:
        {
            "asset": str,          # 通貨シンボル（例: "xrp"）
            "side": str,           # "buy" or "sell"
            "amount_type": str,    # "quantity" / "jpy" / "all"
            "amount": float,       # 数量またはJPY金額
            "confidence": float,
            "error": None or str,
        }
    """
    try:
        import google.generativeai as genai
        genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))
        model = genai.GenerativeModel("gemini-2.5-flash")

        prompt = f"{CRYPTO_TRADE_SYSTEM_PROMPT}\n\n取引指示: {user_message}"

        response = model.generate_content(
            contents=[{"role": "user", "parts": [{"text": prompt}]}],
            generation_config=genai.types.GenerationConfig(
                max_output_tokens=500,
                temperature=0.1,
                response_mime_type="application/json",
            ),
        )

        import json as _json
        result = _json.loads(response.text.strip())
        logger.info(f"取引インテント解析結果: {result}")
        return result

    except Exception as e:
        logger.error(f"取引インテント解析エラー: {e}")
        return {
            "asset": None,
            "side": None,
            "amount_type": None,
            "amount": 0,
            "confidence": 0.0,
            "error": f"解析エラー: {str(e)[:100]}",
        }


def _format_trade_confirmation(asset: str, side: str, amount_type: str,
                               amount: float, price_jpy: float,
                               actual_quantity: float, actual_jpy: float) -> str:
    """
    取引確認メッセージを生成する
    """
    asset_upper = asset.upper()
    name = ASSET_NAMES.get(asset, asset_upper)
    side_str = "🟢 買い" if side == "buy" else "🔴 売り"
    precision = AMOUNT_PRECISION.get(asset, 4)

    if precision <= 0:
        qty_str = f"{actual_quantity:,.0f}"
    elif precision <= 4:
        qty_str = f"{actual_quantity:,.{precision}f}"
    else:
        qty_str = f"{actual_quantity:.{precision}f}".rstrip("0").rstrip(".")

    price_str = f"¥{price_jpy:,.2f}" if price_jpy >= 1 else f"¥{price_jpy:.6f}"

    lines = [
        "⚠️ 【取引確認】",
        "",
        f"通貨:     {asset_upper} ({name})",
        f"売買:     {side_str}",
        f"数量:     {qty_str} {asset_upper}",
        f"現在価格: {price_str}",
        f"概算金額: ¥{actual_jpy:,.0f}",
        "",
        "この注文を実行しますか？",
        "（成行注文のため、実際の約定価格は変動する場合があります）",
    ]
    return "\n".join(lines)


async def handle_crypto_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """仮想通貨メニューを表示"""
    keyboard = [
        [
            InlineKeyboardButton("📊 ポートフォリオを表示", callback_data="crypto:portfolio"),
        ],
        [
            InlineKeyboardButton("💱 取引する（自然言語）", callback_data="crypto:trade_input"),
        ],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        "💰 【仮想通貨】\n\n"
        "bitbank の保有資産確認・取引ができます。\n\n"
        "📊 ポートフォリオ: 保有資産を確認\n"
        "💱 取引する: 自然言語で売買注文\n\n"
        "例: 「XRPを1000円分買って」「BTCを0.001売って」「XLMを全部売って」",
        reply_markup=reply_markup,
    )


async def handle_crypto_trade_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    仮想通貨メニューの「取引する」ボタン押下後、
    自然言語入力を待機するモードに入る
    """
    context.user_data["crypto_awaiting_trade"] = True
    await update.message.reply_text(
        "💱 【取引入力】\n\n"
        "取引内容を自然言語で入力してください。\n\n"
        "例:\n"
        "・「XRPを1000円分買って」\n"
        "・「BTCを0.001売って」\n"
        "・「XLMを全部売って」\n"
        "・「ETHを5000円買いたい」\n\n"
        "⚠️ 注文前に確認画面が表示されます。",
        reply_markup=MENU_KEYBOARD,
    )


async def handle_crypto_trade_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """
    自然言語取引入力を処理する。
    context.user_data["crypto_awaiting_trade"] が True の場合のみ処理。
    Returns: True if handled, False otherwise
    """
    if not context.user_data.get("crypto_awaiting_trade"):
        return False

    text = update.message.text.strip()
    context.user_data.pop("crypto_awaiting_trade", None)

    await update.message.reply_text("🧠 取引内容を解析中...")

    # Geminiで取引インテントを解析
    intent = await parse_trade_intent(text)

    if intent.get("error"):
        await update.message.reply_text(
            f"❌ {intent['error']}\n\n"
            "もう一度入力してください。\n"
            "例: 「XRPを1000円分買って」「BTCを0.001売って」",
            reply_markup=MENU_KEYBOARD,
        )
        return True

    asset = intent.get("asset", "").lower()
    side = intent.get("side", "")
    amount_type = intent.get("amount_type", "")
    amount = float(intent.get("amount", 0))

    # 基本バリデーション
    if not asset or asset not in JPY_PAIRS:
        await update.message.reply_text(
            f"❌ 通貨 '{asset.upper() if asset else '不明'}' はbitbankのJPYペアに対応していません。\n\n"
            "対応通貨: BTC, ETH, XRP, XLM, LTC, DOGE, SOL など",
            reply_markup=MENU_KEYBOARD,
        )
        return True

    if side not in ("buy", "sell"):
        await update.message.reply_text(
            "❌ 売買方向が特定できませんでした。\n「買って」または「売って」を含めて入力してください。",
            reply_markup=MENU_KEYBOARD,
        )
        return True

    # 現在価格を取得
    pair = JPY_PAIRS[asset]
    ticker = get_ticker(pair)
    if not ticker:
        await update.message.reply_text(
            f"❌ {asset.upper()} の現在価格を取得できませんでした。しばらく後に再試行してください。",
            reply_markup=MENU_KEYBOARD,
        )
        return True

    try:
        price_jpy = float(ticker.get("last", 0))
        ask_price = float(ticker.get("sell", price_jpy))  # 買い板最安値
        bid_price = float(ticker.get("buy", price_jpy))   # 売り板最高値
    except (ValueError, TypeError):
        await update.message.reply_text(
            f"❌ {asset.upper()} の価格データが不正です。",
            reply_markup=MENU_KEYBOARD,
        )
        return True

    # 実際の注文数量を計算
    if amount_type == "jpy":
        # JPY金額 → 数量に変換
        ref_price = ask_price if side == "buy" else bid_price
        if ref_price <= 0:
            await update.message.reply_text("❌ 価格が0円のため計算できません。", reply_markup=MENU_KEYBOARD)
            return True
        actual_quantity = amount / ref_price
        actual_jpy = amount

    elif amount_type == "all":
        # 全量売り（利用可能残高を取得）
        if side != "sell":
            await update.message.reply_text("❌ 「全部」は売り注文にのみ対応しています。", reply_markup=MENU_KEYBOARD)
            return True
        free_amount = get_asset_free_amount(asset)
        if free_amount is None or free_amount <= 0:
            await update.message.reply_text(
                f"❌ {asset.upper()} の利用可能残高がありません。",
                reply_markup=MENU_KEYBOARD,
            )
            return True
        actual_quantity = free_amount
        actual_jpy = actual_quantity * bid_price

    else:
        # 数量指定
        actual_quantity = amount
        actual_jpy = actual_quantity * (ask_price if side == "buy" else bid_price)

    # 最小注文数量チェック（概算）
    if actual_quantity <= 0:
        await update.message.reply_text(
            "❌ 注文数量が0以下です。金額または数量を確認してください。",
            reply_markup=MENU_KEYBOARD,
        )
        return True

    # 確認メッセージを生成して保存
    confirmation_msg = _format_trade_confirmation(
        asset, side, amount_type, amount, price_jpy, actual_quantity, actual_jpy
    )

    # 注文情報をコンテキストに保存
    context.user_data["crypto_pending_order"] = {
        "asset": asset,
        "side": side,
        "quantity": actual_quantity,
        "price_jpy": price_jpy,
        "estimated_jpy": actual_jpy,
        "original_text": text,
    }

    keyboard = [
        [
            InlineKeyboardButton("✅ 注文を実行する", callback_data="crypto:order_confirm"),
            InlineKeyboardButton("❌ キャンセル", callback_data="crypto:order_cancel"),
        ]
    ]
    await update.message.reply_text(
        confirmation_msg,
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return True


async def handle_crypto_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """仮想通貨コールバック処理"""
    query = update.callback_query
    await query.answer()

    data = query.data
    if not data.startswith("crypto:"):
        return

    action = data.replace("crypto:", "")

    # ─── ポートフォリオ表示 ───────────────────────────────────
    if action == "portfolio":
        await query.edit_message_text("⏳ bitbank から保有資産を取得中...\nしばらくお待ちください。")

        try:
            portfolio = get_portfolio()
            message = format_portfolio_message(portfolio)

            if len(message) > 4096:
                message = message[:4090] + "\n..."

            keyboard = [
                [
                    InlineKeyboardButton("🔄 更新", callback_data="crypto:portfolio"),
                    InlineKeyboardButton("💱 取引する", callback_data="crypto:trade_input"),
                ],
            ]
            await query.edit_message_text(
                message,
                reply_markup=InlineKeyboardMarkup(keyboard),
            )
        except Exception as e:
            logger.error(f"仮想通貨ポートフォリオ取得エラー: {e}")
            await query.edit_message_text(
                f"❌ ポートフォリオの取得に失敗しました。\n\n"
                f"エラー: {str(e)[:200]}\n\n"
                "BITBANK_API_KEY と BITBANK_API_SECRET が正しく設定されているか確認してください。"
            )

    # ─── 取引入力モードへ ─────────────────────────────────────
    elif action == "trade_input":
        context.user_data["crypto_awaiting_trade"] = True
        await query.edit_message_text(
            "💱 【取引入力】\n\n"
            "取引内容を自然言語で入力してください。\n\n"
            "例:\n"
            "・「XRPを1000円分買って」\n"
            "・「BTCを0.001売って」\n"
            "・「XLMを全部売って」\n"
            "・「ETHを5000円買いたい」\n\n"
            "⚠️ 注文前に確認画面が表示されます。"
        )

    # ─── 注文実行（確認後） ───────────────────────────────────
    elif action == "order_confirm":
        pending = context.user_data.pop("crypto_pending_order", None)
        if not pending:
            await query.edit_message_text("⚠️ 注文情報が見つかりません。もう一度入力してください。")
            return

        asset = pending["asset"]
        side = pending["side"]
        quantity = pending["quantity"]
        side_str = "買い" if side == "buy" else "売り"

        await query.edit_message_text(
            f"⏳ {asset.upper()} の{side_str}注文を発注中...\nしばらくお待ちください。"
        )

        try:
            result = place_market_order(asset, side, quantity)
        except Exception as e:
            logger.error(f"注文発注エラー: {e}")
            await query.edit_message_text(
                f"❌ 注文の発注中にエラーが発生しました。\n\nエラー: {str(e)[:200]}"
            )
            return

        if result.get("success"):
            order_id = result.get("order_id", "不明")
            status = result.get("status", "UNKNOWN")
            executed_amount = result.get("executed_amount", "0")
            avg_price = result.get("average_price", "0")

            try:
                avg_price_f = float(avg_price)
                exec_amount_f = float(executed_amount)
                exec_jpy = avg_price_f * exec_amount_f
                price_display = f"¥{avg_price_f:,.2f}" if avg_price_f >= 1 else f"¥{avg_price_f:.6f}"
                exec_jpy_display = f"¥{exec_jpy:,.0f}"
            except (ValueError, TypeError):
                price_display = avg_price
                exec_jpy_display = "計算不可"

            status_map = {
                "FULLY_FILLED": "✅ 全量約定",
                "PARTIALLY_FILLED": "⚠️ 一部約定",
                "UNFILLED": "⏳ 未約定",
                "CANCELED_UNFILLED": "❌ キャンセル（未約定）",
                "CANCELED_PARTIALLY_FILLED": "❌ キャンセル（一部約定）",
            }
            status_display = status_map.get(status, status)

            await query.edit_message_text(
                f"🎉 【注文完了】\n\n"
                f"注文ID:   {order_id}\n"
                f"通貨:     {asset.upper()} ({ASSET_NAMES.get(asset, asset.upper())})\n"
                f"売買:     {'🟢 買い' if side == 'buy' else '🔴 売り'}\n"
                f"約定数量: {executed_amount} {asset.upper()}\n"
                f"平均価格: {price_display}\n"
                f"約定金額: {exec_jpy_display}\n"
                f"ステータス: {status_display}\n\n"
                f"bitbank アプリで取引履歴を確認してください。"
            )
        else:
            error_msg = result.get("error_message", "不明なエラー")
            await query.edit_message_text(
                f"❌ 【注文失敗】\n\n"
                f"エラー: {error_msg}\n\n"
                "注文が失敗しました。内容を確認して再試行してください。"
            )

    # ─── 注文キャンセル ───────────────────────────────────────
    elif action == "order_cancel":
        context.user_data.pop("crypto_pending_order", None)
        await query.edit_message_text(
            "❌ 注文をキャンセルしました。\n\n"
            "💰 仮想通貨メニューから再度操作できます。"
        )


# ─── 📅 シフトDB（Notionマスタ）─────────────────────────────

async def handle_shift_db_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """シフトDBメニューを表示"""
    keyboard = [
        [
            InlineKeyboardButton("📋 今日のシフトを確認", callback_data="shiftdb:today"),
            InlineKeyboardButton("📆 今週のシフトを確認", callback_data="shiftdb:week"),
        ],
        [
            InlineKeyboardButton("⬜ 未着手シフト一覧", callback_data="shiftdb:pending"),
        ],
        [
            InlineKeyboardButton("🔄 今日のシフトを全同期", callback_data="shiftdb:sync_today"),
        ],
        [
            InlineKeyboardButton("🟢 キャスカンに同期", callback_data="shiftdb:sync_caskan"),
            InlineKeyboardButton("🔵 エスたまに同期", callback_data="shiftdb:sync_estama"),
        ],
        [
            InlineKeyboardButton("🔍 差異を確認する", callback_data="shiftdb:diff"),
        ],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        "📅 【シフトDB】\n\n"
        "NotionシフトDBをマスタとして、\n"
        "キャスカン・エスたまへのシフト同期を管理します。\n\n"
        "操作を選択してください:",
        reply_markup=reply_markup,
    )


async def handle_shift_db_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """シフトDBコールバック処理"""
    query = update.callback_query
    await query.answer()

    data = query.data
    if not data.startswith("shiftdb:"):
        return

    action = data.replace("shiftdb:", "")

    if action == "today":
        await query.edit_message_text("⏳ NotionシフトDBから今日のシフトを取得中...")
        try:
            today_str = datetime.now().strftime("%Y-%m-%d")
            shifts = notion_shift_client.query_shifts(date_str=today_str)
            result = notion_shift_client.format_shifts_message(shifts, title=f"本日のシフト ({today_str})")
            if len(result) > 4000:
                result = result[:4000] + "\n..."
            # 戻るボタン付きで表示
            keyboard = [[InlineKeyboardButton("🔙 シフトDBメニューへ", callback_data="shiftdb:back")]]
            await query.edit_message_text(result, reply_markup=InlineKeyboardMarkup(keyboard))
        except Exception as e:
            await query.edit_message_text(f"❌ エラー: {str(e)[:300]}")

    elif action == "week":
        await query.edit_message_text("⏳ NotionシフトDBから今週のシフトを取得中...")
        try:
            shifts = notion_shift_client.query_shifts_week()
            result = notion_shift_client.format_shifts_message(shifts, title="今週のシフト")
            if len(result) > 4000:
                result = result[:4000] + "\n..."
            keyboard = [[InlineKeyboardButton("🔙 シフトDBメニューへ", callback_data="shiftdb:back")]]
            await query.edit_message_text(result, reply_markup=InlineKeyboardMarkup(keyboard))
        except Exception as e:
            await query.edit_message_text(f"❌ エラー: {str(e)[:300]}")

    elif action == "pending":
        await query.edit_message_text("⏳ 未着手のシフトを検索中...")
        try:
            shifts = notion_shift_client.query_pending_shifts(target="caskan")
            result = notion_shift_client.format_shifts_message(shifts, title="未登録シフト")
            if len(result) > 4000:
                result = result[:4000] + "\n..."
            keyboard = [[InlineKeyboardButton("🔙 シフトDBメニューへ", callback_data="shiftdb:back")]]
            await query.edit_message_text(result, reply_markup=InlineKeyboardMarkup(keyboard))
        except Exception as e:
            await query.edit_message_text(f"❌ エラー: {str(e)[:300]}")

    elif action == "sync_today":
        keyboard = [
            [
                InlineKeyboardButton("✅ 実行する", callback_data="shiftdb_confirm:sync_all"),
                InlineKeyboardButton("❌ キャンセル", callback_data="shiftdb_confirm:cancel"),
            ]
        ]
        await query.edit_message_text(
            "🔄 【全同期確認】\n\n"
            "NotionシフトDB → キャスカン＆エスたまへ\n"
            "今日のシフトを同期します。\n\n"
            "実行しますか？",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

    elif action == "sync_caskan_week":
        keyboard = [
            [
                InlineKeyboardButton("✅ 実行する", callback_data="shiftdb_confirm:sync_caskan"),
                InlineKeyboardButton("❌ キャンセル", callback_data="shiftdb_confirm:cancel"),
            ]
        ]
        await query.edit_message_text(
            "🟢 【キャスカン同期確認】\n\n"
            "NotionシフトDB → キャスカンへ\n"
            "未着手シフトを同期します。\n\n"
            "実行しますか？",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

    elif action == "sync_estama_week":
        keyboard = [
            [
                InlineKeyboardButton("✅ 実行する", callback_data="shiftdb_confirm:sync_estama"),
                InlineKeyboardButton("❌ キャンセル", callback_data="shiftdb_confirm:cancel"),
            ]
        ]
        await query.edit_message_text(
            "🔵 【エスたま同期確認】\n\n"
            "NotionシフトDB → エスたまへ\n"
            "未同期シフトを同期します。\n\n"
            "実行しますか？",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

    elif action == "diff_week":
        await query.edit_message_text("⏳ NotionシフトDB・キャスカン・エスたまのシフトを比較中...")
        try:
            result = await browser_agent.execute_confirmed(
                '{"action": "diff_shifts_week", "params": {}}'
            )
            if len(result) > 4000:
                result = result[:4000] + "\n..."
            keyboard = [[InlineKeyboardButton("🔙 シフトDBメニューへ", callback_data="shiftdb:back")]]
            await query.edit_message_text(result, reply_markup=InlineKeyboardMarkup(keyboard))
        except Exception as e:
            await query.edit_message_text(f"❌ エラー: {str(e)[:300]}")

    elif action == "back":
        keyboard = [
            [
                InlineKeyboardButton("📋 今日のシフトを確認", callback_data="shiftdb:today"),
                InlineKeyboardButton("📆 今週のシフトを確認", callback_data="shiftdb:week"),
            ],
            [
                InlineKeyboardButton("⬜ 未着手シフト一覧", callback_data="shiftdb:pending"),
            ],
            [
                InlineKeyboardButton("🔄 今日のシフトを全同期", callback_data="shiftdb:sync_today"),
            ],
            [
                InlineKeyboardButton("🟢 キャスカンに同期", callback_data="shiftdb:sync_caskan"),
                InlineKeyboardButton("🔵 エスたまに同期", callback_data="shiftdb:sync_estama"),
            ],
            [
                InlineKeyboardButton("🔍 差異を確認する", callback_data="shiftdb:diff"),
            ],
        ]
        await query.edit_message_text(
            "📅 【シフトDB】\n\n"
            "NotionシフトDBをマスタとして、\n"
            "キャスカン・エスたまへのシフト同期を管理します。\n\n"
            "操作を選択してください:",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )


async def handle_shift_db_confirm_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """シフトDB同期確認コールバック"""
    query = update.callback_query
    await query.answer()

    data = query.data
    if not data.startswith("shiftdb_confirm:"):
        return

    action = data.replace("shiftdb_confirm:", "")

    if action == "cancel":
        await query.edit_message_text("❌ 操作をキャンセルしました。")
        return

    if action == "sync_all":
        await query.edit_message_text(
            "⏳ NotionシフトDB → キャスカン＆エスたまへ同期中...\n"
            "しばらくお待ちください。"
        )
        try:
            result = await browser_agent.execute_confirmed(
                '{"action": "sync_all_week", "params": {}}'
            )
            if len(result) > 4000:
                result = result[:4000] + "\n..."
            keyboard = [[InlineKeyboardButton("🔙 シフトDBメニューへ", callback_data="shiftdb:back")]]
            await query.edit_message_text(result, reply_markup=InlineKeyboardMarkup(keyboard))
        except Exception as e:
            await query.edit_message_text(f"❌ エラー: {str(e)[:300]}")

    elif action == "sync_caskan_week":
        await query.edit_message_text(
            "⏳ NotionシフトDB → キャスカンへ同期中...\n"
            "しばらくお待ちください。"
        )
        try:
            result = await browser_agent.execute_confirmed(
                '{"action": "sync_to_caskan_week", "params": {}}'
            )
            if len(result) > 4000:
                result = result[:4000] + "\n..."
            keyboard = [[InlineKeyboardButton("🔙 シフトDBメニューへ", callback_data="shiftdb:back")]]
            await query.edit_message_text(result, reply_markup=InlineKeyboardMarkup(keyboard))
        except Exception as e:
            await query.edit_message_text(f"❌ エラー: {str(e)[:300]}")

    elif action == "sync_estama_week":
        await query.edit_message_text(
            "⏳ NotionシフトDB → エスたまへ同期中...\n"
            "しばらくお待ちください。"
        )
        try:
            result = await browser_agent.execute_confirmed(
                '{"action": "sync_to_estama_week", "params": {}}'
            )
            if len(result) > 4000:
                result = result[:4000] + "\n..."
            keyboard = [[InlineKeyboardButton("🔙 シフトDBメニューへ", callback_data="shiftdb:back")]]
            await query.edit_message_text(result, reply_markup=InlineKeyboardMarkup(keyboard))
        except Exception as e:
            await query.edit_message_text(f"❌ エラー: {str(e)[:300]}")


# ─── 🤖 エージェント（ブラウザ自動操作）─────────────────────

async def handle_agent_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """エージェントメニューを表示"""
    keyboard = [
        [
            InlineKeyboardButton("🔄 1週間分のシフトを全同期", callback_data="agent:sync_week"),
        ],
        [
            InlineKeyboardButton("🟢 キャスカンに同期(1週間)", callback_data="agent:sync_caskan_week"),
            InlineKeyboardButton("🔵 エスたまに同期(1週間)", callback_data="agent:sync_estama_week"),
        ],
        [
            InlineKeyboardButton("📋 差異を確認する(1週間)", callback_data="agent:diff_week"),
        ],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        "🤖 【エージェント】\n\n"
        "NotionシフトDBをマスタとして\n"
        "キャスカン・エスたまへの同期を管理します。\n\n"
        "💡 自然言語でも操作できます:\n"
        "例: 『明日りおんを14時から23時でキャスカンに登録して』",
        reply_markup=reply_markup,
    )


async def handle_agent_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """エージェントコールバック処理"""
    query = update.callback_query
    await query.answer()

    data = query.data
    if not data.startswith("agent:"):
        return

    action = data.replace("agent:", "")

    if action == "sync_week":
        keyboard = [
            [
                InlineKeyboardButton("✅ 実行する", callback_data="agent_confirm:sync"),
                InlineKeyboardButton("❌ キャンセル", callback_data="agent_confirm:cancel"),
            ]
        ]
        await query.edit_message_text(
            "🔄 【全同期確認】\n\n"
            "NotionシフトDB → キャスカン＆エスたまへ\n"
            "今日のシフトを同期します。\n\n"
            "実行しますか？",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

    elif action == "sync_caskan_week":
        keyboard = [
            [
                InlineKeyboardButton("✅ 実行する", callback_data="agent_confirm:sync_caskan"),
                InlineKeyboardButton("❌ キャンセル", callback_data="agent_confirm:cancel"),
            ]
        ]
        await query.edit_message_text(
            "🟢 【キャスカン同期確認】\n\n"
            "NotionシフトDB → キャスカンへ\n"
            "未着手シフトを同期します。\n\n"
            "実行しますか？",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

    elif action == "sync_estama_week":
        keyboard = [
            [
                InlineKeyboardButton("✅ 実行する", callback_data="agent_confirm:sync_estama"),
                InlineKeyboardButton("❌ キャンセル", callback_data="agent_confirm:cancel"),
            ]
        ]
        await query.edit_message_text(
            "🔵 【エスたま同期確認】\n\n"
            "NotionシフトDB → エスたまへ\n"
            "未同期シフトを同期します。\n\n"
            "実行しますか？",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

    elif action == "diff_week":
        await query.edit_message_text("⏳ NotionシフトDB・キャスカン・エスたまのシフトを比較中...")
        try:
            result = await browser_agent.execute_confirmed(
                '{"action": "diff_shifts_week", "params": {}}'
            )
            if len(result) > 4000:
                result = result[:4000] + "\n..."
            await query.edit_message_text(result)
        except Exception as e:
            await query.edit_message_text(f"❌ エラー: {str(e)[:300]}")


async def handle_agent_confirm_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """エージェント確認コールバック処理"""
    query = update.callback_query
    await query.answer()

    data = query.data
    if not data.startswith("agent_confirm:"):
        return

    action = data.replace("agent_confirm:", "")

    if action == "cancel":
        await query.edit_message_text("❌ 操作をキャンセルしました。")
        return

    if action == "sync_week":
        await query.edit_message_text(
            "⏳ NotionシフトDB → キャスカン＆エスたまへ同期中...\n"
            "しばらくお待ちください。"
        )
        try:
            result = await browser_agent.execute_confirmed(
                '{"action": "sync_all_week", "params": {}}'
            )
            if len(result) > 4000:
                result = result[:4000] + "\n..."
            await query.edit_message_text(result)
        except Exception as e:
            await query.edit_message_text(f"❌ エラー: {str(e)[:300]}")

    elif action == "sync_caskan_week":
        await query.edit_message_text(
            "⏳ NotionシフトDB → キャスカンへ同期中...\n"
            "しばらくお待ちください。"
        )
        try:
            result = await browser_agent.execute_confirmed(
                '{"action": "sync_to_caskan_week", "params": {}}'
            )
            if len(result) > 4000:
                result = result[:4000] + "\n..."
            await query.edit_message_text(result)
        except Exception as e:
            await query.edit_message_text(f"❌ エラー: {str(e)[:300]}")

    elif action == "sync_estama_week":
        await query.edit_message_text(
            "⏳ NotionシフトDB → エスたまへ同期中...\n"
            "しばらくお待ちください。"
        )
        try:
            result = await browser_agent.execute_confirmed(
                '{"action": "sync_to_estama_week", "params": {}}'
            )
            if len(result) > 4000:
                result = result[:4000] + "\n..."
            await query.edit_message_text(result)
        except Exception as e:
            await query.edit_message_text(f"❌ エラー: {str(e)[:300]}")


async def handle_agent_nlp_confirm_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """エージェント自然言語操作の確認コールバック"""
    query = update.callback_query
    await query.answer()

    data = query.data
    if not data.startswith("agent_nlp:"):
        return

    action = data.replace("agent_nlp:", "")

    if action == "cancel":
        context.user_data.pop("agent_pending_action", None)
        await query.edit_message_text("❌ 操作をキャンセルしました。")
        return

    if action == "execute":
        pending = context.user_data.pop("agent_pending_action", None)
        if not pending:
            await query.edit_message_text("⚠️ 実行する操作が見つかりません。")
            return

        await query.edit_message_text("⏳ ブラウザで操作を実行中...\nしばらくお待ちください。")
        try:
            result = await browser_agent.execute_confirmed(pending)
            if len(result) > 4000:
                chunks = _split_text(result, 3800)
                await query.edit_message_text(chunks[0])
                for chunk in chunks[1:]:
                    await query.message.chat.send_message(chunk)
            else:
                await query.edit_message_text(result)
        except Exception as e:
            await query.edit_message_text(f"❌ エラー: {str(e)[:300]}")


# ─── 掲載ページ確認 ──────────────────────────────────────────────────────
MEDIA_LISTING_PAGES = [
    {"name": "公式HP", "url": "https://zenryoku-esthe.com"},
    {"name": "エステ魂", "url": "https://estama.jp/shop/43923/"},
    {"name": "メンズエステランキング", "url": "https://www.esthe-ranking.jp/sendai/shop-detail/3aec7842-f7f3-41e4-8cee-6bc4fda7b273/"},
    {"name": "リットリンク", "url": "https://lit.link/zenryoku_esthe"},
    {"name": "ブルースカイ", "url": "https://bsky.app/profile/zenryoku-esthe.bsky.social"},
]

async def handle_media_pages(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """掲載ページ確認 — 各媒体のお店ページリンクを表示"""
    keyboard = [
        [InlineKeyboardButton(p["name"], url=p["url"])]
        for p in MEDIA_LISTING_PAGES
    ]
    await update.message.reply_text(
        "🔗 【掲載ページ確認】\n\n"
        "各媒体のお店掲載ページです。\n"
        "タップして確認してください。",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


# ─── 各種管理画面 ─────────────────────────────────────────────────────────
ADMIN_DASHBOARDS = [
    # SNS / LINE
    {"name": "🟢 LINE公式（求人）", "url": "https://lin.ee/mcg18I6"},
    {"name": "🟢 LINE公式（集客）", "url": "https://lin.ee/oycKbIb"},
    {"name": "🟢 X（集客）@zr_sendai", "url": "https://x.com/zr_sendai"},
    {"name": "🟢 X（求人）@zenryoku_kyujin", "url": "https://x.com/zenryoku_kyujin"},
    # システム
    {"name": "💻 スクエア", "url": "https://www.notion.so/204f9507f0cf8166a890f670e5a59b2c"},
    {"name": "💻 エスたま 管理画面", "url": "https://estama.jp/login"},
    {"name": "🔗 予約フォーム（キャスカン）", "url": "https://r.caskan.jp/zenryoku1209"},
    {"name": "🔗 エステカード決済", "url": "https://pay2.star-pay.jp/site/pc/shop.php?payc=A4046"},
    # 業務フォーム
    {"name": "🔗 経費精算フォーム", "url": "https://docs.google.com/forms/d/e/1FAIpQLSdH4CHHVfAQgZeu068hdqBIoioo2kCZ7E-v7vjLyFsASfT1kQ/viewform"},
    {"name": "🔗 経費申請フォーム", "url": "https://docs.google.com/forms/d/e/1FAIpQLSfM__EXi1kt1wyXsMQDqKu9dXFZAI8-OQnuk2smxpKBta1Kzg/viewform"},
    {"name": "🔗 振込依頼フォーム", "url": "https://yoom.fun/5eee42a7-b4ff-49a8-8373-606c66495142/forms/shared/Cu2K735X9qaSAdMs45x6Bw"},
    {"name": "🔗 清掃チェックフォーム", "url": "https://forms.gle/6xfsmQMU6wmurJ1b8"},
    {"name": "🔗 レジスタシート作成フォーム", "url": "https://yoom.fun/5eee42a7-b4ff-49a8-8373-606c66495142/forms/shared/xzvuqgIiE6P-t3eWamtU1w"},
    {"name": "🔗 レジスタシート（Notion）", "url": "https://www.notion.so/257f9507f0cf80e7907ac0c919c44f56"},
    {"name": "🔗 画像アップロードフォーム", "url": "https://docs.google.com/forms/d/e/1FAIpQLSf48nywPeNr1aZ1QTHXeQsl28u3WkF62-zN82ZGYozURaK8xA/viewform"},
    {"name": "🔗 面談予約フォーム", "url": "https://yoom.fun/5eee42a7-b4ff-49a8-8373-606c66495142/forms/shared/2TPmMhYWn46vv-1EBVlnhw"},
    # ルーム
    {"name": "🎥 インルーム 金庫投函", "url": "https://d.kuku.lu/h3rc635z5"},
    {"name": "🎥 ラズルーム 金庫投函", "url": "https://d.kuku.lu/ar2gtn44r"},
    {"name": "🔗 ラズルーム 光熱費申請", "url": "https://x.gd/56ECe"},
]

async def handle_admin_dashboards(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """各種管理画面 — 管理画面リンク一覧を表示"""
    keyboard = [
        [InlineKeyboardButton(d["name"], url=d["url"])]
        for d in ADMIN_DASHBOARDS
    ]
    await update.message.reply_text(
        "⚙️ 【各種管理画面】\n\n"
        "各種SNS・媒体・業務フォームへのリンクです。\n"
        "タップして開いてください。",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


# ─── りおん自動運用 ───────────────────────────────────────────────────────
async def handle_rion_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """りおん自動運用メニュー"""
    if not RION_ENABLED:
        await update.message.reply_text("⚠️ tweepyが未インストールのため利用できません。\n`pip install tweepy` を実行してください。")
        return
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✍️ 今すぐ投稿（ランダム）", callback_data="rion:post_random")],
        [
            InlineKeyboardButton("🌅 おはよう", callback_data="rion:post_morning"),
            InlineKeyboardButton("📢 出勤告知", callback_data="rion:post_shift"),
        ],
        [
            InlineKeyboardButton("💄 美容ネタ", callback_data="rion:post_beauty"),
            InlineKeyboardButton("🧘 ピラティス", callback_data="rion:post_pilates"),
        ],
        [
            InlineKeyboardButton("✈️ 旅行/パワースポット", callback_data="rion:post_travel"),
            InlineKeyboardButton("🌙 おやすみ", callback_data="rion:post_night"),
        ],
        [InlineKeyboardButton("💬 仙台リプ実行（最大3件）", callback_data="rion:do_reply")],
    ])
    await update.message.reply_text(
        "🌸 【りおん自動運用】\n\n"
        "投稿タイプを選択するか、スケジューラーに任せてください。\n\n"
        "📅 自動投稿: 08:30 / 13:00 / 17:30 / 23:30\n"
        "💬 自動リプ: 30分おき（仙台関連KW）",
        reply_markup=keyboard,
    )


async def handle_rion_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """りおんメニューのインラインボタン処理"""
    query = update.callback_query
    await query.answer()
    action = query.data.replace("rion:", "")

    POST_TYPE_MAP = {
        "post_random":  None,
        "post_morning": "morning",
        "post_shift":   "shift_announce",
        "post_beauty":  "beauty",
        "post_pilates": "pilates",
        "post_travel":  "travel_power",
        "post_night":   "night",
    }

    if action in POST_TYPE_MAP:
        await query.edit_message_text("⏳ 投稿文を生成中...")
        import asyncio as _asyncio
        from rion_persona import generate_post
        post_type = POST_TYPE_MAP[action]
        try:
            text = await _asyncio.wait_for(
                _asyncio.get_event_loop().run_in_executor(None, generate_post, post_type),
                timeout=30.0
            )
        except _asyncio.TimeoutError:
            await query.edit_message_text("❌ 生成タイムアウト（30秒）。GEMINI_API_KEYを確認してください。")
            return
        if not text:
            await query.edit_message_text("❌ 生成に失敗しました。GEMINI_API_KEYが設定されているか確認してください。")
            return

        # プレビュー表示 → 確認ボタン
        context.user_data["rion_pending_post"] = text
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ この内容で投稿する", callback_data="rion:confirm_post")],
            [InlineKeyboardButton("🔄 再生成", callback_data=f"rion:{action}")],
            [InlineKeyboardButton("❌ キャンセル", callback_data="rion:cancel")],
        ])
        await query.edit_message_text(
            f"📝 【投稿プレビュー】\n\n{text}",
            reply_markup=keyboard,
        )

    elif action == "confirm_post":
        text = context.user_data.pop("rion_pending_post", "")
        if not text:
            await query.edit_message_text("❌ 投稿内容が見つかりません。")
            return
        await query.edit_message_text("⏳ 投稿中...")
        import asyncio
        success, err_msg = await asyncio.get_event_loop().run_in_executor(
            None, rion_auto_poster.post_tweet, text
        )
        if success:
            await query.edit_message_text(f"✅ 投稿しました！\n\n{text}")
        else:
            await query.edit_message_text(f"❌ 投稿に失敗しました。\n\n{err_msg}")

    elif action == "do_reply":
        await query.edit_message_text("⏳ 仙台関連ツイートを検索・返信中...")
        import asyncio
        count = await asyncio.get_event_loop().run_in_executor(
            None, rion_auto_poster.search_and_reply, 3
        )
        await query.edit_message_text(f"✅ {count}件に返信しました。")

    elif action == "cancel":
        context.user_data.pop("rion_pending_post", None)
        await query.edit_message_text("❌ キャンセルしました。")



# ─── その他 ──────────────────────────────────────────────────────────────
async def handle_unknown(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """ボタン以外のテキストメッセージ"""
    text = update.message.text.strip() if update.message.text else ""

    # AIシフト操作
    if context.user_data.get("ai_shift_awaiting"):
        handled = await handle_ai_shift_text(update, context)
        if handled:
            return

    # 仮想通貨取引入力待ち
    if context.user_data.get("crypto_awaiting_trade"):
        handled = await handle_crypto_trade_text(update, context)
        if handled:
            return

    # 新カテゴリ名入力待ち
    if context.user_data.get("photo_save_awaiting_name"):
        await handle_photo_name_text(update, context)
        return


# ─── メイン ─────────────────────────────────────────────

async def handle_auto_post_approval(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    data = query.data
    
    if data.startswith("approve_"):
        post_id = data.replace("approve_", "")
        try:
            await query.edit_message_caption(caption="✅ 投稿を承認しました！（HP・ゼロツー等への投稿をバックグラウンドで実行中です）")
        except:
            await query.edit_message_text(text="✅ 投稿を承認しました！（HP・ゼロツー等への投稿をバックグラウンドで実行中です）")
            
        import subprocess
        subprocess.Popen(["/root/.openclaw/workspace/zenryoku-telegram-bot/venv/bin/python", "/root/.openclaw/workspace/zenryoku-telegram-bot/execute_post.py", post_id])
        
    elif data.startswith("reject_"):
        try:
            await query.edit_message_caption(caption="❌ 自動投稿をキャンセルしました。")
        except:
            await query.edit_message_text(text="❌ 自動投稿をキャンセルしました。")

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



    # ブログ一斉投稿
    post_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex(r"^📲 ブログ一斉投稿$"), post_start)],
        states={
            POST_NAME:       [CallbackQueryHandler(post_name_callback, pattern="^post_title:")],
            POST_TITLE_FREE: [MessageHandler(filters.TEXT & ~filters.COMMAND & ~filters.Regex(MENU_BUTTONS_REGEX), post_title_free_text)],
            POST_BODY:       [MessageHandler(filters.TEXT & ~filters.COMMAND & ~filters.Regex(MENU_BUTTONS_REGEX), post_body_text)],
            POST_PHOTO: [
                MessageHandler(filters.PHOTO, post_photo),
                CallbackQueryHandler(post_photo_skip, pattern="^post_photo:skip$"),
                CallbackQueryHandler(post_photo, pattern="^post_photo:manual$"),
                CallbackQueryHandler(post_channel_name_callback, pattern="^post_ch:"),
                CallbackQueryHandler(post_channel_pick_callback, pattern="^post_ch_pick:"),
                CallbackQueryHandler(post_ch_back_callback, pattern="^post_ch_back$"),
            ],
        },
        fallbacks=[
            MessageHandler(filters.Regex(r"^❌ キャンセル$"), post_start),
            MessageHandler(filters.Regex(MENU_BUTTONS_REGEX), force_exit_conv),
        ],
        per_message=False,
        allow_reentry=True,
    )
    app.add_handler(post_conv)

    # 出稼ぎスケジュール登録
    guest_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex(r"^💼 出稼ぎスケジュール登録$"), guest_start)],
        states={
            GUEST_NAME: [CallbackQueryHandler(guest_name_callback, pattern="^guest_name:")],
            GUEST_START_DATE: [CallbackQueryHandler(guest_start_date_callback, pattern="^guest_start_date:")],
            GUEST_END_DATE: [CallbackQueryHandler(guest_end_date_callback, pattern="^guest_end_date:")],
            GUEST_START_TIME: [CallbackQueryHandler(guest_in_time_callback, pattern="^guest_in_time:")],
            GUEST_END_TIME: [CallbackQueryHandler(guest_out_time_callback, pattern="^guest_out_time:")],
            GUEST_EXPENSE: [MessageHandler(filters.TEXT & ~filters.COMMAND & ~filters.Regex(MENU_BUTTONS_REGEX), guest_expense_text)],
            GUEST_X_ACCOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND & ~filters.Regex(MENU_BUTTONS_REGEX), guest_x_account_text)],
        },
        fallbacks=[
            MessageHandler(filters.Regex(r"^❌ キャンセル$"), guest_start),
            MessageHandler(filters.Regex(MENU_BUTTONS_REGEX), force_exit_conv),
        ],
        per_message=False,
        allow_reentry=True,
    )
    app.add_handler(guest_conv)
    
    app.add_handler(CallbackQueryHandler(ai_exec_callback, pattern="^ai_exec:"))
    

    # コマンドの追加
    app.add_handler(CommandHandler("chatid", cmd_chatid))




    # 定期実行ジョブの追加 (朝8時、昼12時、夕方18時)
    jst = pytz.timezone('Asia/Tokyo')
    app.job_queue.run_daily(scheduled_sync, time(hour=8, minute=0, tzinfo=jst))
    app.job_queue.run_daily(scheduled_sync, time(hour=12, minute=0, tzinfo=jst))
    app.job_queue.run_daily(scheduled_sync, time(hour=18, minute=0, tzinfo=jst))

    # ─── 経費入力 ConversationHandler ───────────────────
    expense_conv = ConversationHandler(
        entry_points=[
            CommandHandler("expense", expense_start),
            MessageHandler(filters.Regex(r"^💴 経費を入力$"), expense_start),
        ],
        states={
            EXPENSE_DATE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND & ~filters.Regex(MENU_BUTTONS_REGEX), expense_date),
            ],
            EXPENSE_AMOUNT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND & ~filters.Regex(MENU_BUTTONS_REGEX), expense_amount),
            ],
            EXPENSE_CONTENT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND & ~filters.Regex(MENU_BUTTONS_REGEX), expense_content),
            ],
            EXPENSE_MEMO: [
                MessageHandler(filters.TEXT & ~filters.COMMAND & ~filters.Regex(MENU_BUTTONS_REGEX), expense_memo),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", expense_cancel),
            MessageHandler(filters.Regex(r"^❌ キャンセル$"), expense_cancel),
            MessageHandler(filters.Regex(MENU_BUTTONS_REGEX), force_exit_conv),
        ],
        allow_reentry=True,
    )

    # ─── ハンドラー登録 ──────────────────────────────────

    # ConversationHandler は最初に登録（優先度が高い）
    app.add_handler(expense_conv)

    # コマンド
    app.add_handler(CallbackQueryHandler(handle_auto_post_approval, pattern=r"^(approve_|reject_)"))
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.Regex(r"^🔑 APIキー更新$"), handle_api_update))
    app.add_handler(CommandHandler("images", handle_images))

    # メニューボタン — テキストメッセージ
    app.add_handler(MessageHandler(filters.Regex(r"^📸 画像管理$"), handle_images))
    app.add_handler(MessageHandler(filters.Regex(r"^🤖 エージェント$"), handle_agent_menu))
    app.add_handler(MessageHandler(filters.Regex(r"^📅 シフトDB$"), handle_shift_db_menu))
    app.add_handler(CommandHandler("shiftdb", handle_shift_db_menu))
    app.add_handler(MessageHandler(filters.Regex(r"^🔗 掲載ページ確認$"), handle_media_pages))
    app.add_handler(MessageHandler(filters.Regex(r"^⚙️ 各種管理画面$"), handle_admin_dashboards))
    app.add_handler(MessageHandler(filters.Regex(r"^🌸 りおん自動運用$"), handle_rion_menu))
    app.add_handler(CallbackQueryHandler(handle_rion_callback, pattern=r"^rion:"))

    # 画像メッセージ — 写真管理
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.UpdateType.CHANNEL_POSTS & filters.PHOTO, handle_channel_photo))

    # 新カテゴリ名入力（group=1で優先）
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND & ~filters.Regex(MENU_BUTTONS_REGEX),
        handle_photo_name_text
    ), group=1)

    # インラインボタンコールバック
    app.add_handler(CallbackQueryHandler(handle_img_up_callback, pattern=r"^img_up$"))
    app.add_handler(CallbackQueryHandler(handle_img_dl_callback, pattern=r"^img_dl$"))
    app.add_handler(CallbackQueryHandler(handle_dl_photo_callback, pattern=r"^dl_photo:"))
    app.add_handler(CallbackQueryHandler(handle_dl_cat_callback, pattern=r"^dl_cat:"))
    app.add_handler(CallbackQueryHandler(handle_dl_therapist_callback, pattern=r"^dl_therapist:"))

    app.add_handler(CallbackQueryHandler(handle_photo_save_callback, pattern=r"^photo_save:"))
    app.add_handler(CallbackQueryHandler(expense_confirm_callback, pattern=r"^expense_confirm:"))
    app.add_handler(CallbackQueryHandler(handle_diary_callback, pattern=r"^diary:[0-9]+$"))
    app.add_handler(CallbackQueryHandler(handle_diary_back_callback, pattern=r"^diary:back$"))
    app.add_handler(CallbackQueryHandler(handle_crypto_callback, pattern=r"^crypto:"))
    app.add_handler(CallbackQueryHandler(handle_agent_callback, pattern=r"^agent:"))
    app.add_handler(CallbackQueryHandler(handle_agent_confirm_callback, pattern=r"^agent_confirm:"))
    app.add_handler(CallbackQueryHandler(handle_agent_nlp_confirm_callback, pattern=r"^agent_nlp:"))
    app.add_handler(CallbackQueryHandler(handle_shift_db_callback, pattern=r"^shiftdb:"))
    app.add_handler(CallbackQueryHandler(handle_shift_db_confirm_callback, pattern=r"^shiftdb_confirm:"))

    # その他のテキストメッセージ（最後に登録）
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_unknown))

    # 起動時にTelegramコマンドメニューを更新
    async def post_init(application: Application) -> None:
        await application.bot.set_my_commands([
            BotCommand("start", "メインメニューを表示"),
            BotCommand("images", "画像管理"),
            BotCommand("agent", "AIブラウザエージェント"),
            BotCommand("shiftdb", "シフトDB（Notionマスタ同期）"),
        ])
        logger.info("Telegramコマンドメニューを更新しました")
        # Drive フォルダ構成をバックグラウンドで先読み
        import asyncio
        loop = asyncio.get_event_loop()
        from image_uploader import warm_drive_cache
        loop.run_in_executor(None, warm_drive_cache)

    if RION_ENABLED:
        async def post_init_with_rion(application):
            import asyncio
            await post_init(application)
            asyncio.create_task(rion_auto_poster.run_scheduler())
            logger.info("りおん自動投稿スケジューラーをバックグラウンドで起動しました")
        app.post_init = post_init_with_rion
    else:
        app.post_init = post_init

    # ポーリング開始
    logger.info("全力エステBot を起動しました。Ctrl+C で停止します。")
    app.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True,
        poll_interval=2.0,
        bootstrap_retries=5,
    )


import os
import json
import threading
import logging
from http.server import HTTPServer, SimpleHTTPRequestHandler

class WebAppHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory="/root/.openclaw/workspace/zenryoku-telegram-bot/public", **kwargs)

    def do_POST(self):
        if self.path == "/api/agreement/customer":
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)
            try:
                data = json.loads(post_data.decode('utf-8'))
                # 保存処理
                os.makedirs("/root/.openclaw/workspace/zenryoku-telegram-bot/agreements_data", exist_ok=True)
                filename = f"/root/.openclaw/workspace/zenryoku-telegram-bot/agreements_data/{data['name']}_{data['phone']}.json"
                with open(filename, 'w', encoding='utf-8') as f:
                    json.dump(data, f, ensure_ascii=False)
                
                # Bot管理者へ通知
                import requests
                token = os.environ.get("TELEGRAM_BOT_TOKEN")
                chat_id = "8419641279"
                msg = f"📝 【誓約書 受信】\n\nお客様から同意書が送信されました！\n名前: {data['name']}\n電話: {data['phone']}"
                requests.post(f"https://api.telegram.org/bot{token}/sendMessage", json={"chat_id": chat_id, "text": msg})
                
                self.send_response(200)
                self.send_header("Content-type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"success": true}')
            except Exception as e:
                logging.error(f"Agreement Error: {e}")
                self.send_response(500)
                self.end_headers()
        else:
            self.send_response(404)
            self.end_headers()

def keep_alive():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), WebAppHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()

if __name__ == "__main__":
    keep_alive()
    main()

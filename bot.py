#!/usr/bin/env python3
"""
全力エステ Telegram Bot (@zenryoku_bot)
機能:
  - /start  : メインメニューを表示
  - /news   : ニュース投稿文面を生成
  - /images : 画像管理（セラピスト写真をNotionに保存）
  - /expense: 経費を入力してNotionに記録
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
    append_expense_to_page,
    EXPENSE_PAGE_ID,
)
from image_uploader import upload_telegram_photo
from caskan_client import CaskanClient
from estama_client import EstamaClient
from seo_article import (
    generate_seo_article,
    get_template_preview,
    SEO_CHECKLIST,
    TEMPLATE_1_INFO,
    TEMPLATE_2_INFO,
)

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


# ─── 経費入力 ConversationHandler ステート ────────────────
EXPENSE_DATE, EXPENSE_AMOUNT, EXPENSE_CONTENT, EXPENSE_MEMO = range(4)


# ─── メニューキーボード ─────────────────────────────────
MENU_KEYBOARD = ReplyKeyboardMarkup(
    [
        [KeyboardButton("📰 ニュース生成"), KeyboardButton("📸 画像管理")],
        [KeyboardButton("💴 経費を入力"), KeyboardButton("📓 写メ日記")],
        [KeyboardButton("✍️ SEO記事作成")],
        [KeyboardButton("🏢 キャスカン"), KeyboardButton("🌟 エスたま")],
    ],
    resize_keyboard=True,
    one_time_keyboard=False,
)

# Notion セラピストDB URL
NOTION_THERAPIST_DB_URL = "https://www.notion.so/20af9507f0cf811a9397000b1fd6918d"

# Notionリンクボタン付きメインメニュー
MENU_INLINE_KEYBOARD = InlineKeyboardMarkup([
    [InlineKeyboardButton("🗒 Notion セラピスト一覧", url=NOTION_THERAPIST_DB_URL)],
])

# ─── /start コマンド ───────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """メインメニューを表示する"""
    welcome_text = (
        "こんにちは！全力エステBotへようこそ 💪\n\n"
        "以下のメニューから操作を選んでください。\n\n"
        "📰 ニュース生成 — エスたま用のニュース文面を作成\n"
        "📸 画像管理 — セラピストのNotionページに写真を保存\n"
        "💴 経費を入力 — 経費をNotionに記録\n"
        "📓 写メ日記 — テンプレートをコピーして使える\n"
        "✍️ SEO記事作成 — SEOテンプレートで記事ドラフトを生成\n"
        "🏢 キャスカン — 売上・スケジュール確認\n"
        "🌟 エスたま — ご案内状況・アピール"
    )
    # リプライキーボード（ボタンメニュー）を送信
    await update.message.reply_text(welcome_text, reply_markup=MENU_KEYBOARD)
    # Notionセラピスト一覧のインラインリンクボタンを別メッセージで送信
    await update.message.reply_text(
        "🗒 Notionのセラピスト一覧は下のボタンから開けます:",
        reply_markup=MENU_INLINE_KEYBOARD,
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

    # OpenAI APIでニュース文面を生成
    try:
        import openai
        client = openai.OpenAI()
        response = client.chat.completions.create(
            model="gpt-4.1-mini",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "あなたは仙台のメンズエステ「全力エステ」のスタッフです。"
                        "エスたま（メンズエステポータルサイト）のニュース投稿文面を作成してください。"
                        "タイトルは30文字以内、本文は1000〜1500文字で作成してください。"
                        "文体は丁寧で親しみやすく、集客効果が高い内容にしてください。"
                        "出力形式: 【タイトル】と【本文】を分けて記載してください。"
                    ),
                },
                {
                    "role": "user",
                    "content": f"テーマ: {topic}",
                },
            ],
            max_tokens=1500,
        )
        result = response.choices[0].message.content
        await update.message.reply_text(
            f"📰 【ニュース文面】\n\n{result}",
            reply_markup=MENU_KEYBOARD,
        )
    except Exception as e:
        logger.error(f"ニュース生成エラー: {e}")
        await update.message.reply_text(
            "📰 ニュース文面の生成に失敗しました。\n"
            "OPENAI_API_KEY が設定されているか確認してください。",
            reply_markup=MENU_KEYBOARD,
        )
    return True


# ─── /images コマンド（写真管理） ────────────────────────
async def handle_images(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/images コマンド — 写真管理メニュー"""
    await update.message.reply_text(
        "📸 【画像管理】\n\n"
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
        "short": "今日もありがとう",
        "text": (
            "今日もありがとう\n"
            '"癒された"って言ってもらえて嬉しかったよ。\n'
            "また疲れたらいつでも来てね"
        ),
    },
    {
        "id": "7",
        "title": "7️⃣ 話が盛り上がった時のお礼",
        "short": "今日はありがとう",
        "text": (
            "今日はありがとう\n"
            "いっぱい笑って楽しかったね\n"
            "あっという間だった～ また会おうね。"
        ),
    },
    {
        "id": "8",
        "title": "8️⃣ 久しぶりに会えた時のお礼",
        "short": "久しぶりにありがとう",
        "text": (
            "今日はありがとう\n"
            "久しぶりに会えて嬉しかったよ\n"
            "また間あかないうちに会えたらいいな。"
        ),
    },
]


async def handle_photo_diary(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """📓 写メ日記ボタン — テンプレート一覧を表示"""
    keyboard = []
    for tmpl in PHOTO_DIARY_TEMPLATES:
        keyboard.append([
            InlineKeyboardButton(
                tmpl["title"],
                callback_data=f"diary:{tmpl['id']}"
            )
        ])
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "📓 【写メ日記テンプレート集】\n\n"
        "エスたまランキング上位店舗を分析した8種のテンプレートです。\n"
        "使いたいテンプレートをタップしてください。",
        reply_markup=reply_markup,
    )


async def handle_diary_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """写メ日記テンプレート選択コールバック"""
    query = update.callback_query
    await query.answer()

    data = query.data
    if not data.startswith("diary:"):
        return

    tmpl_id = data.replace("diary:", "")
    tmpl = next((t for t in PHOTO_DIARY_TEMPLATES if t["id"] == tmpl_id), None)
    if not tmpl:
        await query.edit_message_text("⚠️ テンプレートが見つかりません。")
        return

    # テンプレート本文を送信（コピーしやすいようにコードブロックなし・プレーンテキスト）
    text = (
        f"{tmpl['title']}\n"
        f"タイトル例: {tmpl['short']}\n"
        f"{'─' * 20}\n"
        f"{tmpl['text']}\n"
        f"{'─' * 20}\n"
        "⬆️ 上の文面をコピーしてお使いください。"
    )

    # 戻るボタン付き
    back_keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 テンプレート一覧に戻る", callback_data="diary:back")]
    ])
    await query.edit_message_text(text, reply_markup=back_keyboard)


async def handle_diary_back_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """写メ日記テンプレート一覧に戻る"""
    query = update.callback_query
    await query.answer()

    keyboard = []
    for tmpl in PHOTO_DIARY_TEMPLATES:
        keyboard.append([
            InlineKeyboardButton(
                tmpl["title"],
                callback_data=f"diary:{tmpl['id']}"
            )
        ])
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(
        "📓 【写メ日記テンプレート集】\n\n"
        "エスたまランキング上位店舗を分析した8種のテンプレートです。\n"
        "使いたいテンプレートをタップしてください。",
        reply_markup=reply_markup,
    )


# ─── /expense コマンド（経費入力） ───────────────────────
async def expense_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """/expense または「💴 経費を入力」ボタン — 経費入力を開始"""
    today = datetime.now().strftime("%Y-%m-%d")
    await update.message.reply_text(
        "💴 【経費を入力】\n\n"
        "経費の日付を入力してください。\n"
        f"今日の日付はそのままEnterで確定できます（{today}）\n\n"
        "📅 日付（例: 2026-02-24）または「今日」と入力:",
        reply_markup=ReplyKeyboardMarkup(
            [[KeyboardButton("今日"), KeyboardButton("❌ キャンセル")]],
            resize_keyboard=True,
            one_time_keyboard=True,
        ),
    )
    return EXPENSE_DATE


async def expense_date(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """日付を受け取る"""
    text = update.message.text.strip()

    if text == "❌ キャンセル":
        await update.message.reply_text("❌ 経費入力をキャンセルしました。", reply_markup=MENU_KEYBOARD)
        return ConversationHandler.END

    # 「今日」または空の場合は今日の日付
    if text in ("今日", "today", ""):
        date_str = datetime.now().strftime("%Y-%m-%d")
    else:
        # 日付フォーマットを正規化
        import re
        # YYYY/MM/DD → YYYY-MM-DD
        text = re.sub(r"(\d{4})[/年](\d{1,2})[/月](\d{1,2})日?", r"\1-\2-\3", text)
        # MM/DD → YYYY-MM-DD
        text = re.sub(r"^(\d{1,2})[/月](\d{1,2})日?$", lambda m: f"{datetime.now().year}-{m.group(1).zfill(2)}-{m.group(2).zfill(2)}", text)
        date_str = text

    context.user_data["expense_date"] = date_str

    await update.message.reply_text(
        f"📅 日付: {date_str}\n\n"
        "💴 金額を入力してください（数字のみ、円単位）:\n"
        "例: 3500",
        reply_markup=ReplyKeyboardMarkup(
            [[KeyboardButton("❌ キャンセル")]],
            resize_keyboard=True,
            one_time_keyboard=True,
        ),
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
    """メモを受け取り、Notionに保存する"""
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

    confirm_text += "\nNotionに保存しますか？"

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

    await query.edit_message_text("⏳ Notionに経費を保存中...")

    success = append_expense_to_page(
        date=date_str,
        amount=amount,
        content=content,
        memo=memo,
    )

    if success:
        # コンテキストをクリア
        for key in ("expense_date", "expense_amount", "expense_content", "expense_memo"):
            context.user_data.pop(key, None)

        await query.edit_message_text(
            f"✅ 経費を記録しました！\n\n"
            f"📅 {date_str}　💴 ¥{amount:,}\n"
            f"📌 {content}"
            + (f"\n📝 {memo}" if memo else "")
            + f"\n\n📎 Notion: https://www.notion.so/{EXPENSE_PAGE_ID.replace('-', '')}"
        )
    else:
        await query.edit_message_text(
            "❌ Notionへの保存に失敗しました。\n"
            "NOTION_API_KEY が正しく設定されているか確認してください。"
        )


async def expense_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """経費入力をキャンセル"""
    await update.message.reply_text("❌ 経費入力をキャンセルしました。", reply_markup=MENU_KEYBOARD)
    return ConversationHandler.END


# ─── 🏪 キャスカン ハブ ──────────────────────────────────
async def handle_caskan_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """キャスカンメニュー"""
    from datetime import datetime
    now = datetime.now()
    this_month = f"{now.year}-{now.month:02d}"
    next_month_year = now.year if now.month < 12 else now.year + 1
    next_month_num = now.month + 1 if now.month < 12 else 1
    next_month = f"{next_month_year}-{next_month_num:02d}"

    keyboard = [
        [
            InlineKeyboardButton("📊 売上確認", callback_data="caskan:sales"),
            InlineKeyboardButton("📅 スケジュール", callback_data="caskan:schedule"),
        ],
        [
            InlineKeyboardButton(f"🗓 {now.month}月カレンダー", callback_data=f"caskan:calendar:{this_month}"),
            InlineKeyboardButton(f"🗓 {next_month_num}月カレンダー", callback_data=f"caskan:calendar:{next_month}"),
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
        "🏦 【キャスカン ハブ】\n\n"
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

    if action in ("sales", "home"):
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
        result = caskan.get_schedule()

        if "error" in result:
            await query.edit_message_text(f"❌ エラー: {result['error']}")
            return

        text = result.get("schedule_text", "情報なし")
        if len(text) > 3500:
            text = text[:3500] + "\n\n... (続きは管理画面で確認)"

        await query.edit_message_text(f"📅 【キャスカン スケジュール】\n{text}")

    elif action == "reservations":
        await query.edit_message_text("⏳ 予約情報を取得中...")
        result = caskan.get_reservations()

        if "error" in result:
            await query.edit_message_text(f"❌ エラー: {result['error']}")
            return

        reservations = result.get("reservations", [])
        if reservations:
            text = "📋 【キャスカン 予約一覧】\n\n"
            for r in reservations[:15]:
                text += f"• {r}\n"
            text += f"\n合計: {result.get('count', 0)}件"
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

    elif action.startswith("calendar:"):
        # caskan:calendar:YYYY-MM
        ym = action.replace("calendar:", "")
        try:
            year, month = int(ym.split("-")[0]), int(ym.split("-")[1])
        except (ValueError, IndexError):
            await query.edit_message_text("❌ 日付形式エラー")
            return

        await query.edit_message_text(f"⏳ {year}年{month}月のシフト・ルーム情報を取得中...\n(数分かかる場合があります)")

        data_monthly = caskan.get_monthly_shift(year, month)
        if "error" in data_monthly:
            await query.edit_message_text(f"❌ エラー: {data_monthly['error']}")
            return

        # カレンダー画像を生成
        from calendar_image import generate_calendar_image
        img_buf = generate_calendar_image(data_monthly)

        # 前月・翌月ナビゲーションボタン
        prev_year = year if month > 1 else year - 1
        prev_month = month - 1 if month > 1 else 12
        next_year = year if month < 12 else year + 1
        next_month_n = month + 1 if month < 12 else 1

        nav_keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    f"◀ {prev_month}月",
                    callback_data=f"caskan:calendar:{prev_year}-{prev_month:02d}"
                ),
                InlineKeyboardButton(
                    f"{next_month_n}月 ▶",
                    callback_data=f"caskan:calendar:{next_year}-{next_month_n:02d}"
                ),
            ],
            [
                InlineKeyboardButton("🔙 キャスカンメニューに戻る", callback_data="caskan:back_menu"),
            ],
        ])

        # 画像を新規メッセージとして送信（edit_messageでは画像送信不可のため、元メッセージを削除して新規送信）
        from telegram import InputFile
        await query.delete_message()
        await query.message.chat.send_photo(
            photo=img_buf,
            caption=f"🗓 {year}年{month}月 シフト・ルーム空き状況",
            reply_markup=nav_keyboard,
        )

    elif action == "back_menu":
        # キャスカンメニューに戻る（インラインキーボードを再表示）
        from datetime import datetime
        now = datetime.now()
        this_month = f"{now.year}-{now.month:02d}"
        next_month_year = now.year if now.month < 12 else now.year + 1
        next_month_num = now.month + 1 if now.month < 12 else 1
        next_month = f"{next_month_year}-{next_month_num:02d}"

        keyboard = [
            [
                InlineKeyboardButton("📊 売上確認", callback_data="caskan:sales"),
                InlineKeyboardButton("📅 スケジュール", callback_data="caskan:schedule"),
            ],
            [
                InlineKeyboardButton(f"🗓 {now.month}月カレンダー", callback_data=f"caskan:calendar:{this_month}"),
                InlineKeyboardButton(f"🗓 {next_month_num}月カレンダー", callback_data=f"caskan:calendar:{next_month}"),
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
        await query.edit_message_text(
            "🏦 【キャスカン ハブ】\n\n"
            "キャスカン管理画面の情報を確認できます。\n"
            "操作を選択してください:",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )


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
        if info.get("plan"):
            text_parts.append(f"📋 プラン: {info['plan']}")
        if info.get("contract_period"):
            text_parts.append(f"📅 {info['contract_period']}")
        if info.get("points"):
            text_parts.append(f"⭐ ポイント: {info['points']}pt")

        if info.get("notifications"):
            text_parts.append("\n🔔 通知:")
            for notif in info["notifications"][:5]:
                if notif and len(notif) > 3:
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
        result = estama.get_schedule()

        if "error" in result:
            await query.edit_message_text(f"❌ エラー: {result['error']}")
            return

        text = result.get("schedule_text", "情報なし")
        if len(text) > 3500:
            text = text[:3500] + "\n\n... (続きは管理画面で確認)"

        await query.edit_message_text(f"📅 【エスたま 出勤表】\n\n{text}")

    elif action == "reservations":
        await query.edit_message_text("⏳ 予約情報を取得中...")
        result = estama.get_reservations()

        if "error" in result:
            await query.edit_message_text(f"❌ エラー: {result['error']}")
            return

        reservations = result.get("reservations", [])
        if reservations:
            text = "📋 【エスたま 予約一覧】\n\n"
            for r in reservations[:15]:
                text += f"• {r}\n"
            text += f"\n合計: {result.get('count', 0)}件"
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
                "• OPENAI_API_KEY が設定されていない\n"
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


# ─── その他 ──────────────────────────────────────────────
async def handle_unknown(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """未知のテキストメッセージ"""
    text = update.message.text.strip() if update.message.text else ""

    # SEOキーワード入力待ちの場合
    if context.user_data.get("seo_awaiting_keyword"):
        handled = await handle_seo_keyword_input(update, context)
        if handled:
            return

    # ニューストピック待ちの場合
    if context.user_data.get("awaiting_news_topic"):
        handled = await handle_news_topic(update, context)
        if handled:
            return

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

    # ─── 経費入力 ConversationHandler ───────────────────
    expense_conv = ConversationHandler(
        entry_points=[
            CommandHandler("expense", expense_start),
            MessageHandler(filters.Regex(r"^💴 経費を入力$"), expense_start),
        ],
        states={
            EXPENSE_DATE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, expense_date),
            ],
            EXPENSE_AMOUNT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, expense_amount),
            ],
            EXPENSE_CONTENT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, expense_content),
            ],
            EXPENSE_MEMO: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, expense_memo),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", expense_cancel),
            MessageHandler(filters.Regex(r"^❌ キャンセル$"), expense_cancel),
        ],
        allow_reentry=True,
    )

    # ─── ハンドラー登録 ──────────────────────────────────

    # ConversationHandler は最初に登録（優先度が高い）
    app.add_handler(expense_conv)

    # コマンド
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("news", handle_news))
    app.add_handler(CommandHandler("images", handle_images))

    # メニューボタン — テキストメッセージ
    app.add_handler(MessageHandler(filters.Regex(r"^📰 ニュース生成$"), handle_news))
    app.add_handler(MessageHandler(filters.Regex(r"^📸 画像管理$"), handle_images))
    app.add_handler(MessageHandler(filters.Regex(r"^📓 写メ日記$"), handle_photo_diary))
    app.add_handler(MessageHandler(filters.Regex(r"^🏢 キャスカン$"), handle_caskan_menu))
    app.add_handler(MessageHandler(filters.Regex(r"^🌟 エスたま$"), handle_estama_menu))
    app.add_handler(MessageHandler(filters.Regex(r"^✍️ SEO記事作成$"), handle_seo_menu))
    app.add_handler(CommandHandler("seo", handle_seo_menu))

    # 画像メッセージ — 写真管理
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))

    # インラインボタンコールバック
    app.add_handler(CallbackQueryHandler(handle_photo_save_callback, pattern=r"^photo_save:"))
    app.add_handler(CallbackQueryHandler(handle_caskan_callback, pattern=r"^caskan:"))
    app.add_handler(CallbackQueryHandler(handle_estama_callback, pattern=r"^estama:"))
    app.add_handler(CallbackQueryHandler(handle_estama_confirm_callback, pattern=r"^estama_confirm:"))
    app.add_handler(CallbackQueryHandler(expense_confirm_callback, pattern=r"^expense_confirm:"))
    app.add_handler(CallbackQueryHandler(handle_diary_callback, pattern=r"^diary:[0-9]+$"))
    app.add_handler(CallbackQueryHandler(handle_diary_back_callback, pattern=r"^diary:back$"))
    app.add_handler(CallbackQueryHandler(handle_seo_callback, pattern=r"^seo:"))

    # その他のテキストメッセージ（最後に登録）
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_unknown))

    # 起動時にTelegramコマンドメニューを更新
    async def post_init(application: Application) -> None:
        await application.bot.set_my_commands([
            BotCommand("start", "メインメニューを表示"),
            BotCommand("news", "ニュース投稿文面を生成"),
            BotCommand("images", "画像管理"),
            BotCommand("seo", "SEO記事ドラフトを生成"),
        ])
        logger.info("Telegramコマンドメニューを更新しました")

    app.post_init = post_init

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

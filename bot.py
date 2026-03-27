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

if not BOT_TOKEN:
    raise ValueError("環境変数 TELEGRAM_BOT_TOKEN が設定されていません")

# ログ設定
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


# ─── 経費入力 ConversationHandler ステート ────────────────
EXPENSE_DATE, EXPENSE_AMOUNT, EXPENSE_CONTENT, EXPENSE_MEMO = range(4)


# ─── メニューキーボード ─────────────────────────────────
MENU_KEYBOARD = ReplyKeyboardMarkup(
    [
        [KeyboardButton("📰 ニュース生成"), KeyboardButton("📸 画像管理")],
        [KeyboardButton("💴 経費を入力"), KeyboardButton("📓 写メ日記")],
        [KeyboardButton("✍️ SEO記事作成")],
        [KeyboardButton("💰 仮想通貨"), KeyboardButton("🤖 エージェント")],
        [KeyboardButton("📅 シフトDB")],
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
        "📰 ニュース生成 / ✍️ SEO記事作成\n"
        "　エスたま向けの投稿文面・記事をAI生成\n\n"
        "💴 経費を入力\n"
        "　Googleスプレッドシートに経費を記録\n\n"
        "📓 写メ日記 / 📸 画像管理\n"
        "　テンプレート表示・セラピスト写真をNotionに保存",
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
            result = await browser_agent.execute_confirmed(
                '{"action": "notion_get_shifts", "params": {}}'
            )
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
            result = await browser_agent.execute_confirmed(
                '{"action": "notion_get_shifts", "params": {"days_range": 6}}'
            )
            if len(result) > 4000:
                result = result[:4000] + "\n..."
            keyboard = [[InlineKeyboardButton("🔙 シフトDBメニューへ", callback_data="shiftdb:back")]]
            await query.edit_message_text(result, reply_markup=InlineKeyboardMarkup(keyboard))
        except Exception as e:
            await query.edit_message_text(f"❌ エラー: {str(e)[:300]}")

    elif action == "pending":
        await query.edit_message_text("⏳ 未着手シフトを取得中...")
        try:
            result = await browser_agent.execute_confirmed(
                '{"action": "notion_get_pending", "params": {"target": "caskan"}}'
            )
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

    elif action == "sync_caskan":
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

    elif action == "sync_estama":
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

    elif action == "diff":
        await query.edit_message_text("⏳ NotionシフトDB・キャスカン・エスたまのシフトを比較中...")
        try:
            result = await browser_agent.execute_confirmed(
                '{"action": "diff_shifts", "params": {}}'
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
                '{"action": "sync_all", "params": {}}'
            )
            if len(result) > 4000:
                result = result[:4000] + "\n..."
            keyboard = [[InlineKeyboardButton("🔙 シフトDBメニューへ", callback_data="shiftdb:back")]]
            await query.edit_message_text(result, reply_markup=InlineKeyboardMarkup(keyboard))
        except Exception as e:
            await query.edit_message_text(f"❌ エラー: {str(e)[:300]}")

    elif action == "sync_caskan":
        await query.edit_message_text(
            "⏳ NotionシフトDB → キャスカンへ同期中...\n"
            "しばらくお待ちください。"
        )
        try:
            result = await browser_agent.execute_confirmed(
                '{"action": "sync_to_caskan", "params": {}}'
            )
            if len(result) > 4000:
                result = result[:4000] + "\n..."
            keyboard = [[InlineKeyboardButton("🔙 シフトDBメニューへ", callback_data="shiftdb:back")]]
            await query.edit_message_text(result, reply_markup=InlineKeyboardMarkup(keyboard))
        except Exception as e:
            await query.edit_message_text(f"❌ エラー: {str(e)[:300]}")

    elif action == "sync_estama":
        await query.edit_message_text(
            "⏳ NotionシフトDB → エスたまへ同期中...\n"
            "しばらくお待ちください。"
        )
        try:
            result = await browser_agent.execute_confirmed(
                '{"action": "sync_to_estama", "params": {}}'
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
            InlineKeyboardButton("🔄 今日のシフトを全同期", callback_data="agent:sync"),
        ],
        [
            InlineKeyboardButton("🟢 キャスカンに同期", callback_data="agent:sync_caskan"),
            InlineKeyboardButton("🔵 エスたまに同期", callback_data="agent:sync_estama"),
        ],
        [
            InlineKeyboardButton("📋 差異を確認する", callback_data="agent:diff"),
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

    if action == "sync":
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

    elif action == "sync_caskan":
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

    elif action == "sync_estama":
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

    elif action == "diff":
        await query.edit_message_text("⏳ NotionシフトDB・キャスカン・エスたまのシフトを比較中...")
        try:
            result = await browser_agent.execute_confirmed(
                '{"action": "diff_shifts", "params": {}}'
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

    if action == "sync":
        await query.edit_message_text(
            "⏳ NotionシフトDB → キャスカン＆エスたまへ同期中...\n"
            "しばらくお待ちください。"
        )
        try:
            result = await browser_agent.execute_confirmed(
                '{"action": "sync_all", "params": {}}'
            )
            if len(result) > 4000:
                result = result[:4000] + "\n..."
            await query.edit_message_text(result)
        except Exception as e:
            await query.edit_message_text(f"❌ エラー: {str(e)[:300]}")

    elif action == "sync_caskan":
        await query.edit_message_text(
            "⏳ NotionシフトDB → キャスカンへ同期中...\n"
            "しばらくお待ちください。"
        )
        try:
            result = await browser_agent.execute_confirmed(
                '{"action": "sync_to_caskan", "params": {}}'
            )
            if len(result) > 4000:
                result = result[:4000] + "\n..."
            await query.edit_message_text(result)
        except Exception as e:
            await query.edit_message_text(f"❌ エラー: {str(e)[:300]}")

    elif action == "sync_estama":
        await query.edit_message_text(
            "⏳ NotionシフトDB → エスたまへ同期中...\n"
            "しばらくお待ちください。"
        )
        try:
            result = await browser_agent.execute_confirmed(
                '{"action": "sync_to_estama", "params": {}}'
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


# ─── その他 ──────────────────────────────────────────────────────────────
async def handle_unknown(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """ボタン以外のテキストメッセージ — Gemini LLMで解析して適切な操作を実行"""
    text = update.message.text.strip() if update.message.text else ""

    # SEOキーワード入力待ちの場合（専用フローを優先）
    if context.user_data.get("seo_awaiting_keyword"):
        handled = await handle_seo_keyword_input(update, context)
        if handled:
            return

    # ニューストピック待ちの場合（専用フローを優先）
    if context.user_data.get("awaiting_news_topic"):
        handled = await handle_news_topic(update, context)
        if handled:
            return

    # 仮想通貨取引入力待ちの場合（専用フローを優先）
    if context.user_data.get("crypto_awaiting_trade"):
        handled = await handle_crypto_trade_text(update, context)
        if handled:
            return

    # テキストメッセージは常にGemini LLMで解析して実行
    if not text:
        return

    await update.message.reply_text("🧠 AIが指示を解析中...")

    import json as _json
    try:
        confirmation, action_json = await browser_agent.process_agent_command(text)
    except Exception as e:
        await update.message.reply_text(
            f"❌ 解析エラー: {str(e)[:300]}\n\n"
            "もう一度入力してください。",
            reply_markup=MENU_KEYBOARD,
        )
        return

    try:
        intent = _json.loads(action_json)
    except Exception:
        intent = {}

    action_name = intent.get("action", "")
    actions_list = intent.get("actions", [])

    # 読み取り系・差異確認は確認なしで即実行
    read_actions = {
        "caskan_get_shifts", "caskan_get_casts", "caskan_get_rooms",
        "estama_get_schedule", "estama_get_therapists", "diff_shifts", "unknown",
        "notion_get_shifts", "notion_get_pending",
    }

    is_read_only = (
        action_name in read_actions
        or (actions_list and all(a.get("action") in read_actions for a in actions_list))
    )

    if is_read_only:
        await update.message.reply_text("⏳ ブラウザで情報を取得中...")
        try:
            result = await browser_agent.execute_confirmed(action_json)
            if len(result) > 4000:
                chunks = _split_text(result, 3800)
                for chunk in chunks:
                    await update.message.reply_text(chunk)
            else:
                await update.message.reply_text(result)
        except Exception as e:
            await update.message.reply_text(f"❌ 実行エラー: {str(e)[:300]}")
    else:
        # 書き込み系は確認を求める
        context.user_data["agent_pending_action"] = action_json

        keyboard = [
            [
                InlineKeyboardButton("✅ 実行する", callback_data="agent_nlp:execute"),
                InlineKeyboardButton("❌ キャンセル", callback_data="agent_nlp:cancel"),
            ]
        ]
        await update.message.reply_text(
            f"🤖 【操作確認】\n\n{confirmation}\n\n実行しますか？",
            reply_markup=InlineKeyboardMarkup(keyboard),
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
    app.add_handler(MessageHandler(filters.Regex(r"^✍️ SEO記事作成$"), handle_seo_menu))
    app.add_handler(CommandHandler("seo", handle_seo_menu))
    app.add_handler(MessageHandler(filters.Regex(r"^💰 仮想通貨$"), handle_crypto_menu))
    app.add_handler(MessageHandler(filters.Regex(r"^🤖 エージェント$"), handle_agent_menu))
    app.add_handler(CommandHandler("agent", handle_agent_menu))
    app.add_handler(MessageHandler(filters.Regex(r"^📅 シフトDB$"), handle_shift_db_menu))
    app.add_handler(CommandHandler("shiftdb", handle_shift_db_menu))

    # 画像メッセージ — 写真管理
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))

    # インラインボタンコールバック
    app.add_handler(CallbackQueryHandler(handle_photo_save_callback, pattern=r"^photo_save:"))
    app.add_handler(CallbackQueryHandler(expense_confirm_callback, pattern=r"^expense_confirm:"))
    app.add_handler(CallbackQueryHandler(handle_diary_callback, pattern=r"^diary:[0-9]+$"))
    app.add_handler(CallbackQueryHandler(handle_diary_back_callback, pattern=r"^diary:back$"))
    app.add_handler(CallbackQueryHandler(handle_seo_callback, pattern=r"^seo:"))
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
            BotCommand("news", "ニュース投稿文面を生成"),
            BotCommand("images", "画像管理"),
            BotCommand("seo", "SEO記事ドラフトを生成"),
            BotCommand("agent", "AIブラウザエージェント"),
            BotCommand("shiftdb", "シフトDB（Notionマスタ同期）"),
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


import os
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

class DummyHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"Bot is running!")

def keep_alive():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), DummyHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()

if __name__ == "__main__":
    keep_alive()
    main()

import asyncio
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

logger = logging.getLogger(__name__)

async def request_approval(bot_token, chat_id, post_type, text, image_path):
    from telegram import Bot
    bot = Bot(bot_token)
    keyboard = [
        [InlineKeyboardButton("✅ 承認して投稿", callback_data=f"approve:{post_type}")],
        [InlineKeyboardButton("❌ キャンセル", callback_data=f"reject:{post_type}")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    msg = f"【自動投稿の承認待ち】\n\n以下の内容でエスたま・キャスカン・Xに投稿してもよろしいですか？\n\n{text}"
    
    if image_path:
        with open(image_path, "rb") as photo:
            await bot.send_photo(chat_id=chat_id, photo=photo, caption=msg, reply_markup=reply_markup)
    else:
        await bot.send_message(chat_id=chat_id, text=msg, reply_markup=reply_markup)


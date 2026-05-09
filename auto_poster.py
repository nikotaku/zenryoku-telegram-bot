import asyncio
import sys
import os
import random
import logging
import uuid
import json
from datetime import datetime, timedelta
from dotenv import load_dotenv
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup

sys.path.append('/root/.openclaw/workspace/zenryoku-telegram-bot')
load_dotenv('/root/.openclaw/workspace/zenryoku-telegram-bot/.env')

from caskan_browser import CaskanBrowser
import bs4

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

LOCAL_IMAGES_DIR = "/root/.openclaw/workspace/zenryoku-telegram-bot/local_images"
PENDING_POSTS_DIR = "/root/.openclaw/workspace/zenryoku-telegram-bot/pending_posts"
ADMIN_CHAT_ID = "8419641279"

os.makedirs(PENDING_POSTS_DIR, exist_ok=True)

PROMO_TEMPLATES = [
    {
        "title": "🔔お得なご案内🔔",
        "body": "口コミ割引始めました！✨\nエステ魂への口コミの投稿で次回3,000円OFF⭕\n\n日頃の感謝を込めて、皆様の温かいお声をお待ちしております💆‍♀️✨\nご予約はWebまたはお電話にて受付中📞"
    },
    {
        "title": "✨ご新規様大歓迎✨お得なキャンペーン",
        "body": "はじめて「全力エステ」をご利用されるお客様へ🔰\n\n当店では初回ご利用のお客様向けに特別な割引をご用意しております！\n日々の疲れを癒やす極上のリラクゼーションをぜひご体感ください💆‍♂️\n\nあなたにぴったりのセラピストが、心を込めておもてなしいたします🌿\n皆様のご来店を心よりお待ちしております！"
    },
    {
        "title": "🌙お仕事帰りのお立ち寄り大歓迎🌙",
        "body": "本日もお仕事お疲れ様です👔✨\n\n夕方以降のお時間はご予約が埋まりやすくなっております。\n「今から行けるかな？」と思ったら、お早めにお電話・Webからのご予約がおすすめです📱\n\nがんばった自分へのご褒美に、全力の癒やしをお届けします💆‍♀️💖\n極上の空間でおくつろぎくださいませ。"
    }
]

def get_random_image(therapist_name=None):
    target_dir = LOCAL_IMAGES_DIR
    if therapist_name:
        specific_dir = os.path.join(LOCAL_IMAGES_DIR, therapist_name)
        if os.path.exists(specific_dir) and os.listdir(specific_dir):
            target_dir = specific_dir
            
    if not os.path.exists(target_dir):
        return None
        
    all_images = []
    for root, dirs, files in os.walk(target_dir):
        for file in files:
            if file.lower().endswith(('.png', '.jpg', '.jpeg')):
                all_images.append(os.path.join(root, file))
                
    if all_images:
        return random.choice(all_images)
    return None

async def send_approval_request(title, body, image_path, post_type):
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token or not ADMIN_CHAT_ID:
        logger.error("Token or Admin ID missing.")
        return
    
    post_id = str(uuid.uuid4())
    
    post_data = {
        "id": post_id,
        "type": post_type,
        "title": title,
        "body": body,
        "image_path": image_path,
        "created_at": datetime.now().isoformat()
    }
    
    with open(os.path.join(PENDING_POSTS_DIR, f"{post_id}.json"), "w", encoding="utf-8") as f:
        json.dump(post_data, f, ensure_ascii=False)
        
    bot = Bot(token)
    
    keyboard = [
        [InlineKeyboardButton("✅ 承認して投稿", callback_data=f"approve_{post_id}")],
        [InlineKeyboardButton("❌ キャンセル", callback_data=f"reject_{post_id}")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    msg_text = f"【自動投稿の承認待ち】\n\n以下の内容で投稿してもよろしいですか？\n\n■タイトル\n{title}\n\n■本文\n{body}"
    
    try:
        if image_path and os.path.exists(image_path):
            with open(image_path, "rb") as photo:
                await bot.send_photo(chat_id=ADMIN_CHAT_ID, photo=photo, caption=msg_text, reply_markup=reply_markup)
        else:
            await bot.send_message(chat_id=ADMIN_CHAT_ID, text=msg_text + "\n\n(※画像なし)", reply_markup=reply_markup)
        logger.info(f"Approval request sent for {post_id}")
    except Exception as e:
        logger.error(f"Failed to send approval request: {e}")

async def post_shift(target="today"):
    logger.info(f"シフト情報({target})の構築を開始します...")
    
    browser = CaskanBrowser()
    try:
        success = await browser.login()
        if not success:
            logger.error("Caskan Login failed.")
            return
            
        page = browser._page
        
        # 1. キャストのX URLをNotionから収集
        x_urls = {}
        try:
            from notion_client import NOTION_MASTER_DB_ID, _headers
            url = f"https://api.notion.com/v1/databases/{NOTION_MASTER_DB_ID}/query"
            body = {
                "filter": {
                    "or": [
                        {"property": "タグ", "multi_select": {"contains": "在籍セラピスト"}},
                        {"property": "タグ", "multi_select": {"contains": "出稼ぎセラピスト"}}
                    ]
                }
            }
            resp = requests.post(url, headers=_headers(), json=body, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                for item in data.get("results", []):
                    props = item.get("properties", {})
                    # タイトル(名前)
                    name_prop = props.get("名前", props.get("title", {}))
                    name = ""
                    if name_prop and name_prop.get("title"):
                        name = name_prop["title"][0].get("plain_text", "")
                    
                    # XのURL
                    x_url = "https://x.com/zenryoku_sendai"
                    x_prop = props.get("Xアカウント", {})
                    if x_prop and x_prop.get("rich_text") and len(x_prop["rich_text"]) > 0:
                        x_url = x_prop["rich_text"][0].get("plain_text", x_url)
                    elif x_prop and x_prop.get("url"):
                        x_url = x_prop.get("url")
                        
                    if name:
                        x_urls[name] = x_url
        except Exception as e:
            logger.error(f"Failed to fetch X URLs from Notion: {e}")
        
        # 2. シフト情報を取得
        if target == "tomorrow":
            d = datetime.now() + timedelta(days=1)
            target_date = d.strftime("%Y-%m-%d")
            display_date = f"{d.month}月{d.day}日"
            title = "明日のスタメン発表🆕"
            header_text = f"{display_date}の出勤情報のご案内です♪"
        else:
            d = datetime.now()
            target_date = d.strftime("%Y-%m-%d")
            display_date = f"{d.month}月{d.day}日"
            title = "🔔本日の出勤速報🔔"
            header_text = f"{display_date}出勤速報🆕"
            
        schedule = await browser.get_shift_page(target_date)
        raw_shifts = [s for s in schedule.get('shifts', []) if s['date'] == target_date]
        
        # 名前で重複排除（同じ日の同じ人が複数枠ある場合に対応）
        unique_shifts = {}
        for s in raw_shifts:
            if s['name'] not in unique_shifts:
                unique_shifts[s['name']] = s
            else:
                # 既存のシフトより開始時間が早い場合は上書き
                if s['start'] < unique_shifts[s['name']]['start']:
                    unique_shifts[s['name']]['start'] = s['start']
        
        shifts = list(unique_shifts.values())
        shifts.sort(key=lambda x: x['start'])
        
        if not shifts:
            logger.warning(f"{target_date}のシフト情報がありません。")
            # 空でもいったんテスト用に作成する
            picked_therapist = "のぞみ"
            earliest_time = "24:00"
        else:
            picked_therapist = shifts[0]['name']
            earliest_time = shifts[0]['start']
            
        # 本文組み立て
        body = f"{header_text}\n\n"
        for s in shifts:
            name = s['name']
            start = s['start']
            body += f"🌻{name}\n"
            
        if earliest_time != "24:00":
            body += f"\n🕐最短{earliest_time}〜ご案内🉑\n"
        else:
            body += "\n"
            
        if target == "today":
            body += "\nご予約はお電話、またはWebからお待ちしております💆‍♀️✨\n皆さまのご来店を心よりお待ちしております！"
        else:
            body += "\nご予約はお電話、またはWebからお待ちしております💆‍♀️✨\n明日も皆様のご来店を心よりお待ちしております！"
            
        # 画像を選ぶ
        image_path = get_random_image(picked_therapist)
        
        await send_approval_request(title, body, image_path, target)
        
    except Exception as e:
        logger.error(f"Error in post_shift: {e}")
    finally:
        await browser.close()

async def post_promo():
    logger.info("お得なご案内(プロモ)の承認リクエストを作成します...")
    day_of_year = datetime.now().timetuple().tm_yday
    pattern_index = day_of_year % 3
    template = PROMO_TEMPLATES[pattern_index]
    
    image_path = get_random_image()
    
    title = template['title']
    body = template['body']
    
    await send_approval_request(title, body, image_path, "promo")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(1)
    mode = sys.argv[1]
    if mode == "today":
        asyncio.run(post_shift("today"))
    elif mode == "tomorrow":
        asyncio.run(post_shift("tomorrow"))
    elif mode == "promo":
        asyncio.run(post_promo())

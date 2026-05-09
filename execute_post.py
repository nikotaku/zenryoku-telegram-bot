import asyncio
import sys
import os
import json
import logging
from dotenv import load_dotenv

sys.path.append('/root/.openclaw/workspace/zenryoku-telegram-bot')
load_dotenv('/root/.openclaw/workspace/zenryoku-telegram-bot/.env')

from zerotwo_browser import ZeroTwoBrowser
import requests

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

PENDING_POSTS_DIR = "/root/.openclaw/workspace/zenryoku-telegram-bot/pending_posts"

async def execute_post(post_id):
    file_path = os.path.join(PENDING_POSTS_DIR, f"{post_id}.json")
    if not os.path.exists(file_path):
        logger.error(f"Post data not found: {post_id}")
        return False
        
    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)
        
    title = data.get("title", "")
    body = data.get("body", "")
    image_path = data.get("image_path", "")
    
    # 画像の読み込み
    image_bytes = None
    if image_path and os.path.exists(image_path):
        with open(image_path, "rb") as f:
            image_bytes = f.read()
            
    # ゼロツーに投稿
    logger.info(f"ゼロツーに投稿を開始します: {title}")
    browser = ZeroTwoBrowser()
    try:
        # ゼロツーはタイトル欄がなく、本文のみの仕様
        full_content = f"【{title}】\n\n{body}"
        
        
    # HP(キャスカン)に投稿
    logger.info(f"キャスカン(HP)にお知らせを投稿します: {title}")
    from caskan_browser import CaskanBrowser
    caskan = CaskanBrowser()
    try:
        await caskan.post_news(title=title, body=body)
    except Exception as e:
        logger.error(f"キャスカン(HP)投稿エラー: {e}")
    finally:
        await caskan.close()

        result = await browser.post_news(
            content=full_content,
            image_path=image_path if image_bytes else None
        )
        logger.info(f"投稿結果: {result}")
        
        # 投稿完了したらファイルを削除
        if result.get("success", False):
            os.remove(file_path)
            
        return result
    except Exception as e:
        logger.error(f"Post execution error: {e}")
        return {"success": False, "message": str(e)}
    finally:
        await browser.close()

if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(1)
    post_id = sys.argv[1]
    asyncio.run(execute_post(post_id))

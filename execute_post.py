import asyncio
import sys
import os
import json
import logging
from dotenv import load_dotenv

sys.path.append('/root/.openclaw/workspace/zenryoku-telegram-bot')
load_dotenv('/root/.openclaw/workspace/zenryoku-telegram-bot/.env')

from zerotwo_browser import ZeroTwoBrowser
from caskan_browser import CaskanBrowser

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

    image_bytes = None
    if image_path and os.path.exists(image_path):
        with open(image_path, "rb") as f:
            image_bytes = f.read()

    # ゼロツーに投稿
    logger.info(f"ゼロツーに投稿: {title}")
    browser = ZeroTwoBrowser()
    try:
        full_content = f"【{title}】\n\n{body}"
        result = await browser.post_news(
            content=full_content,
            image_path=image_path if image_bytes else None
        )
        logger.info(f"ゼロツー投稿結果: {result}")
    except Exception as e:
        logger.error(f"ゼロツー投稿エラー: {e}")
        result = {"success": False, "message": str(e)}
    finally:
        await browser.close()

    # キャスカン(HP)に投稿（キャスカンは画像なし）
    logger.info(f"キャスカン(HP)にお知らせを投稿: {title}")
    caskan = CaskanBrowser()
    try:
        await caskan.post_news(title=title, body=body)
    except Exception as e:
        logger.error(f"キャスカン投稿エラー: {e}")
    finally:
        await caskan.close()

    # 一時画像ファイルを削除
    if image_path and os.path.exists(image_path):
        try:
            os.remove(image_path)
        except Exception:
            pass

    # 投稿完了後にJSONファイルを削除
    try:
        os.remove(file_path)
    except Exception:
        pass

    return result

if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(1)
    post_id = sys.argv[1]
    asyncio.run(execute_post(post_id))

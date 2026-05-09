import os
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

LOCAL_IMAGES_DIR = "/root/.openclaw/workspace/zenryoku-telegram-bot/local_images"

async def save_photo_locally(bot, file_id: str, therapist_name: str) -> str | None:
    try:
        # ディレクトリを作成
        target_dir = os.path.join(LOCAL_IMAGES_DIR, therapist_name)
        os.makedirs(target_dir, exist_ok=True)

        # Telegramサーバーからファイルをダウンロード
        file = await bot.get_file(file_id)
        
        # タイムスタンプでファイル名を生成
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{therapist_name}_{timestamp}.jpg"
        filepath = os.path.join(target_dir, filename)

        await file.download_to_drive(filepath)
        logger.info(f"Local Image Saved: {filepath}")
        return filepath
    except Exception as e:
        logger.error(f"Local Image Save Error: {e}")
        return None

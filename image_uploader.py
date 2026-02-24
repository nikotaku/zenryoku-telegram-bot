"""
画像アップロードユーティリティ
テレグラムから受け取った画像を外部ストレージにアップロードし、
公開URLを返す。Notionに画像を埋め込むために使用。
"""

import os
import logging
import requests
import tempfile
import hashlib
from datetime import datetime

logger = logging.getLogger(__name__)

# Imgur API (無料、匿名アップロード可能)
IMGUR_CLIENT_ID = os.environ.get("IMGUR_CLIENT_ID", "")

# 代替: 自前のS3互換ストレージ
S3_ENDPOINT = os.environ.get("S3_ENDPOINT", "")
S3_BUCKET = os.environ.get("S3_BUCKET", "")
S3_ACCESS_KEY = os.environ.get("S3_ACCESS_KEY", "")
S3_SECRET_KEY = os.environ.get("S3_SECRET_KEY", "")


async def upload_telegram_photo(bot, file_id: str) -> str | None:
    """
    テレグラムのfile_idから画像をダウンロードし、
    外部ストレージにアップロードして公開URLを返す。

    優先順位:
    1. Imgur (IMGUR_CLIENT_ID が設定されている場合)
    2. テレグラムのファイルURLをそのまま返す（一時的、有効期限あり）
    """
    try:
        # テレグラムから画像ファイルを取得
        file = await bot.get_file(file_id)
        file_url = file.file_path

        if not file_url.startswith("http"):
            file_url = f"https://api.telegram.org/file/bot{bot.token}/{file_url}"

        # 画像をダウンロード
        resp = requests.get(file_url, timeout=30)
        if resp.status_code != 200:
            logger.error(f"画像ダウンロード失敗: {resp.status_code}")
            return None

        image_data = resp.content

        # Imgur にアップロード
        if IMGUR_CLIENT_ID:
            imgur_url = _upload_to_imgur(image_data)
            if imgur_url:
                return imgur_url

        # フォールバック: テレグラムのURLをそのまま返す
        # 注意: このURLは一時的で、約1時間後に無効になる
        logger.warning("外部ストレージ未設定のため、テレグラムの一時URLを使用します")
        return file_url

    except Exception as e:
        logger.error(f"画像アップロードエラー: {e}")
        return None


def _upload_to_imgur(image_data: bytes) -> str | None:
    """Imgurに画像をアップロード"""
    try:
        import base64
        b64_image = base64.b64encode(image_data).decode("utf-8")

        resp = requests.post(
            "https://api.imgur.com/3/image",
            headers={"Authorization": f"Client-ID {IMGUR_CLIENT_ID}"},
            data={"image": b64_image, "type": "base64"},
            timeout=30,
        )

        if resp.status_code == 200:
            data = resp.json()
            url = data.get("data", {}).get("link")
            if url:
                logger.info(f"Imgur アップロード成功: {url}")
                return url

        logger.error(f"Imgur アップロード失敗: {resp.status_code}")
        return None

    except Exception as e:
        logger.error(f"Imgur アップロードエラー: {e}")
        return None


async def download_telegram_photo(bot, file_id: str) -> tuple[bytes | None, str]:
    """
    テレグラムのfile_idから画像をダウンロードしてバイトデータとURLを返す
    """
    try:
        file = await bot.get_file(file_id)
        file_url = file.file_path

        if not file_url.startswith("http"):
            file_url = f"https://api.telegram.org/file/bot{bot.token}/{file_url}"

        resp = requests.get(file_url, timeout=30)
        if resp.status_code == 200:
            return resp.content, file_url
        return None, ""

    except Exception as e:
        logger.error(f"画像ダウンロードエラー: {e}")
        return None, ""

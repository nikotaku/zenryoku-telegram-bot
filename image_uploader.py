import os
import logging
import requests
import tempfile
import json
from datetime import datetime
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

logger = logging.getLogger(__name__)

# フォルダIDのマッピング
FOLDER_MAP = {
    "なお": "1YIrFwPFRuUVtvie4W_bQ8pTVMJy5X01x",
    "みなみ": "1sUEBan-XIOYs74cL1iURW9DPa5aQInAx",
    "みおり": "1Jx1MFmE86Hya-LXGMvfO_XcffVimpZwO",
    "れい": "1xzPyLqLC0b-3gE2olcqa75IGgYh0yC1f",
    "さくら": "14t1b9OmbRQql2ZEHyNrKQUSIM6oSIExr",
    "かすみ": "1Y2-NHir0nJ4ugxoGbnPb5T3ajY9-0vAc",
    "しおり": "1L-dV5GOOj4syGilJosln8fWegP5ozrgC",
    "にいな": "19OgWbYmThXdBkAKx4izw40DE5DrtBRNs",
    "かえで": "1fgYBNRrKAic32pDaN_fMljVX94DJA4GS",
    "ゆか": "1_mHubNVbSydP6SCkOYWh8ukNICIl_qJ_",
    "りさ": "1LK_N8jmOudocnJ60TIMJ9kloSnpmfjIr"
}
ROOT_FOLDER_ID = "12WeDasWkpUYeBa9uv6Kq-9CTVXPJmlAz"

def _get_drive_service():
    sa_json_str = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "")
    if not sa_json_str:
        logger.error("GOOGLE_SERVICE_ACCOUNT_JSON が設定されていません")
        return None
    try:
        sa_info = json.loads(sa_json_str)
        creds = service_account.Credentials.from_service_account_info(
            sa_info, scopes=["https://www.googleapis.com/auth/drive"]
        )
        return build("drive", "v3", credentials=creds, cache_discovery=False)
    except Exception as e:
        logger.error(f"Google Drive API 初期化エラー: {e}")
        return None

async def upload_telegram_photo(bot, file_id: str, therapist_name: str = "") -> str | None:
    try:
        file = await bot.get_file(file_id)
        file_url = file.file_path
        if not file_url.startswith("http"):
            file_url = f"https://api.telegram.org/file/bot{bot.token}/{file_url}"

        resp = requests.get(file_url, timeout=30)
        if resp.status_code != 200:
            logger.error(f"画像ダウンロード失敗: {resp.status_code}")
            return None

        # 一時ファイルに保存
        with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
            tmp.write(resp.content)
            tmp_path = tmp.name

        service = _get_drive_service()
        if not service:
            return file_url  # フォールバック

        folder_id = FOLDER_MAP.get(therapist_name, ROOT_FOLDER_ID)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{therapist_name}_{timestamp}.jpg"

        file_metadata = {
            'name': filename,
            'parents': [folder_id]
        }
        media = MediaFileUpload(tmp_path, mimetype='image/jpeg')
        
        uploaded_file = service.files().create(
            body=file_metadata,
            media_body=media,
            fields='id, webViewLink, webContentLink'
        ).execute()

        os.unlink(tmp_path)
        
        # Google Drive上の画像IDから直接表示可能なURLを生成する
        file_id = uploaded_file.get('id')
        direct_link = f"https://drive.google.com/uc?export=view&id={file_id}"
        
        logger.info(f"Google Driveに画像をアップロードしました: {direct_link}")
        return direct_link

    except Exception as e:
        logger.error(f"画像アップロードエラー: {e}")
        return None

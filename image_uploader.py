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
    "りな": "15aEXgHnY89Kkb7mPI3IoqnP4vBtILXwL",
    "セラピスト": "1MEKmvSrfJR4cKZmNvLMMgJFaQKEdcepo",
    "ダミー用画像": "1uM2E3Pgtl-NAG6Ef161GVnKoqw-dzDYG",
    "店舗別バナー、ロゴ": "13HlmgCHcpmS1ePOBauBydGYz04dnM5LH",
    "共通バナー": "1-dCih4oAghloGZn4gRmEuPdETeVArkyE",
    "えな": "1Q3uDihUTZ2VUI6cGcXXYv_wnjteUDRLx",
    "おとは": "1IHAdBWfWbPTBx2ObEUPz3VooVhJytt9F",
    "かえで": "1VuLK7v7CP1dhj_Kqo6KnG9kmKbajleKO",
    "かりな": "1q48j-2iLpDsKpJbVcKovwIL2_sQHcymW",
    "かりん": "1y7FAhdTNzoNDn7_--vI4aM2AV7ZZw7lJ",
    "きらら": "1thUlVA40EWAoq9fDJHMPzHeJNABnYSaV",
    "さな": "1xTxmspFJWPltF-L1QM4ln-eLo7qxwjRG",
    "しおり": "1QuD0Xoc0bisJvNNqfGjVQBlmzk2Fy_WC",
    "なの": "1_wgDKgG5c3Vmp2GzFNs3MNHe4-aWKKEV",
    "のぞみ": "1k0JI_SxG920NmlFrC6qjMgb43H60QFSJ",
    "はる": "1TLKtMueUKs_N9LNhTeJ3q6ZxQQEXWTUz",
    "ばんび": "1ULzrX_qK6AylUp-gV0c-CakATFT9XPE9",
    "ひより": "1opbT-fLw64ZUUp0i-lo4XbZCHa3kpJ0h",
    "まりの": "1mr_paDKLh9OkUS8DWlLWr6IGn47eVEEd",
    "まりん": "1It0KE-xzSEpJdE2olNTW145NWYcgZHmV",
    "みおり": "1OwJ6F29aBMbTuMAHOjJjXiys9QyLD3GJ",
    "みおん": "1lORJUMysbt31p0OHAbDhdJ-VyM7qG_mc",
    "みさき": "1dsT1m9Br-VFRU3vSEl_CXo_z4LOBkeIf",
    "みなみ": "1uU0d0_Uul0Vh2UWhLgmJoOKe9j-cqSo7",
    "らむ": "1iKoEl3kWiuV41OPCu5yy7V_uitzGU6B0",
    "りおん": "1kArDg5wLaKOQHZoQ5v36mOYnbK0Ut3Cj",
    "りさ": "1ui30Eas5pqPDJHFCXBC5Z7caD5Uqo6cr",
    "りの": "1LPYrqKEpbwqSMGIgbZCjpL_8Sh2em8wl",
    "りん": "1kVBCcZYaVZ3rLXoLJWk1eoCY6OG8DUx1",
    "るい": "1W7R6RqPzdK2bM9apk2O0RHW9qrKU4CiH",
    "れい": "1DSVrwHvahkgIG2R5XMkiUW9HNKxzMmgL",
    "わかな": "1FlwY5Cz_THyY0yiM5GdR3cErNa--_7R3",
    "佐倉はな": "1gMCWSJ5G7JfXZ5Qh5RrL2-JLS8St3eAY",
    "店舗用❶": "1K5A3XUXMMJm7MhGxS3ZtU6vCRWCq6Od1",
    "聡電舎❷": "1rn2drVOOyWZLiQf1O8Iv9m6gtHk685PI",
}
ROOT_FOLDER_ID = "1pyZk9RftuX41MwV77jxhXS8Q0Aw-n9YM"


from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request

def _get_drive_service():
    creds = None
    token_path = "/root/.openclaw/workspace/zenryoku-telegram-bot/token.json"
    
    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, ["https://www.googleapis.com/auth/drive"])
        
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            # Save the refreshed credentials
            with open(token_path, "w") as token:
                token.write(creds.to_json())
        else:
            logger.error("No valid credentials found in token.json. OAuth required.")
            return None
            
    try:
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

        file_id = uploaded_file.get('id')

        # ファイルを「リンクを知っている全員が閲覧可能」に設定
        service.permissions().create(
            fileId=file_id,
            body={'type': 'anyone', 'role': 'reader'},
        ).execute()

        # Google Drive直接表示URL
        direct_link = f"https://drive.google.com/uc?export=view&id={file_id}"
        
        logger.info(f"Google Driveに画像をアップロードしました: {direct_link}")
        return direct_link

    except Exception as e:
        logger.error(f"画像アップロードエラー: {e}")
        return None


def _get_all_subfolders(service, folder_id):
    subfolders = [folder_id]
    query = f"'{folder_id}' in parents and mimeType = 'application/vnd.google-apps.folder' and trashed=false"
    try:
        results = service.files().list(q=query, fields="files(id)").execute()
        for f in results.get('files', []):
            subfolders.extend(_get_all_subfolders(service, f['id']))
    except Exception as e:
        logger.error(f"Error fetching subfolders for {folder_id}: {e}")
    return subfolders

def get_latest_images_from_drive(therapist_name: str, limit: int = 5):
    service = _get_drive_service()
    if not service:
        logger.error("Drive service failed to init")
        return []
    
    root_folder_id = FOLDER_MAP.get(therapist_name)
    if not root_folder_id:
        logger.error(f"No folder ID for {therapist_name}")
        return []

    try:
        folder_ids = _get_all_subfolders(service, root_folder_id)
        parent_queries = [f"'{fid}' in parents" for fid in folder_ids]
        parent_query_str = "(" + " or ".join(parent_queries) + ")"
        
        query = f"{parent_query_str} and mimeType contains 'image/' and trashed=false"
        results = service.files().list(q=query, orderBy="createdTime desc", pageSize=limit, fields="files(id, name)").execute()
        files = results.get('files', [])
        
        downloaded = []
        import io
        from googleapiclient.http import MediaIoBaseDownload
        
        for f in files:
            file_id = f['id']
            request = service.files().get_media(fileId=file_id)
            fh = io.BytesIO()
            downloader = MediaIoBaseDownload(fh, request)
            done = False
            while done is False:
                status, done = downloader.next_chunk()
            fh.seek(0)
            downloaded.append({
                "name": f['name'],
                "bytes": fh.read()
            })
            
        return downloaded
    except Exception as e:
        logger.error(f"Error fetching images from drive: {e}")
        return []

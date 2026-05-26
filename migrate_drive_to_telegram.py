"""
Google DriveのセラピストフォルダからTelegramチャンネルに画像を一括アップ
VPS上で実行: venv/bin/python migrate_drive_to_telegram.py
"""
import os
import sys
import time
import io
import json
import requests
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHANNEL_ID = os.environ.get("PHOTO_CHANNEL_ID", "-5269472642")

# セラピストフォルダのみ（バナー等は除外）
THERAPIST_FOLDERS = {
    "りな": "15aEXgHnY89Kkb7mPI3IoqnP4vBtILXwL",
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
}


def get_drive_service():
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    import httplib2

    sa_json_str = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "")
    if not sa_json_str:
        print("ERROR: GOOGLE_SERVICE_ACCOUNT_JSON が設定されていません")
        sys.exit(1)

    sa_info = json.loads(sa_json_str)
    if isinstance(sa_info, str):
        sa_info = json.loads(sa_info)

    creds = service_account.Credentials.from_service_account_info(
        sa_info, scopes=["https://www.googleapis.com/auth/drive"]
    )
    http = httplib2.Http(timeout=30)
    authed_http = creds.authorize(http)
    return build("drive", "v3", http=authed_http, cache_discovery=False)


def list_images(service, folder_id, limit=10):
    """フォルダ内の画像を最大limit件取得（サブフォルダも含む）"""
    # まずサブフォルダを取得
    all_folder_ids = [folder_id]
    try:
        sub = service.files().list(
            q=f"'{folder_id}' in parents and mimeType='application/vnd.google-apps.folder' and trashed=false",
            fields="files(id)",
            pageSize=20
        ).execute()
        for f in sub.get("files", []):
            all_folder_ids.append(f["id"])
    except Exception:
        pass

    parent_query = " or ".join(f"'{fid}' in parents" for fid in all_folder_ids)
    query = f"({parent_query}) and mimeType contains 'image/' and trashed=false"
    try:
        result = service.files().list(
            q=query,
            fields="files(id, name)",
            orderBy="createdTime desc",
            pageSize=limit
        ).execute()
        return result.get("files", [])
    except Exception as e:
        print(f"  リスト取得失敗: {e}")
        return []


def download_image(service, file_id):
    """Drive画像をbytesでダウンロード"""
    from googleapiclient.http import MediaIoBaseDownload
    try:
        request = service.files().get_media(fileId=file_id)
        fh = io.BytesIO()
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
        fh.seek(0)
        return fh.read()
    except Exception as e:
        print(f"  ダウンロード失敗: {e}")
        return None


def send_to_channel(image_bytes, caption):
    """Telegramチャンネルに送信"""
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"
    resp = requests.post(url, data={"chat_id": CHANNEL_ID, "caption": caption},
                         files={"photo": ("photo.jpg", image_bytes, "image/jpeg")},
                         timeout=30)
    if resp.status_code == 200:
        return resp.json().get("result", {}).get("photo", [{}])[-1].get("file_id")
    else:
        print(f"  Telegram送信失敗: {resp.text[:200]}")
        return None


def main():
    print(f"Google Drive → Telegramチャンネル ({CHANNEL_ID}) 移行開始\n")
    service = get_drive_service()

    from photo_storage import add_photo

    total_ok = 0
    total_fail = 0

    for name, folder_id in THERAPIST_FOLDERS.items():
        print(f"\n📁 {name} ...")
        images = list_images(service, folder_id, limit=10)
        if not images:
            print(f"  画像なし（スキップ）")
            continue

        ok = 0
        for img in images:
            img_bytes = download_image(service, img["id"])
            if not img_bytes:
                total_fail += 1
                continue

            file_id = send_to_channel(img_bytes, name)
            if file_id:
                add_photo(name, file_id)
                ok += 1
                total_ok += 1
                print(f"  ✅ {img['name'][:40]}")
            else:
                total_fail += 1
                print(f"  ❌ {img['name'][:40]}")

            time.sleep(0.5)  # Telegram rate limit対策

        print(f"  → {ok}/{len(images)}枚完了")

    print(f"\n=== 完了: 成功{total_ok}枚 / 失敗{total_fail}枚 ===")


if __name__ == "__main__":
    main()

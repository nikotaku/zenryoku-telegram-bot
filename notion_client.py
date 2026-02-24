"""
Notion API クライアント — セラピスト情報の取得・写真アップロード
"""

import os
import logging
import requests

logger = logging.getLogger(__name__)

NOTION_API_KEY = os.environ.get("NOTION_API_KEY", "")
NOTION_VERSION = "2022-06-28"

# マスタDB data_source_id
MASTER_DB_ID = os.environ.get("NOTION_MASTER_DB_ID", "20af9507-f0cf-811a-9397-000b1fd6918d")

# セラピスト一覧（源氏名 → Notion ページID）
# 環境変数 THERAPIST_MAP で上書き可能（JSON形式）
DEFAULT_THERAPIST_MAP = {
    "なお": "23ff9507-f0cf-80dd-bb02-db4fe5e8cc6d",
    "みなみ": "23cf9507-f0cf-8087-acf6-e3ce3dd08a16",
    "みおり": "c88837ff-d602-4b66-aff5-dd7442839a8e",
    "れい": "307f9507-f0cf-802c-a18f-db76c859c514",
    "さくら": "30cf9507-f0cf-80e7-94b7-e753cc620bc7",
    "かすみ": "2fbf9507-f0cf-80e5-9d5e-fdf9e2c0452d",
    "しおり": "c54a96ce-5508-45b4-9512-49d6ef433965",
    "にいな": "240861f7-28c2-47b7-8020-3a3ba8cc36de",
    "かえで": "2cff9507-f0cf-80f4-8fcf-dec2b1a28964",
    "ゆか": "305f9507-f0cf-8093-b883-ec4180791443",
    "りさ": "2e6f9507-f0cf-8058-9b3c-db36c74be6f0",
}


def _get_therapist_map():
    """セラピストマップを取得（環境変数で上書き可能）"""
    import json
    custom = os.environ.get("THERAPIST_MAP")
    if custom:
        try:
            return json.loads(custom)
        except Exception:
            pass
    return DEFAULT_THERAPIST_MAP


def get_therapist_list():
    """セラピスト名のリストを返す"""
    return list(_get_therapist_map().keys())


def get_therapist_page_id(name: str) -> str | None:
    """セラピスト名からNotionページIDを返す"""
    return _get_therapist_map().get(name)


def _headers():
    return {
        "Authorization": f"Bearer {NOTION_API_KEY}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }


def append_image_to_page(page_id: str, image_url: str, caption: str = "") -> bool:
    """
    Notionページに画像ブロックを追加する
    """
    if not NOTION_API_KEY:
        logger.error("NOTION_API_KEY が設定されていません")
        return False

    url = f"https://api.notion.com/v1/blocks/{page_id}/children"

    image_block = {
        "object": "block",
        "type": "image",
        "image": {
            "type": "external",
            "external": {
                "url": image_url
            },
        }
    }

    if caption:
        image_block["image"]["caption"] = [
            {
                "type": "text",
                "text": {"content": caption}
            }
        ]

    payload = {"children": [image_block]}

    try:
        resp = requests.patch(url, json=payload, headers=_headers(), timeout=30)
        if resp.status_code == 200:
            logger.info(f"画像をNotionページ {page_id} に追加しました")
            return True
        else:
            logger.error(f"Notion API エラー: {resp.status_code} - {resp.text}")
            return False
    except Exception as e:
        logger.error(f"Notion API 接続エラー: {e}")
        return False


def get_page_title(page_id: str) -> str:
    """Notionページのタイトルを取得"""
    if not NOTION_API_KEY:
        return "不明"

    url = f"https://api.notion.com/v1/pages/{page_id}"
    try:
        resp = requests.get(url, headers=_headers(), timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            props = data.get("properties", {})
            for prop in props.values():
                if prop.get("type") == "title":
                    titles = prop.get("title", [])
                    if titles:
                        return titles[0].get("plain_text", "不明")
        return "不明"
    except Exception:
        return "不明"

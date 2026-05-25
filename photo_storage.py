"""
Telegramチャンネル経由で管理する写真インデックス（JSON保存）
チャンネルに「キャプション=名前」で写真を投稿するとBotが自動登録する
"""
import json
import os
import logging

logger = logging.getLogger(__name__)
STORAGE_FILE = os.path.join(os.path.dirname(__file__), "photo_index.json")


def load_index() -> dict:
    if os.path.exists(STORAGE_FILE):
        try:
            with open(STORAGE_FILE, encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"photo_index読み込みエラー: {e}")
    return {}


def save_index(index: dict):
    try:
        with open(STORAGE_FILE, "w", encoding="utf-8") as f:
            json.dump(index, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"photo_index保存エラー: {e}")


def add_photo(name: str, file_id: str):
    index = load_index()
    if name not in index:
        index[name] = []
    if file_id not in index[name]:
        index[name].append(file_id)
        save_index(index)
        logger.info(f"写真登録: {name} ({len(index[name])}枚目)")


def get_photos(name: str) -> list:
    return load_index().get(name, [])


def get_all_names() -> list:
    return sorted(load_index().keys())


def remove_photo(name: str, file_id: str):
    index = load_index()
    if name in index and file_id in index[name]:
        index[name].remove(file_id)
        if not index[name]:
            del index[name]
        save_index(index)

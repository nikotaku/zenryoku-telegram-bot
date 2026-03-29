"""
Notion シフトDB クライアント — シフトデータの取得・ステータス更新

NotionシフトDBをマスタデータとして、キャスカン・エスたまへの同期を管理する。

シフトDB プロパティ:
  - タイトル (title): セラピスト名
  - 日付 (date): シフト日
  - ルーム (select): インルーム / ラズルーム / サンルーム / インルーム/ラズルーム
  - 開始時間 (select): 11:00〜21:00
  - 終了時間 (select): 14:00〜26:00
  - 条件 (text): 条件テキスト
  - ｼﾌﾄﾁｪｯｸ (status): 未着手 / ｷｬｽｶﾝ完了/エスたま未登録 / 完了
  - 実働日数 (formula): 自動計算
"""

import os
import logging
import requests
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

NOTION_API_KEY = os.environ.get("NOTION_API_KEY", "")
NOTION_VERSION = "2022-06-28"

# シフトDB のデータベースID
SHIFT_DB_ID = os.environ.get(
    "NOTION_SHIFT_DB_ID",
    "256f9507-f0cf-8076-931f-ed70fc040520",
)

# シフトチェック ステータス値
STATUS_NOT_STARTED = "未着手"
STATUS_CASKAN_DONE = "ｷｬｽｶﾝ完了/エスたま未登録"
STATUS_COMPLETED = "完了"


def _headers():
    return {
        "Authorization": f"Bearer {NOTION_API_KEY}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }


def query_shifts(
    date_str: Optional[str] = None,
    status_filter: Optional[str] = None,
    days_range: int = 0,
) -> list[dict]:
    """
    NotionシフトDBからシフトデータを取得する。

    Args:
        date_str: 対象日付 "YYYY-MM-DD"（Noneなら今日）
        status_filter: ステータスでフィルタ（例: "未着手"）
        days_range: date_str から何日分取得するか（0=当日のみ）

    Returns:
        [
            {
                "page_id": str,
                "name": str,       # セラピスト名（タイトル）
                "date": str,       # "YYYY-MM-DD"
                "room": str,       # ルーム名
                "start": str,      # "HH:MM"
                "end": str,        # "HH:MM"
                "condition": str,  # 条件
                "status": str,     # ｼﾌﾄﾁｪｯｸ
            },
            ...
        ]
    """
    if not NOTION_API_KEY:
        logger.error("NOTION_API_KEY が設定されていません")
        return []

    if date_str is None:
        date_str = datetime.now().strftime("%Y-%m-%d")

    url = f"https://api.notion.com/v1/databases/{SHIFT_DB_ID}/query"

    # フィルター構築
    filters = []

    # 日付フィルター
    if days_range > 0:
        end_date = (
            datetime.strptime(date_str, "%Y-%m-%d") + timedelta(days=days_range)
        ).strftime("%Y-%m-%d")
        filters.append({
            "property": "日付",
            "date": {"on_or_after": date_str},
        })
        filters.append({
            "property": "日付",
            "date": {"on_or_before": end_date},
        })
    else:
        filters.append({
            "property": "日付",
            "date": {"equals": date_str},
        })

    # ステータスフィルター
    if status_filter:
        filters.append({
            "property": "ｼﾌﾄﾁｪｯｸ",
            "status": {"equals": status_filter},
        })

    # リクエストボディ
    body = {
        "sorts": [
            {"property": "日付", "direction": "ascending"},
            {"property": "IN", "direction": "ascending"},
        ],
    }

    if len(filters) == 1:
        body["filter"] = filters[0]
    elif len(filters) > 1:
        body["filter"] = {"and": filters}

    try:
        all_results = []
        has_more = True
        start_cursor = None

        while has_more:
            if start_cursor:
                body["start_cursor"] = start_cursor

            resp = requests.post(url, json=body, headers=_headers(), timeout=30)

            if resp.status_code != 200:
                logger.error(f"Notion API エラー: {resp.status_code} - {resp.text}")
                return []

            data = resp.json()
            results = data.get("results", [])
            all_results.extend(results)

            has_more = data.get("has_more", False)
            start_cursor = data.get("next_cursor")

        return [_parse_shift_page(page) for page in all_results]

    except Exception as e:
        logger.error(f"Notion API 接続エラー: {e}")
        return []


def query_shifts_week(start_date: Optional[str] = None) -> list[dict]:
    """今日から7日間のシフトを取得する"""
    if start_date is None:
        start_date = datetime.now().strftime("%Y-%m-%d")
    return query_shifts(date_str=start_date, days_range=6)


def query_pending_shifts(target: str = "caskan") -> list[dict]:
    """
    同期が必要なシフトを取得する。

    Args:
        target: "caskan" → 未着手のシフト, "estama" → 未着手 or ｷｬｽｶﾝ完了/エスたま未登録

    Returns:
        同期が必要なシフトのリスト
    """
    if target == "caskan":
        return query_shifts(
            date_str=datetime.now().strftime("%Y-%m-%d"),
            status_filter=STATUS_NOT_STARTED,
            days_range=30,
        )
    elif target == "estama":
        # エスたま未登録のもの（未着手 + ｷｬｽｶﾝ完了/エスたま未登録）
        not_started = query_shifts(
            date_str=datetime.now().strftime("%Y-%m-%d"),
            status_filter=STATUS_NOT_STARTED,
            days_range=30,
        )
        caskan_done = query_shifts(
            date_str=datetime.now().strftime("%Y-%m-%d"),
            status_filter=STATUS_CASKAN_DONE,
            days_range=30,
        )
        return not_started + caskan_done
    return []


def update_shift_status(page_id: str, new_status: str) -> bool:
    """
    シフトレコードのｼﾌﾄﾁｪｯｸステータスを更新する。

    Args:
        page_id: NotionページID
        new_status: 新しいステータス値

    Returns:
        成功したら True
    """
    if not NOTION_API_KEY:
        logger.error("NOTION_API_KEY が設定されていません")
        return False

    url = f"https://api.notion.com/v1/pages/{page_id}"
    payload = {
        "properties": {
            "ｼﾌﾄﾁｪｯｸ": {
                "status": {
                    "name": new_status,
                }
            }
        }
    }

    try:
        resp = requests.patch(url, json=payload, headers=_headers(), timeout=30)
        if resp.status_code == 200:
            logger.info(f"シフトステータス更新: {page_id} → {new_status}")
            return True
        else:
            logger.error(f"Notion API エラー: {resp.status_code} - {resp.text}")
            return False
    except Exception as e:
        logger.error(f"Notion API 接続エラー: {e}")
        return False


def _parse_shift_page(page: dict) -> dict:
    """Notion APIのページオブジェクトからシフト情報を抽出する"""
    props = page.get("properties", {})
    page_id = page.get("id", "")

    # タイトル（セラピスト名）
    title_prop = props.get("タイトル", {})
    name = ""
    if title_prop.get("type") == "title":
        titles = title_prop.get("title", [])
        if titles:
            name = titles[0].get("plain_text", "")

    # 日付
    date_prop = props.get("日付", {})
    date_str = ""
    if date_prop.get("type") == "date" and date_prop.get("date"):
        raw_date = date_prop["date"].get("start", "")
        # "2026-03-30T05:00:00.000+00:00" のような形式から日付部分(先頭10文字)だけを抽出
        if raw_date:
            date_str = raw_date[:10]

    # ルーム
    room_prop = props.get("ルーム", {})
    room = ""
    if room_prop.get("type") == "select" and room_prop.get("select"):
        room = room_prop["select"].get("name", "")

    # 開始時間
    start_prop = props.get("IN", {})
    start = ""
    if start_prop.get("type") == "select" and start_prop.get("select"):
        start = start_prop["select"].get("name", "")

    # 終了時間
    end_prop = props.get("OUT", {})
    end = ""
    if end_prop.get("type") == "select" and end_prop.get("select"):
        end = end_prop["select"].get("name", "")

    # 条件
    condition_prop = props.get("条件", {}) # Missing in new DB
    condition = ""
    if condition_prop.get("type") == "rich_text":
        texts = condition_prop.get("rich_text", [])
        if texts:
            condition = texts[0].get("plain_text", "")

    # ｼﾌﾄﾁｪｯｸ
    status_prop = props.get("ｼﾌﾄﾁｪｯｸ", {})
    status = ""
    if status_prop.get("type") == "status" and status_prop.get("status"):
        status = status_prop["status"].get("name", "")

    return {
        "page_id": page_id,
        "name": name,
        "date": date_str,
        "room": room,
        "start": start,
        "end": end,
        "condition": condition,
        "status": status,
    }


def format_shifts_message(shifts: list[dict], title: str = "シフト一覧") -> str:
    """シフトリストを表示用テキストに整形する"""
    if not shifts:
        return f"📅 【{title}】\nシフトデータがありません。"

    text = f"📅 【{title}】\n\n"
    current_date = ""

    for s in shifts:
        if s["date"] != current_date:
            current_date = s["date"]
            text += f"\n📆 {current_date}\n"

        status_icon = {
            STATUS_NOT_STARTED: "⬜",
            STATUS_CASKAN_DONE: "🟡",
            STATUS_COMPLETED: "✅",
        }.get(s["status"], "❓")

        room_str = f" 🏠{s['room']}" if s["room"] else ""
        condition_str = f" 📝{s['condition']}" if s["condition"] else ""

        text += (
            f"  {status_icon} {s['name']}  "
            f"⏰ {s['start']}〜{s['end']}"
            f"{room_str}{condition_str}\n"
        )

    # 凡例
    text += (
        f"\n{'─' * 25}\n"
        f"⬜ 未着手  🟡 ｷｬｽｶﾝ完了  ✅ 完了"
    )

    return text

def create_shift(name: str, date_str: str, start_time: str, end_time: str, room: str = "") -> str | None:
    """
    NotionのシフトDBに新しいシフトを登録する。
    """
    if not NOTION_API_KEY:
        logger.error("NOTION_API_KEY が設定されていません")
        return None

    url = "https://api.notion.com/v1/pages"

    props = {
        "タイトル": {"title": [{"text": {"content": name}}]},
        "日付": {"date": {"start": date_str}},
    }
    
    if start_time:
        props["IN"] = {"select": {"name": start_time}}
    if end_time:
        props["OUT"] = {"select": {"name": end_time}}
    if room:
        props["ルーム"] = {"select": {"name": room}}
    
    # ｼﾌﾄﾁｪｯｸを未着手に設定
    props["ｼﾌﾄﾁｪｯｸ"] = {"status": {"name": STATUS_NOT_STARTED}}

    payload = {
        "parent": {"database_id": SHIFT_DB_ID},
        "properties": props
    }

    try:
        import requests
        resp = requests.post(url, headers=_headers(), json=payload, timeout=30)
        if resp.status_code == 200:
            data = resp.json()
            logger.info(f"シフト作成成功: {name} {date_str} {start_time}-{end_time}")
            return data.get("id")
        else:
            logger.error(f"シフト作成失敗: {resp.status_code} {resp.text}")
            return None
    except Exception as e:
        logger.error(f"シフト作成エラー: {e}")
        return None

def delete_shift(page_id: str) -> bool:
    """
    Notionのシフトを削除（ゴミ箱へ移動）する。
    """
    if not NOTION_API_KEY:
        return False
    
    url = f"https://api.notion.com/v1/pages/{page_id}"
    payload = {"archived": True}
    
    try:
        import requests
        resp = requests.patch(url, headers=_headers(), json=payload, timeout=30)
        return resp.status_code == 200
    except Exception as e:
        logger.error(f"シフト削除エラー: {e}")
        return False

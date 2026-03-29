"""
Google Sheets API クライアント — 経費明細シートへの書き込み

認証方式（優先順位順）:
  1. GOOGLE_SERVICE_ACCOUNT_JSON 環境変数（サービスアカウントのJSONを文字列で設定）
  2. GOOGLE_APPLICATION_CREDENTIALS 環境変数（サービスアカウントJSONファイルのパス）

スプレッドシートID:
  EXPENSE_SHEET_ID 環境変数で指定する
  （例: 1WpwYKqrameXK3yefsEyNYJUpyB_kkBNec-9MviEmncY）
"""

import os
import json
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

# ─── 設定 ────────────────────────────────────────────────────
EXPENSE_SHEET_ID = os.environ.get(
    "EXPENSE_SHEET_ID", "1WpwYKqrameXK3yefsEyNYJUpyB_kkBNec-9MviEmncY"
)

# 書き込み先シート名
EXPENSE_SHEET_NAME = "経費明細"

# 経費明細シートのヘッダー行（初回作成時に使用）
EXPENSE_SHEET_HEADERS = ["日付", "金額", "カテゴリ", "メモ", "登録日時"]

# Google Sheets API スコープ
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


def _get_credentials():
    """
    Google APIの認証情報を取得する。

    優先順位:
      1. GOOGLE_SERVICE_ACCOUNT_JSON 環境変数（JSON文字列）
      2. GOOGLE_APPLICATION_CREDENTIALS 環境変数（JSONファイルパス）

    Returns:
        google.oauth2.service_account.Credentials または None
    """
    try:
        from google.oauth2 import service_account

        # 方法1: 環境変数にJSON文字列が直接設定されている場合
        sa_json_str = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "")
        if sa_json_str:
            sa_info = json.loads(sa_json_str)
            if isinstance(sa_info, str):
                sa_info = json.loads(sa_info)
            creds = service_account.Credentials.from_service_account_info(
                sa_info, scopes=SCOPES
            )
            logger.info("GOOGLE_SERVICE_ACCOUNT_JSON から認証情報を取得しました")
            return creds

        # 方法2: JSONファイルパスが設定されている場合
        sa_file = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "")
        if sa_file and os.path.exists(sa_file):
            creds = service_account.Credentials.from_service_account_file(
                sa_file, scopes=SCOPES
            )
            logger.info(f"GOOGLE_APPLICATION_CREDENTIALS ({sa_file}) から認証情報を取得しました")
            return creds

        logger.warning(
            "Google認証情報が設定されていません。"
            "GOOGLE_SERVICE_ACCOUNT_JSON または GOOGLE_APPLICATION_CREDENTIALS を設定してください。"
        )
        return None

    except ImportError:
        logger.error(
            "google-auth パッケージがインストールされていません。"
            "pip install google-auth google-api-python-client を実行してください。"
        )
        return None
    except Exception as e:
        logger.error(f"Google認証情報の取得に失敗しました: {e}")
        return None


def _get_sheets_service():
    """
    Google Sheets API サービスオブジェクトを返す。

    Returns:
        googleapiclient.discovery.Resource または None
    """
    try:
        from googleapiclient.discovery import build

        creds = _get_credentials()
        if creds is None:
            return None

        service = build("sheets", "v4", credentials=creds, cache_discovery=False)
        return service

    except ImportError:
        logger.error(
            "google-api-python-client がインストールされていません。"
            "pip install google-api-python-client を実行してください。"
        )
        return None
    except Exception as e:
        logger.error(f"Sheets API サービスの初期化に失敗しました: {e}")
        return None


def _ensure_expense_sheet(service) -> bool:
    """
    「経費明細」シートが存在しない場合は作成し、ヘッダー行を書き込む。

    Args:
        service: Google Sheets API サービスオブジェクト

    Returns:
        成功したら True
    """
    try:
        # スプレッドシートのシート一覧を取得
        spreadsheet = (
            service.spreadsheets()
            .get(spreadsheetId=EXPENSE_SHEET_ID, fields="sheets(properties(title))")
            .execute()
        )
        existing_sheets = [
            s["properties"]["title"] for s in spreadsheet.get("sheets", [])
        ]

        if EXPENSE_SHEET_NAME not in existing_sheets:
            # 「経費明細」シートを新規追加
            body = {
                "requests": [
                    {
                        "addSheet": {
                            "properties": {
                                "title": EXPENSE_SHEET_NAME,
                            }
                        }
                    }
                ]
            }
            service.spreadsheets().batchUpdate(
                spreadsheetId=EXPENSE_SHEET_ID, body=body
            ).execute()
            logger.info(f"「{EXPENSE_SHEET_NAME}」シートを新規作成しました")

            # ヘッダー行を書き込む
            header_body = {
                "values": [EXPENSE_SHEET_HEADERS]
            }
            service.spreadsheets().values().update(
                spreadsheetId=EXPENSE_SHEET_ID,
                range=f"{EXPENSE_SHEET_NAME}!A1",
                valueInputOption="RAW",
                body=header_body,
            ).execute()
            logger.info(f"「{EXPENSE_SHEET_NAME}」シートにヘッダー行を書き込みました")

        return True

    except Exception as e:
        logger.error(f"「{EXPENSE_SHEET_NAME}」シートの確認・作成に失敗しました: {e}")
        return False


def append_expense_to_sheet(
    date: str,
    amount: int,
    content: str,
    memo: str = "",
) -> bool:
    """
    「経費明細」シートに経費データを1行追記する。

    シートが存在しない場合は自動作成し、ヘッダー行を書き込む。
    列構成: 日付 | 金額 | カテゴリ | メモ | 登録日時

    Args:
        date: 日付文字列（例: "2026-03-20"）
        amount: 金額（整数、円）
        content: カテゴリ（例: "地代家賃"）
        memo: メモ（任意）

    Returns:
        成功したら True、失敗したら False
    """
    if not EXPENSE_SHEET_ID:
        logger.error("EXPENSE_SHEET_ID が設定されていません")
        return False

    service = _get_sheets_service()
    if service is None:
        return False

    # シートの存在確認・作成
    if not _ensure_expense_sheet(service):
        return False

    # 登録日時
    recorded_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # 書き込む行データ
    row = [date, amount, content, memo, recorded_at]

    try:
        body = {"values": [row]}
        result = (
            service.spreadsheets()
            .values()
            .append(
                spreadsheetId=EXPENSE_SHEET_ID,
                range=f"{EXPENSE_SHEET_NAME}!A:E",
                valueInputOption="USER_ENTERED",
                insertDataOption="INSERT_ROWS",
                body=body,
            )
            .execute()
        )
        updated_range = result.get("updates", {}).get("updatedRange", "不明")
        logger.info(
            f"経費をスプレッドシートに追記しました: {date} ¥{amount:,} {content} → {updated_range}"
        )
        return True

    except Exception as e:
        logger.error(f"スプレッドシートへの書き込みに失敗しました: {e}")
        return False

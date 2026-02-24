"""
キャスカン (caskan.jp) クライアント — スクレイピングベースの情報取得
"""

import os
import re
import logging
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta, date as date_type
import calendar

logger = logging.getLogger(__name__)

CASKAN_SHOP_ID = os.environ.get("CASKAN_SHOP_ID", "Zenryoku1209")
CASKAN_LOGIN_ID = os.environ.get("CASKAN_LOGIN_ID", "zr.sendai@gmail.com")
CASKAN_PASSWORD = os.environ.get("CASKAN_PASSWORD", "Zenryoku1209")

BASE_URL = "https://my.caskan.jp"


class CaskanClient:
    """キャスカン管理画面のスクレイピングクライアント"""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        })
        self._logged_in = False

    def login(self) -> bool:
        """キャスカンにログイン（2段階フォーム）"""
        try:
            # Step 1: 店舗IDとログインIDを送信
            resp = self.session.post(
                f"{BASE_URL}/login",
                data={
                    "mode": "step1",
                    "shop_code": CASKAN_SHOP_ID,
                    "code": CASKAN_LOGIN_ID,
                },
                timeout=15,
                allow_redirects=True,
            )

            if resp.status_code != 200:
                logger.error(f"Step1失敗: {resp.status_code}")
                return False

            # Step 2: パスワードを送信
            resp2 = self.session.post(
                f"{BASE_URL}/login/password",
                data={
                    "mode": "step2",
                    "login_password": CASKAN_PASSWORD,
                },
                timeout=15,
                allow_redirects=True,
            )

            if "/login" not in resp2.url:
                self._logged_in = True
                logger.info("キャスカンにログイン成功")
                return True
            else:
                logger.error("キャスカンログイン失敗（パスワード不正）")
                return False

        except Exception as e:
            logger.error(f"キャスカンログインエラー: {e}")
            return False

    def _ensure_login(self) -> bool:
        if not self._logged_in:
            return self.login()
        # セッション切れチェック
        try:
            resp = self.session.get(f"{BASE_URL}/", timeout=10, allow_redirects=False)
            if resp.status_code in (301, 302) and "/login" in resp.headers.get("Location", ""):
                self._logged_in = False
                return self.login()
        except Exception:
            pass
        return True

    def get_home_info(self) -> dict:
        """ホーム画面から売上情報と出勤情報を取得"""
        if not self._ensure_login():
            return {"error": "ログインに失敗しました"}

        try:
            resp = self.session.get(f"{BASE_URL}/", timeout=15)
            soup = BeautifulSoup(resp.text, "html.parser")

            result = {
                "sales": {},
                "attendance_text": "",
                "guidance_text": "",
            }

            # テキスト全体を取得
            text = soup.get_text(separator="\n", strip=True)
            lines = text.split("\n")

            # 売上情報を抽出（パターンマッチング）
            for i, line in enumerate(lines):
                line_s = line.strip()
                if line_s == "本日" and i + 1 < len(lines):
                    result["sales"]["today"] = lines[i + 1].strip()
                elif line_s == "昨日" and i + 1 < len(lines):
                    result["sales"]["yesterday"] = lines[i + 1].strip()
                elif line_s == "今月" and i + 1 < len(lines):
                    result["sales"]["this_month"] = lines[i + 1].strip()
                elif line_s == "昨月" and i + 1 < len(lines):
                    result["sales"]["last_month"] = lines[i + 1].strip()

            # textarea から出勤情報を取得
            textareas = soup.find_all("textarea")
            for ta in textareas:
                content = ta.get_text(strip=True)
                if "出勤情報" in content:
                    result["attendance_text"] = content
                elif "案内状況" in content:
                    result["guidance_text"] = content

            return result

        except Exception as e:
            logger.error(f"ホーム情報取得エラー: {e}")
            return {"error": str(e)}

    def get_schedule(self) -> dict:
        """週間スケジュールを取得"""
        if not self._ensure_login():
            return {"error": "ログインに失敗しました"}

        try:
            resp = self.session.get(f"{BASE_URL}/schedule/week", timeout=15)
            soup = BeautifulSoup(resp.text, "html.parser")

            text = soup.get_text(separator="\n", strip=True)

            # スケジュール情報を構造化して抽出
            schedule_lines = []
            lines = text.split("\n")
            current_date = ""

            for line in lines:
                line = line.strip()
                if not line:
                    continue

                # 日付パターン (例: 2/24 (火))
                date_match = re.match(r"(\d+/\d+\s*\([月火水木金土日]\))", line)
                if date_match:
                    current_date = date_match.group(1)
                    schedule_lines.append(f"\n📅 {current_date}")
                    continue

                # ルーム情報
                if "room" in line.lower():
                    schedule_lines.append(f"  🏠 {line}")
                    continue

                # 時間帯パターン (例: 13:00〜25:00)
                time_match = re.search(r"\d{1,2}:\d{2}[〜~-]\d{1,2}:\d{2}", line)
                if time_match and current_date:
                    schedule_lines.append(f"  ⏰ {line}")
                    continue

                # セラピスト名（短い日本語テキスト）
                if current_date and len(line) < 15 and re.match(r"^[\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FFF]+$", line):
                    schedule_lines.append(f"  👤 {line}")

            return {
                "schedule_text": "\n".join(schedule_lines) if schedule_lines else "スケジュール情報が見つかりません",
            }

        except Exception as e:
            logger.error(f"スケジュール取得エラー: {e}")
            return {"error": str(e)}

    def get_reservations(self) -> dict:
        """予約一覧を取得"""
        if not self._ensure_login():
            return {"error": "ログインに失敗しました"}

        try:
            resp = self.session.get(f"{BASE_URL}/reservation", timeout=15)
            soup = BeautifulSoup(resp.text, "html.parser")

            reservations = []
            tables = soup.find_all("table")
            for table in tables:
                rows = table.find_all("tr")
                for row in rows:
                    cells = row.find_all(["td", "th"])
                    if cells:
                        row_text = " | ".join(c.get_text(strip=True) for c in cells)
                        if row_text.strip():
                            reservations.append(row_text)

            return {
                "reservations": reservations[:20],
                "count": len(reservations),
            }

        except Exception as e:
            logger.error(f"予約取得エラー: {e}")
            return {"error": str(e)}

    def get_room_map(self) -> dict:
        """ルームIDとルーム名のマッピングを取得"""
        if not self._ensure_login():
            return {}
        try:
            resp = self.session.get(f"{BASE_URL}/room", timeout=15)
            soup = BeautifulSoup(resp.text, "html.parser")
            room_map = {}
            inputs = soup.find_all("input", {"name": re.compile(r"^sort\[")})
            for inp in inputs:
                room_id = inp.get("value", "")
                tr = inp.find_parent("tr")
                if tr:
                    link = tr.find("a", href=re.compile(r"/room/view"))
                    if link:
                        room_name = link.get_text(separator=" ", strip=True).split()[0]
                        room_map[room_id] = room_name
            return room_map
        except Exception as e:
            logger.error(f"ルームマップ取得エラー: {e}")
            return {}

    def get_monthly_shift(self, year: int, month: int) -> dict:
        """
        指定月のシフト情報とルーム空き状況を取得して月カレンダー形式で返す。

        Returns:
            {
                'year': int,
                'month': int,
                'room_map': {room_id: room_name},
                'days': {
                    'YYYY-MM-DD': {
                        'weekday': '月',
                        'shifts': [
                            {'name': str, 'time': str, 'room_id': str, 'room_name': str}
                        ],
                        'rooms_used': [room_id, ...],
                    }
                }
            }
        """
        if not self._ensure_login():
            return {"error": "ログインに失敗しました"}

        try:
            room_map = self.get_room_map()
            # 月の最初の日と最後の日を計算
            first_day = date_type(year, month, 1)
            last_day = date_type(year, month, calendar.monthrange(year, month)[1])

            # 週ごとにシフト表を取得（7日単位）
            all_shifts: dict = {}  # date_str -> list of shifts
            current = first_day
            fetched_weeks = set()

            while current <= last_day:
                week_key = current.strftime("%Y-%m-%d")
                if week_key not in fetched_weeks:
                    fetched_weeks.add(week_key)
                    resp = self.session.get(
                        f"{BASE_URL}/shift/view?start_day={week_key}",
                        timeout=15,
                    )
                    soup = BeautifulSoup(resp.text, "html.parser")

                    # parts-cast-table からシフト情報を抽出
                    cast_tables = soup.find_all("table", class_="parts-cast-table")
                    for ct in cast_tables:
                        for row in ct.find_all("tr"):
                            td = row.find("td")
                            if not td:
                                continue
                            divs = td.find_all("div")
                            name = divs[0].get_text(strip=True) if divs else ""
                            time_str = divs[1].get_text(strip=True) if len(divs) > 1 else ""
                            edit_span = td.find("span", {"data-room-id": True})
                            if not edit_span:
                                continue
                            room_id = edit_span.get("data-room-id", "")
                            day_str = edit_span.get("data-day", "")
                            if not day_str or not name:
                                continue
                            # 対象月のみ記録
                            try:
                                d = datetime.strptime(day_str, "%Y-%m-%d").date()
                            except ValueError:
                                continue
                            if d.year == year and d.month == month:
                                if day_str not in all_shifts:
                                    all_shifts[day_str] = []
                                all_shifts[day_str].append({
                                    "name": name,
                                    "time": time_str,
                                    "room_id": room_id,
                                    "room_name": room_map.get(room_id, f"Room{room_id}"),
                                })
                current += timedelta(days=7)

            # 月の全日付を埋める
            weekday_names = ["月", "火", "水", "木", "金", "土", "日"]
            days = {}
            d = first_day
            while d <= last_day:
                day_str = d.strftime("%Y-%m-%d")
                shifts = all_shifts.get(day_str, [])
                rooms_used = list({s["room_id"] for s in shifts})
                days[day_str] = {
                    "weekday": weekday_names[d.weekday()],
                    "shifts": shifts,
                    "rooms_used": rooms_used,
                }
                d += timedelta(days=1)

            return {
                "year": year,
                "month": month,
                "room_map": room_map,
                "days": days,
            }

        except Exception as e:
            logger.error(f"月シフト取得エラー: {e}")
            return {"error": str(e)}

    def get_cast_list(self) -> list:
        """キャスト一覧を取得"""
        if not self._ensure_login():
            return []

        try:
            resp = self.session.get(f"{BASE_URL}/cast", timeout=15)
            soup = BeautifulSoup(resp.text, "html.parser")

            casts = []
            seen = set()

            # テーブルの行からキャスト情報を抽出
            rows = soup.find_all("tr")
            for row in rows:
                # 名前リンクを探す
                links = row.find_all("a")
                for link in links:
                    href = link.get("href", "")
                    text = link.get_text(strip=True)
                    if "/cast/" in href and text and "編集" not in text and text not in seen:
                        # 追加情報を行から取得
                        row_text = row.get_text(separator=" ", strip=True)
                        # ステータスを確認
                        status = "掲載中" if "掲載中" in row_text else "未掲載"
                        casts.append(f"{text} [{status}]")
                        seen.add(text)

            return casts

        except Exception as e:
            logger.error(f"キャスト一覧取得エラー: {e}")
            return []

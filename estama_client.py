"""
エスたま (estama.jp) クライアント — Ajax API ベースの情報取得
"""

import os
import re
import logging
import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

ESTAMA_LOGIN_ID = os.environ.get("ESTAMA_LOGIN_ID", "zr.sendai@gmail.com")
ESTAMA_PASSWORD = os.environ.get("ESTAMA_PASSWORD", "Zenryoku1209")

BASE_URL = "https://estama.jp"
ADMIN_URL = f"{BASE_URL}/admin"


class EstamaClient:
    """エスたま管理画面のスクレイピングクライアント"""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        })
        self._logged_in = False
        self._csrf_token = ""

    def _get_csrf_token(self, url: str) -> str:
        """ページからCSRFトークンを取得"""
        try:
            resp = self.session.get(url, timeout=15)
            soup = BeautifulSoup(resp.text, "html.parser")
            csrf_input = soup.find("input", {"id": "csrf_footer"})
            if csrf_input:
                return csrf_input["value"]
        except Exception:
            pass
        return ""

    def login(self) -> bool:
        """エスたまにAjaxログイン"""
        try:
            # ログインページからCSRFトークン取得
            self._csrf_token = self._get_csrf_token(f"{BASE_URL}/login/")
            if not self._csrf_token:
                logger.error("CSRFトークン取得失敗")
                return False

            # Ajax形式でログイン (jQuery serializeArray互換)
            resp = self.session.post(
                f"{BASE_URL}/post/login_shop",
                data={
                    "str[0][name]": "mail",
                    "str[0][value]": ESTAMA_LOGIN_ID,
                    "str[1][name]": "password",
                    "str[1][value]": ESTAMA_PASSWORD,
                    "str[2][name]": "r",
                    "str[2][value]": "",
                    "ctk": self._csrf_token,
                },
                timeout=15,
                headers={
                    "Referer": f"{BASE_URL}/login/",
                    "X-Requested-With": "XMLHttpRequest",
                },
            )

            if resp.status_code == 200:
                try:
                    data = resp.json()
                    if data[0] == "OK" or data[0] == "REDIRECT_OK":
                        self._logged_in = True
                        logger.info("エスたまにログイン成功")
                        return True
                    else:
                        logger.error(f"エスたまログイン失敗: {data}")
                        return False
                except Exception:
                    pass

            logger.error(f"エスたまログイン失敗: {resp.status_code}")
            return False

        except Exception as e:
            logger.error(f"エスたまログインエラー: {e}")
            return False

    def _ensure_login(self) -> bool:
        if not self._logged_in:
            return self.login()
        # セッション切れチェック
        try:
            resp = self.session.get(f"{ADMIN_URL}/", timeout=10, allow_redirects=False)
            if resp.status_code in (301, 302) and "/login" in resp.headers.get("Location", ""):
                self._logged_in = False
                return self.login()
        except Exception:
            pass
        return True

    def get_dashboard(self) -> dict:
        """管理画面トップの情報を取得"""
        if not self._ensure_login():
            return {"error": "ログインに失敗しました"}

        try:
            resp = self.session.get(f"{ADMIN_URL}/", timeout=15)
            soup = BeautifulSoup(resp.text, "html.parser")
            text = soup.get_text(separator="\n", strip=True)

            result = {
                "shop_name": "",
                "shop_number": "",
                "plan": "",
                "contract_period": "",
                "points": "",
                "notifications": [],
                "menu_items": [],
            }

            lines = text.split("\n")
            for i, line in enumerate(lines):
                line = line.strip()
                if "全力エステ" in line and "仙台" in line:
                    result["shop_name"] = line
                elif "店舗番号" in line:
                    result["shop_number"] = line
                elif "ご契約期間" in line:
                    result["contract_period"] = line
                elif "プラン" in line and ("プラチナ" in line or "ゴールド" in line or "シルバー" in line):
                    result["plan"] = line
                elif "ポイント" in line and i > 0:
                    # ポイント数を取得
                    for j in range(max(0, i-2), min(len(lines), i+2)):
                        if lines[j].strip().isdigit():
                            result["points"] = lines[j].strip()
                            break

            # 予約通知を探す
            links = soup.find_all("a")
            for link in links:
                href = link.get("href", "")
                text_content = link.get_text(strip=True)
                if "予約" in text_content and href:
                    result["notifications"].append(text_content)

            return result

        except Exception as e:
            logger.error(f"ダッシュボード取得エラー: {e}")
            return {"error": str(e)}

    def get_guidance_status(self) -> dict:
        """ご案内状況を取得"""
        if not self._ensure_login():
            return {"error": "ログインに失敗しました"}

        try:
            resp = self.session.get(f"{ADMIN_URL}/guidance/", timeout=15)
            soup = BeautifulSoup(resp.text, "html.parser")
            text = soup.get_text(separator="\n", strip=True)

            result = {
                "status": "不明",
                "therapists": [],
            }

            if "今すぐご案内可" in text:
                result["status"] = "◎ 今すぐご案内可"
            elif "ご案内終了" in text:
                result["status"] = "✕ ご案内終了"
            elif "受付中" in text:
                result["status"] = "○ 受付中"

            # セラピスト情報を抽出
            lines = text.split("\n")
            for line in lines:
                line = line.strip()
                if line and len(line) < 20 and re.match(r"^[\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FFF]+$", line):
                    result["therapists"].append(line)

            return result

        except Exception as e:
            logger.error(f"ご案内状況取得エラー: {e}")
            return {"error": str(e)}

    def get_schedule(self) -> dict:
        """出勤表を取得"""
        if not self._ensure_login():
            return {"error": "ログインに失敗しました"}

        try:
            resp = self.session.get(f"{ADMIN_URL}/schedule/", timeout=15)
            soup = BeautifulSoup(resp.text, "html.parser")
            text = soup.get_text(separator="\n", strip=True)

            # 出勤表から有用な情報を抽出
            schedule_lines = []
            lines = text.split("\n")
            current_date = ""

            for line in lines:
                line = line.strip()
                if not line:
                    continue

                # 日付パターン
                date_match = re.match(r"(\d+/\d+|\d+月\d+日)", line)
                if date_match:
                    current_date = line
                    schedule_lines.append(f"\n📅 {line}")
                    continue

                # セラピスト名 + 時間
                time_match = re.search(r"\d{1,2}:\d{2}", line)
                if time_match and current_date:
                    schedule_lines.append(f"  ⏰ {line}")

            result_text = "\n".join(schedule_lines) if schedule_lines else text[:1500]

            return {
                "schedule_text": result_text if len(result_text) <= 3000 else result_text[:3000] + "\n...",
            }

        except Exception as e:
            logger.error(f"出勤表取得エラー: {e}")
            return {"error": str(e)}

    def get_reservations(self) -> dict:
        """予約一覧を取得"""
        if not self._ensure_login():
            return {"error": "ログインに失敗しました"}

        try:
            resp = self.session.get(f"{ADMIN_URL}/reservation/", timeout=15)
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

    def click_appeal(self) -> bool:
        """集客ワンクリックアピールを実行"""
        if not self._ensure_login():
            return False

        try:
            # ご案内状況ページにアクセス
            resp = self.session.get(f"{ADMIN_URL}/guidance/", timeout=15)
            soup = BeautifulSoup(resp.text, "html.parser")

            # CSRFトークン取得
            csrf_input = soup.find("input", {"id": "csrf_footer"})
            csrf_token = csrf_input["value"] if csrf_input else self._csrf_token

            # 集客ワンクリックアピールのリンク/ボタンを探す
            appeal_links = soup.find_all("a", class_="send-post")
            for link in appeal_links:
                data_post = link.get("data-post", "")
                if "appeal" in data_post.lower() or "アピール" in link.get_text():
                    # Ajax POST で実行
                    data_form = link.get("data-form", "")
                    form = soup.find("form", {"id": f"form-{data_form}"}) if data_form else None

                    post_data = {"ctk": csrf_token}
                    if form:
                        for inp in form.find_all("input"):
                            name = inp.get("name")
                            value = inp.get("value", "")
                            if name:
                                post_data[f"str[0][name]"] = name
                                post_data[f"str[0][value]"] = value

                    resp2 = self.session.post(
                        f"{BASE_URL}/post/{data_post}",
                        data=post_data,
                        timeout=15,
                        headers={
                            "Referer": f"{ADMIN_URL}/guidance/",
                            "X-Requested-With": "XMLHttpRequest",
                        },
                    )

                    if resp2.status_code == 200:
                        logger.info("集客ワンクリックアピール実行成功")
                        return True

            # フォールバック: 直接URLにアクセス
            resp3 = self.session.get(f"{ADMIN_URL}/appeal/", timeout=15)
            if resp3.status_code == 200:
                logger.info("集客アピールページにアクセス成功")
                return True

            logger.warning("アピール機能が見つかりません")
            return False

        except Exception as e:
            logger.error(f"アピール実行エラー: {e}")
            return False

    def get_news_list(self) -> list:
        """ニュース一覧を取得"""
        if not self._ensure_login():
            return []

        try:
            resp = self.session.get(f"{ADMIN_URL}/news/", timeout=15)
            soup = BeautifulSoup(resp.text, "html.parser")

            news_items = []
            # テーブルからニュース情報を抽出
            tables = soup.find_all("table")
            for table in tables:
                rows = table.find_all("tr")
                for row in rows[1:]:  # ヘッダー行をスキップ
                    cells = row.find_all("td")
                    if len(cells) >= 2:
                        news_items.append({
                            "title": cells[0].get_text(strip=True)[:50],
                            "date": cells[-1].get_text(strip=True) if len(cells) > 1 else "",
                        })

            # テーブルがない場合はリストから取得
            if not news_items:
                text = soup.get_text(separator="\n", strip=True)
                lines = text.split("\n")
                for line in lines:
                    line = line.strip()
                    if line and len(line) > 5 and len(line) < 100:
                        date_match = re.search(r"\d{4}[/-]\d{1,2}[/-]\d{1,2}", line)
                        if date_match:
                            news_items.append({
                                "title": line.replace(date_match.group(), "").strip(),
                                "date": date_match.group(),
                            })

            return news_items[:10]

        except Exception as e:
            logger.error(f"ニュース取得エラー: {e}")
            return []

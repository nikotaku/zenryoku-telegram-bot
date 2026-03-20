"""
エスたま (estama.jp) Playwright ブラウザクライアント
ヘッドレスブラウザで出勤登録・取得・アピール等を自動実行する。
"""

import os
import re
import logging
import asyncio
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

# ESTAMA_LOGIN_ID または ESTAMA_EMAIL のどちらの環境変数名でも受け付ける
ESTAMA_LOGIN_ID = (
    os.environ.get("ESTAMA_LOGIN_ID")
    or os.environ.get("ESTAMA_EMAIL")
    or "zr.sendai@gmail.com"
)
ESTAMA_PASSWORD = os.environ.get("ESTAMA_PASSWORD", "Zenryoku1209")

BASE_URL = "https://estama.jp"
ADMIN_URL = f"{BASE_URL}/admin"


class EstamaBrowser:
    """Playwright を使ったエスたま管理画面の自動操作クライアント"""

    def __init__(self):
        self._browser = None
        self._context = None
        self._page = None
        self._logged_in = False

    async def _ensure_browser(self):
        """ブラウザインスタンスを確保する"""
        if self._browser is None:
            from playwright.async_api import async_playwright
            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                    "--single-process",
                ],
            )
            self._context = await self._browser.new_context(
                viewport={"width": 1280, "height": 900},
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
            )
            self._page = await self._context.new_page()

    async def close(self):
        """ブラウザを閉じる"""
        try:
            if self._browser:
                await self._browser.close()
            if hasattr(self, "_playwright") and self._playwright:
                await self._playwright.stop()
        except Exception:
            pass
        finally:
            self._browser = None
            self._context = None
            self._page = None
            self._logged_in = False

    async def login(self) -> bool:
        """エスたまにログイン（複数フォールバック付き）"""
        logger.info(f"エスたまログイン試行: {ESTAMA_LOGIN_ID}")
        try:
            await self._ensure_browser()
            page = self._page

            # ログインページへ移動
            await page.goto(f"{BASE_URL}/login/", wait_until="networkidle", timeout=30000)
            await page.wait_for_timeout(2000)

            # ページの内容をデバッグログ
            current_url = page.url
            logger.info(f"ログインページURL: {current_url}")

            # 既に管理画面にいる場合はログイン済み
            if "/admin" in current_url and "/login" not in current_url:
                self._logged_in = True
                logger.info("エスたま: 既にログイン済み")
                return True

            # 方法1: Ajaxログイン（CSRFトークンあり）
            csrf_token = await page.evaluate("""() => {
                const el = document.getElementById('csrf_footer')
                    || document.querySelector('input[name="ctk"]')
                    || document.querySelector('meta[name="csrf-token"]');
                return el ? (el.value || el.getAttribute('content') || '') : '';
            }""")
            logger.info(f"CSRFトークン: {'found' if csrf_token else 'not found'}")

            if csrf_token:
                login_id_escaped = ESTAMA_LOGIN_ID.replace("'", "\\'")
                password_escaped = ESTAMA_PASSWORD.replace("'", "\\'")
                response = await page.evaluate(f"""async () => {{
                    const formData = new URLSearchParams();
                    formData.append('str[0][name]', 'mail');
                    formData.append('str[0][value]', '{login_id_escaped}');
                    formData.append('str[1][name]', 'password');
                    formData.append('str[1][value]', '{password_escaped}');
                    formData.append('str[2][name]', 'r');
                    formData.append('str[2][value]', '');
                    formData.append('ctk', '{csrf_token}');

                    const resp = await fetch('{BASE_URL}/post/login_shop', {{
                        method: 'POST',
                        headers: {{
                            'Content-Type': 'application/x-www-form-urlencoded',
                            'X-Requested-With': 'XMLHttpRequest',
                        }},
                        body: formData.toString(),
                        credentials: 'include',
                    }});
                    const text = await resp.text();
                    try {{ return JSON.parse(text); }} catch(e) {{ return [text]; }}
                }}""")

                logger.info(f"Ajaxログインレスポンス: {response}")

                if response and isinstance(response, list) and response[0] in ("OK", "REDIRECT_OK"):
                    self._logged_in = True
                    await page.goto(f"{ADMIN_URL}/", wait_until="networkidle", timeout=15000)
                    logger.info("エスたまにAjaxログイン成功")
                    return True

            # 方法2: 通常のフォーム入力ログイン
            mail_input = page.locator(
                'input[name="mail"], input[name="email"], input[type="email"], input#mail'
            )
            if await mail_input.count() > 0:
                await mail_input.first.fill(ESTAMA_LOGIN_ID)
                logger.info("メール入力完了")
            else:
                logger.warning("メール入力フィールドが見つかりません")

            pw_input = page.locator('input[name="password"], input[type="password"]')
            if await pw_input.count() > 0:
                await pw_input.first.fill(ESTAMA_PASSWORD)
                logger.info("パスワード入力完了")
            else:
                logger.warning("パスワード入力フィールドが見つかりません")

            login_btn = page.locator(
                'button:has-text("ログイン"), input[type="submit"], '
                'a:has-text("ログイン"), .btn-login, button[type="submit"]'
            )
            if await login_btn.count() > 0:
                await login_btn.first.click()
                logger.info("ログインボタンクリック")

            await page.wait_for_timeout(3000)

            current_url = page.url
            logger.info(f"ログイン後のURL: {current_url}")

            if "/admin" in current_url or "/login" not in current_url:
                self._logged_in = True
                logger.info("エスたまにフォームログイン成功")
                return True

            logger.error(f"エスたまログイン失敗: URL={current_url}")
            return False

        except Exception as e:
            logger.error(f"エスたまPlaywrightログインエラー: {e}")
            return False

    async def _ensure_login(self) -> bool:
        """ログイン状態を確認し、必要ならログインする"""
        if not self._logged_in:
            return await self.login()

        try:
            await self._ensure_browser()
            await self._page.goto(f"{ADMIN_URL}/", wait_until="networkidle", timeout=15000)
            if "/login" in self._page.url:
                self._logged_in = False
                return await self.login()
        except Exception:
            self._logged_in = False
            return await self.login()

        return True

    # ─── 出勤情報取得 ──────────────────────────────────────

    async def get_schedule(self) -> dict:
        """
        出勤表を取得する。

        Returns:
            {
                "schedules": [
                    {"date": str, "name": str, "start": str, "end": str}
                ],
                "therapist_names": [str],
            }
        """
        if not await self._ensure_login():
            return {"error": "ログインに失敗しました"}

        try:
            page = self._page
            await page.goto(f"{ADMIN_URL}/schedule/", wait_until="networkidle", timeout=30000)
            await page.wait_for_timeout(2000)

            schedules = await page.evaluate("""() => {
                const results = [];
                const rows = document.querySelectorAll('tr, .schedule-row, .schedule-item');
                rows.forEach(row => {
                    const text = row.textContent.trim();
                    const timeMatch = text.match(/(\\d{1,2}:\\d{2})[〜~\\-](\\d{1,2}:\\d{2})/);
                    if (timeMatch) {
                        // 名前を抽出（時間の前のテキスト）
                        const parts = text.split(timeMatch[0]);
                        const name = parts[0].replace(/[\\d\\/月日（）()\\s]/g, '').trim();
                        results.push({
                            name: name,
                            start: timeMatch[1],
                            end: timeMatch[2],
                            raw: text.substring(0, 100),
                        });
                    }
                });
                return results;
            }""")

            therapist_names = list(set(s["name"] for s in schedules if s.get("name")))

            return {
                "schedules": schedules,
                "therapist_names": therapist_names,
            }

        except Exception as e:
            logger.error(f"出勤表取得エラー: {e}")
            return {"error": str(e)}

    async def get_therapist_list(self) -> list:
        """セラピスト一覧を取得する"""
        if not await self._ensure_login():
            return []

        try:
            page = self._page
            await page.goto(f"{ADMIN_URL}/therapist/", wait_until="networkidle", timeout=30000)
            await page.wait_for_timeout(2000)

            therapists = await page.evaluate("""() => {
                const results = [];
                const items = document.querySelectorAll(
                    '.therapist-item, .therapist-row, tr, .list-item'
                );
                items.forEach(item => {
                    const links = item.querySelectorAll('a');
                    links.forEach(link => {
                        const href = link.getAttribute('href') || '';
                        const name = link.textContent.trim();
                        if (href.includes('therapist') && name && name.length < 20
                            && !name.includes('追加') && !name.includes('編集')) {
                            results.push({
                                name: name,
                                url: href,
                            });
                        }
                    });
                });
                // 重複除去
                const seen = new Set();
                return results.filter(r => {
                    if (seen.has(r.name)) return false;
                    seen.add(r.name);
                    return true;
                });
            }""")

            return therapists

        except Exception as e:
            logger.error(f"セラピスト一覧取得エラー: {e}")
            return []

    # ─── 出勤登録 ──────────────────────────────────────────

    async def register_schedule(
        self,
        therapist_name: str,
        date_str: str,
        start_time: str,
        end_time: str,
    ) -> dict:
        """
        エスたまに出勤スケジュールを登録する。

        Args:
            therapist_name: セラピスト名
            date_str: 日付 "YYYY-MM-DD"
            start_time: 開始時刻 "HH:MM"
            end_time: 終了時刻 "HH:MM"

        Returns:
            {"success": bool, "message": str}
        """
        if not await self._ensure_login():
            return {"success": False, "message": "ログインに失敗しました"}

        try:
            page = self._page

            # 出勤表ページへ移動
            await page.goto(f"{ADMIN_URL}/schedule/", wait_until="networkidle", timeout=30000)
            await page.wait_for_timeout(2000)

            # セラピスト選択
            therapist_select = page.locator('select[name*="therapist"], select#therapist_id')
            if await therapist_select.count() > 0:
                options = await therapist_select.first.locator("option").all()
                for opt in options:
                    text = await opt.text_content()
                    if therapist_name in text:
                        value = await opt.get_attribute("value")
                        await therapist_select.first.select_option(value=value)
                        break

            # 日付入力
            date_input = page.locator('input[name*="date"], input[type="date"], input[name*="day"]')
            if await date_input.count() > 0:
                await date_input.first.fill(date_str)

            # 開始時刻
            start_h_select = page.locator('select[name*="start_h"], select[name*="from_h"]')
            start_m_select = page.locator('select[name*="start_m"], select[name*="from_m"]')
            start_input = page.locator('input[name*="start_time"]')

            if await start_h_select.count() > 0 and await start_m_select.count() > 0:
                h, m = start_time.split(":")
                await start_h_select.first.select_option(value=h.lstrip("0") or "0")
                await start_m_select.first.select_option(value=m.lstrip("0") or "0")
            elif await start_input.count() > 0:
                await start_input.first.fill(start_time)

            # 終了時刻
            end_h_select = page.locator('select[name*="end_h"], select[name*="to_h"]')
            end_m_select = page.locator('select[name*="end_m"], select[name*="to_m"]')
            end_input = page.locator('input[name*="end_time"]')

            if await end_h_select.count() > 0 and await end_m_select.count() > 0:
                h, m = end_time.split(":")
                await end_h_select.first.select_option(value=h.lstrip("0") or "0")
                await end_m_select.first.select_option(value=m.lstrip("0") or "0")
            elif await end_input.count() > 0:
                await end_input.first.fill(end_time)

            await page.wait_for_timeout(500)

            # 保存ボタンをクリック
            save_btn = page.locator(
                'button:has-text("保存"), button:has-text("登録"), '
                'input[type="submit"], .btn-primary, .btn-success, '
                'a.send-post:has-text("保存")'
            )
            if await save_btn.count() > 0:
                await save_btn.first.click()
                await page.wait_for_timeout(3000)

                return {
                    "success": True,
                    "message": f"出勤登録完了: {therapist_name} {date_str} {start_time}〜{end_time}",
                }
            else:
                return {"success": False, "message": "保存ボタンが見つかりません"}

        except Exception as e:
            logger.error(f"出勤登録エラー: {e}")
            return {"success": False, "message": f"エラー: {str(e)}"}

    # ─── ご案内状況・アピール ───────────────────────────────

    async def set_guidance_status(self, status: str = "now") -> dict:
        """
        ご案内状況を設定する。

        Args:
            status: "now"（今すぐご案内可）, "accepting"（受付中）, "ended"（ご案内終了）
        """
        if not await self._ensure_login():
            return {"success": False, "message": "ログインに失敗しました"}

        try:
            page = self._page
            await page.goto(f"{ADMIN_URL}/guidance/", wait_until="networkidle", timeout=30000)
            await page.wait_for_timeout(2000)

            status_map = {
                "now": "今すぐご案内可",
                "accepting": "受付中",
                "ended": "ご案内終了",
            }
            target_text = status_map.get(status, "今すぐご案内可")

            btn = page.locator(f'button:has-text("{target_text}"), a:has-text("{target_text}")')
            if await btn.count() > 0:
                await btn.first.click()
                await page.wait_for_timeout(2000)
                return {"success": True, "message": f"ご案内状況を「{target_text}」に設定しました"}
            else:
                return {"success": False, "message": f"「{target_text}」ボタンが見つかりません"}

        except Exception as e:
            logger.error(f"ご案内状況設定エラー: {e}")
            return {"success": False, "message": f"エラー: {str(e)}"}

    async def click_appeal(self) -> dict:
        """集客ワンクリックアピールを実行する"""
        if not await self._ensure_login():
            return {"success": False, "message": "ログインに失敗しました"}

        try:
            page = self._page
            await page.goto(f"{ADMIN_URL}/guidance/", wait_until="networkidle", timeout=30000)
            await page.wait_for_timeout(2000)

            appeal_btn = page.locator(
                'a:has-text("アピール"), button:has-text("アピール"), '
                '.appeal-btn, a:has-text("集客")'
            )
            if await appeal_btn.count() > 0:
                await appeal_btn.first.click()
                await page.wait_for_timeout(2000)
                return {"success": True, "message": "集客ワンクリックアピールを実行しました"}
            else:
                return {"success": False, "message": "アピールボタンが見つかりません"}

        except Exception as e:
            logger.error(f"アピール実行エラー: {e}")
            return {"success": False, "message": f"エラー: {str(e)}"}

    # ─── シフト同期（キャスカン → エスたま） ─────────────────

    async def sync_from_caskan(self, caskan_shifts: list) -> dict:
        """
        キャスカンのシフトデータをエスたまに同期する。

        Args:
            caskan_shifts: [{"date": str, "name": str, "start": str, "end": str}, ...]

        Returns:
            {"success": bool, "synced": int, "failed": int, "details": [str]}
        """
        synced = 0
        failed = 0
        details = []

        for shift in caskan_shifts:
            result = await self.register_schedule(
                therapist_name=shift["name"],
                date_str=shift["date"],
                start_time=shift["start"],
                end_time=shift["end"],
            )
            if result.get("success"):
                synced += 1
                details.append(f"✅ {result['message']}")
            else:
                failed += 1
                details.append(f"❌ {shift['name']} {shift['date']}: {result['message']}")

            # 連続操作の間隔を空ける
            await asyncio.sleep(2)

        return {
            "success": failed == 0,
            "synced": synced,
            "failed": failed,
            "details": details,
        }

    async def take_screenshot(self, path: str = "/tmp/estama_screenshot.png") -> str:
        """デバッグ用スクリーンショットを撮る"""
        try:
            await self._ensure_browser()
            await self._page.screenshot(path=path, full_page=True)
            return path
        except Exception as e:
            logger.error(f"スクリーンショットエラー: {e}")
            return ""

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

    def _requests_login_cookies(self):
        """
        requests でエスたまに Ajax ログインし、Playwright 形式の Cookie を返す。
        estama_client.py と同じ実績のあるログインフローを使う。
        失敗時は None。
        """
        try:
            import requests
            from bs4 import BeautifulSoup
        except Exception as e:
            logger.warning(f"requests/bs4 が利用できません: {e}")
            return None
        try:
            session = requests.Session()
            session.headers.update({
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                )
            })
            resp = session.get(f"{BASE_URL}/login/", timeout=15)
            soup = BeautifulSoup(resp.text, "html.parser")
            csrf_input = soup.find("input", {"id": "csrf_footer"})
            csrf_token = csrf_input["value"] if csrf_input else ""
            if not csrf_token:
                logger.error("requests: CSRFトークン取得失敗")
                return None

            resp = session.post(
                f"{BASE_URL}/post/login_shop",
                data={
                    "str[0][name]": "mail",
                    "str[0][value]": ESTAMA_LOGIN_ID,
                    "str[1][name]": "password",
                    "str[1][value]": ESTAMA_PASSWORD,
                    "str[2][name]": "r",
                    "str[2][value]": "",
                    "ctk": csrf_token,
                },
                timeout=15,
                headers={
                    "Referer": f"{BASE_URL}/login/",
                    "X-Requested-With": "XMLHttpRequest",
                },
            )
            ok = False
            try:
                data = resp.json()
                ok = data and data[0] in ("OK", "REDIRECT_OK")
            except Exception:
                ok = False
            if not ok:
                logger.error(f"requests: ログイン失敗 status={resp.status_code} body={resp.text[:120]}")
                return None

            cookies = []
            for c in session.cookies:
                cookies.append({
                    "name": c.name,
                    "value": c.value,
                    "domain": c.domain or "estama.jp",
                    "path": c.path or "/",
                })
            logger.info(f"requests: ログイン成功（Cookie {len(cookies)}件取得）")
            return cookies or None
        except Exception as e:
            logger.error(f"requests ログインエラー: {e}")
            return None

    async def login(self) -> bool:
        """エスたまにログイン"""
        logger.info(f"エスたまログイン試行: {ESTAMA_LOGIN_ID}")

        # 方法0: requests で確実にログインし、Cookie を Playwright に注入する
        try:
            cookies = self._requests_login_cookies()
            if cookies:
                await self._ensure_browser()
                await self._context.add_cookies(cookies)
                await self._page.goto(f"{ADMIN_URL}/", wait_until="domcontentloaded", timeout=20000)
                if "/login" not in self._page.url:
                    self._logged_in = True
                    logger.info("エスたま: requests Cookie 注入でログイン成功")
                    return True
                logger.warning("Cookie 注入後も未ログイン状態。ブラウザログインにフォールバック")
        except Exception as e:
            logger.warning(f"Cookie 注入ログイン失敗（フォールバックします）: {e}")

        try:
            await self._ensure_browser()
            page = self._page

            await page.goto(f"{BASE_URL}/login/", wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(1500)

            current_url = page.url
            logger.info(f"ログインページURL: {current_url}")

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
                    await page.goto(f"{ADMIN_URL}/", wait_until="domcontentloaded", timeout=15000)
                    logger.info("エスたまにAjaxログイン成功")
                    return True

            # 方法2: フォーム入力ログイン
            mail_input = page.locator('input[name="mail"], input[name="email"], input[type="email"]')
            if await mail_input.count() > 0:
                await mail_input.first.fill(ESTAMA_LOGIN_ID)
                logger.info("メール入力完了")

            pw_input = page.locator('input[name="password"], input[type="password"]')
            if await pw_input.count() > 0:
                await pw_input.first.fill(ESTAMA_PASSWORD)
                logger.info("パスワード入力完了")

            submit_btn = page.locator(
                'input[type="submit"], button[type="submit"], '
                'button:has-text("ログイン"), a:has-text("ログイン")'
            )
            if await submit_btn.count() > 0:
                await submit_btn.first.click()
                logger.info("ログインボタンクリック")
            else:
                logger.error("ログインボタンが見つかりません")
                return False

            # リダイレクト完了を待つ
            try:
                await page.wait_for_url(f"**/admin/**", timeout=10000)
            except Exception:
                await page.wait_for_timeout(4000)

            current_url = page.url
            logger.info(f"ログイン後のURL: {current_url}")

            if "/admin" in current_url and "/login" not in current_url:
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

    async def click_guest_appeals(self) -> dict:
        """
        /admin/guest/appeal/ の「店舗情報」「クーポン情報」「お店体験談」
        アピールボタンを順番にクリックする。
        """
        if not await self._ensure_login():
            return {"success": False, "message": "ログインに失敗しました"}

        try:
            page = self._page
            await page.goto(f"{ADMIN_URL}/guest/appeal/", wait_until="networkidle", timeout=30000)
            await page.wait_for_timeout(2000)

            targets = ["店舗情報", "クーポン情報", "お店体験談"]
            clicked = []
            failed = []

            for label in targets:
                # 各カテゴリ行の中にあるアピールボタンを探す
                # 行要素 (tr/div/li) に label テキストが含まれ、その中のボタン/リンク
                btn = page.locator(
                    f'tr:has-text("{label}") a:has-text("アピール"), '
                    f'tr:has-text("{label}") button:has-text("アピール"), '
                    f'div:has-text("{label}") a:has-text("アピール"), '
                    f'div:has-text("{label}") button:has-text("アピール"), '
                    f'li:has-text("{label}") a:has-text("アピール"), '
                    f'li:has-text("{label}") button:has-text("アピール")'
                ).first
                if await btn.count() > 0:
                    await btn.click()
                    await page.wait_for_timeout(1500)
                    clicked.append(label)
                    logger.info(f"アピール成功: {label}")
                else:
                    failed.append(label)
                    logger.warning(f"アピールボタン未検出: {label}")

            if clicked:
                msg = f"アピール完了: {', '.join(clicked)}"
                if failed:
                    msg += f"（未検出: {', '.join(failed)}）"
                return {"success": True, "message": msg, "clicked": clicked, "failed": failed}
            else:
                return {"success": False, "message": "アピールボタンが1つも見つかりませんでした", "clicked": [], "failed": failed}

        except Exception as e:
            logger.error(f"ゲストアピール実行エラー: {e}")
            return {"success": False, "message": f"エラー: {str(e)}"}

    async def click_cast_appeal(self) -> dict:
        """
        /admin/cast/appeal/ のセラピストアピールを実行する。
        手順:
          1. 出勤が早い順で絞り込む
          2. 一番上のセラピストにチェック
          3. アピールボタンを押す
        """
        if not await self._ensure_login():
            return {"success": False, "message": "ログインに失敗しました"}

        try:
            page = self._page
            await page.goto(f"{ADMIN_URL}/cast/appeal/", wait_until="networkidle", timeout=30000)
            await page.wait_for_timeout(2000)

            # 1. 出勤が早い順で絞り込む（並び替えセレクト or リンク）
            sorted_ok = False
            sort_select = page.locator(
                'select[name*="sort"], select[name*="order"], select#sort, select#order'
            )
            if await sort_select.count() > 0:
                options = await sort_select.first.locator("option").all()
                for opt in options:
                    text = (await opt.text_content() or "")
                    if "出勤" in text and ("早" in text or "順" in text):
                        value = await opt.get_attribute("value")
                        await sort_select.first.select_option(value=value)
                        await page.wait_for_timeout(2000)
                        sorted_ok = True
                        logger.info(f"出勤順ソート選択: {text.strip()}")
                        break
            if not sorted_ok:
                sort_link = page.locator(
                    'a:has-text("出勤が早い"), a:has-text("出勤順"), '
                    'button:has-text("出勤が早い"), button:has-text("出勤順")'
                ).first
                if await sort_link.count() > 0:
                    await sort_link.click()
                    await page.wait_for_timeout(2000)
                    sorted_ok = True
                    logger.info("出勤順ソートリンクをクリック")
            if not sorted_ok:
                logger.warning("出勤順の絞り込みコントロールが見つかりませんでした（既定順で続行）")

            # 2. 一番上のセラピストにチェック
            checkbox = page.locator('input[type="checkbox"]').first
            if await checkbox.count() == 0:
                return {"success": False, "message": "セラピストのチェックボックスが見つかりません"}
            if not await checkbox.is_checked():
                await checkbox.check()
            await page.wait_for_timeout(500)
            logger.info("一番上のセラピストにチェック")

            # 3. アピールボタンを押す
            # JS でページ本文に表示されているアピール要素を探す（ナビリンクを除外）
            btn_info = await page.evaluate("""() => {
                const cands = [];
                for (const el of document.querySelectorAll(
                    'button, input[type="submit"], a.btn, a.button, a[class*="btn"]'
                )) {
                    const text = (el.textContent || el.value || '').trim();
                    if (!text.includes('アピール')) continue;
                    const href = el.getAttribute('href') || '';
                    // ナビリンク（現ページ自身へのリンク）を除外
                    if (href.includes('/cast/appeal/')) continue;
                    const rect = el.getBoundingClientRect();
                    if (rect.width === 0 || rect.height === 0) continue;
                    cands.push({tag: el.tagName, text: text.slice(0,40), cls: el.className, href});
                }
                return cands;
            }""")
            logger.info(f"アピールボタン候補: {btn_info}")

            # 候補を元にクリック
            clicked = False
            for info in (btn_info or []):
                tag = info.get("tag", "").upper()
                text = info.get("text", "")
                if tag == "INPUT":
                    locator = page.locator(f'input[type="submit"][value*="アピール"]').first
                elif tag == "BUTTON":
                    locator = page.locator(f'button:has-text("アピール")').first
                else:
                    cls = info.get("cls", "")
                    href = info.get("href", "")
                    if cls:
                        locator = page.locator(f'a.{cls.split()[0]}:has-text("アピール")').first
                    else:
                        locator = page.locator(f'a[href="{href}"]').first
                if await locator.count() > 0:
                    await locator.scroll_into_view_if_needed()
                    await locator.click()
                    clicked = True
                    break

            if not clicked:
                # フォールバック: ページ本文（#contents, main, form 内）のアピールリンク
                fallback = page.locator(
                    '#contents a:has-text("アピール"), '
                    'main a:has-text("アピール"), '
                    'form a:has-text("アピール"), '
                    'form button:has-text("アピール"), '
                    '.contents a:has-text("アピール")'
                ).first
                if await fallback.count() > 0:
                    await fallback.scroll_into_view_if_needed()
                    await fallback.click()
                    clicked = True

            if not clicked:
                return {"success": False, "message": "アピールボタンが見つかりません（候補なし）"}

            await page.wait_for_timeout(2000)
            return {"success": True, "message": "セラピストアピールを実行しました（出勤が早い順・一番上）"}

        except Exception as e:
            logger.error(f"セラピストアピール実行エラー: {e}")
            return {"success": False, "message": f"エラー: {str(e)}"}

    async def update_schedule_status(self, now_min: Optional[int] = None) -> dict:
        """
        各セラピストの編集ページ (/admin/schedule/{idx}/) を Playwright で開き、
        JS レンダリング後の DOM から今日の日付列で現在時刻より前の○スロットを
        ×に変更してフォームを保存する。

        個別スロット select が見つからない場合（システム制約）は、
        シフト終了済みのセラピストに限り「完売」ボタンで全スロットを×にする。

        Args:
            now_min: 営業日基準の現在分（None なら JST 現在時刻から算出）。
                     0:00〜5:59 は深夜営業として +24h 換算する。

        Returns:
            {"success": bool, "message": str, "changed": [str]}
        """
        import pytz

        if not await self._ensure_login():
            return {"success": False, "message": "ログインに失敗しました", "changed": []}

        jst = pytz.timezone("Asia/Tokyo")
        now_jst = datetime.now(jst)
        if now_min is None:
            now_min = now_jst.hour * 60 + now_jst.minute
            if now_jst.hour < 6:
                now_min += 24 * 60
        today_str = now_jst.strftime("%Y-%m-%d")

        page = self._page

        # セラピスト一覧を表示ページから取得
        try:
            await page.goto(f"{ADMIN_URL}/schedule/", wait_until="networkidle", timeout=30000)
            await page.wait_for_timeout(1000)
            therapists = await page.evaluate("""() => {
                return Array.from(document.querySelectorAll('thead th[data-idx]')).map(th => ({
                    idx: th.getAttribute('data-idx'),
                    name: th.textContent.trim().slice(0, 20)
                })).filter(t => t.idx);
            }""")
        except Exception as e:
            return {"success": False, "message": f"出勤表取得エラー: {e}", "changed": []}

        if not therapists:
            return {"success": True, "message": "セラピストが見つかりませんでした", "changed": []}

        changed = []

        for t in therapists:
            idx = t["idx"]
            tname = t["name"]
            try:
                await page.goto(f"{ADMIN_URL}/schedule/{idx}/",
                                wait_until="networkidle", timeout=30000)
                await page.wait_for_timeout(2000)  # JS による tbody レンダリング待ち

                # JS-rendered DOM から今日の時間帯セレクトを操作
                result = await page.evaluate("""(args) => {
                    const {todayStr, nowMin} = args;

                    // 今日の日付を含むすべての select を列挙（JS レンダリング後）
                    const allSelects = Array.from(document.querySelectorAll('select')).filter(
                        s => (s.name || '').includes('column[' + todayStr + ']')
                    );
                    const allNames = allSelects.map(s => s.name);

                    // 開始/終了セレクト（[select]）を除いた時間帯セレクト
                    const timeSelects = allSelects.filter(
                        s => !s.name.includes('[select]')
                    );

                    // 今日の開始・終了時刻を取得（完売フォールバック用）
                    const startSel = document.querySelector(
                        'select[name="column[' + todayStr + '][select][select_start]"]'
                    );
                    const endSel = document.querySelector(
                        'select[name="column[' + todayStr + '][select][select_end]"]'
                    );
                    const startVal = startSel ? (startSel.options[startSel.selectedIndex] || {}).value || '' : '';
                    const endVal = endSel ? (endSel.options[endSel.selectedIndex] || {}).value || '' : '';

                    const changedSlots = [];

                    for (const sel of timeSelects) {
                        const m = sel.name.match(/\\[(\\d{1,2}:\\d{2})\\]$/);
                        if (!m) continue;

                        const [h, mi] = m[1].split(':').map(Number);
                        let slotMin = h * 60 + mi;
                        if (h < 6) slotMin += 24 * 60;
                        if (slotMin >= nowMin) continue;  // 未来はスキップ

                        const curOpt = sel.options[sel.selectedIndex];
                        if (!curOpt) continue;
                        const curText = curOpt.text || '';
                        const curVal  = curOpt.value || '';

                        // ○（受付可）でなければスキップ
                        if (!curText.includes('○') && !curText.includes('◯') && curVal !== '1') continue;

                        // ×オプションを探す
                        let closeOpt = null;
                        for (const opt of Array.from(sel.options)) {
                            const t = opt.text || '', v = opt.value || '';
                            if (t.includes('×') || t.includes('✕') ||
                                ['2','soldout','close','x'].includes(v)) {
                                closeOpt = opt; break;
                            }
                        }
                        if (!closeOpt) continue;

                        sel.value = closeOpt.value;
                        sel.dispatchEvent(new Event('change', {bubbles: true}));
                        changedSlots.push(m[1]);
                    }

                    return {allNames, changedSlots, startVal, endVal};
                }""", {"todayStr": today_str, "nowMin": now_min})

                all_names = result.get("allNames", [])
                slots = result.get("changedSlots", [])
                start_val = result.get("startVal", "")
                end_val   = result.get("endVal", "")
                logger.info(f"{tname} 今日のセレクト({len(all_names)}件): {all_names[:5]}")

                if slots:
                    # 変更があればフォームを保存
                    save_btn = page.locator(
                        'a:has-text("出勤情報を保存"), '
                        'input[type=submit], '
                        'button[type=submit]'
                    )
                    if await save_btn.count() > 0:
                        await save_btn.first.click()
                        await page.wait_for_timeout(2000)
                    for s in slots:
                        changed.append(f"{tname} {s}")
                        logger.info(f"スケジュール更新: {tname} {s} ○→×")

                elif not all_names:
                    # 個別スロット select が存在しない → 完売フォールバック
                    # シフト終了済みの場合のみ 完売 ボタンをクリック
                    if start_val:
                        em = re.match(r"(\d{1,2}):(\d{2})", end_val) if end_val not in ("", "99:99") else None
                        if em:
                            end_h, end_m = int(em.group(1)), int(em.group(2))
                            end_min_val = end_h * 60 + end_m
                            if end_h < 6:
                                end_min_val += 24 * 60
                        else:
                            end_min_val = 25 * 60  # 99:99 = 未定、翌1時扱い
                        if now_min > end_min_val:
                            soldout_btn = page.locator(
                                f'.sce_soldout[data-tg="column[{today_str}]"]'
                            )
                            if await soldout_btn.count() > 0:
                                await soldout_btn.click()
                                await page.wait_for_timeout(2000)
                                changed.append(f"{tname}(完売)")
                                logger.info(f"スケジュール完売: {tname} {today_str}")

            except Exception as e:
                logger.warning(f"{tname} 処理エラー: {e}")
                continue

        if changed:
            return {
                "success": True,
                "message": f"{len(changed)}件を○→×に更新: " + ", ".join(changed),
                "changed": changed,
            }
        return {"success": True, "message": "更新対象（過去の○）はありませんでした", "changed": []}

    async def dump_schedule_debug(self, screenshot_path: str = "/tmp/estama_schedule.png") -> dict:
        """
        デバッグ用: 出勤表ページのスクリーンショットと主要HTMLを取得する。
        セレクタ調整のため、構造把握に使う。

        Returns:
            {"success": bool, "screenshot": str, "html": str, "message": str}
        """
        if not await self._ensure_login():
            return {"success": False, "message": "ログインに失敗しました", "screenshot": "", "html": ""}

        try:
            page = self._page
            await page.goto(f"{ADMIN_URL}/schedule/", wait_until="networkidle", timeout=30000)
            await page.wait_for_timeout(2000)

            try:
                await page.screenshot(path=screenshot_path, full_page=True)
            except Exception as se:
                logger.warning(f"スクショ取得失敗: {se}")
                screenshot_path = ""

            # セラピスト一覧（data-idx と名前）を取得
            therapists = await page.evaluate(r"""() => {
                const out = [];
                document.querySelectorAll('thead th[data-idx]').forEach(th => {
                    const idx = th.getAttribute('data-idx');
                    const name = (th.querySelector('span') || th).textContent.trim();
                    if (idx) out.push({ idx, name });
                });
                return out;
            }""")

            # 最初のセラピストの編集ページ（/admin/schedule/{idx}/）の HTML を取得
            edit_html = ""
            edit_target = ""
            if therapists:
                edit_idx = therapists[0]["idx"]
                edit_target = f"{therapists[0]['name']} (idx={edit_idx})"
                try:
                    await page.goto(f"{ADMIN_URL}/schedule/{edit_idx}/", wait_until="networkidle", timeout=30000)
                    await page.wait_for_timeout(2000)
                    try:
                        await page.screenshot(path="/tmp/estama_schedule_edit.png", full_page=True)
                    except Exception:
                        pass
                    edit_html = await page.evaluate(r"""() => {
                        const out = [];

                        // 今日の日付列の select 名を全列挙（JS レンダリング後）
                        const today = new Date().toISOString().slice(0,10);
                        const allSels = Array.from(document.querySelectorAll('select'))
                            .filter(s => (s.name||'').includes('column[' + today + ']'));
                        if (allSels.length) {
                            const info = allSels.map(s => {
                                const cur = s.options[s.selectedIndex];
                                const opts = Array.from(s.options).map(o => o.text+'='+o.value).join(', ');
                                return s.name + ' (cur=' + (cur?cur.text:'?') + ') [' + opts + ']';
                            }).join('\n');
                            out.push('<!-- 今日のSELECT一覧 -->\n' + info);
                        } else {
                            out.push('<!-- 今日のSELECT: 見つかりません（tbody未レンダリングの可能性） -->');
                        }

                        // tbody: 最初の3行のHTML（select name確認用）
                        const tbody = document.querySelector('table.sce_tb tbody');
                        if (tbody) {
                            const rows = Array.from(tbody.querySelectorAll('tr')).slice(0, 3);
                            if (rows.length) {
                                const sample = rows.map(r => r.outerHTML).join('\n');
                                let s = sample;
                                if (s.length > 6000) s = s.slice(0, 6000) + '\n<!-- truncated -->';
                                out.push('<!-- TBODY SAMPLE (first 3 rows) -->\n' + s);
                            } else {
                                out.push('<!-- TBODY: 行なし（JSレンダリング未完？） -->');
                            }
                        } else {
                            out.push('<!-- TBODY: 要素自体なし -->');
                        }

                        return out.join('\n\n');
                    }""")
                except Exception as ee:
                    logger.warning(f"編集ページ取得失敗: {ee}")

            info = "セラピスト: " + ", ".join(f"{t['name']}={t['idx']}" for t in therapists)
            html = (
                f"<!-- 出勤表セラピスト一覧 -->\n{info}\n\n"
                f"<!-- 編集ページ /admin/schedule/{therapists[0]['idx'] if therapists else ''}/ ({edit_target}) -->\n"
                f"{edit_html}"
            )

            return {
                "success": True,
                "screenshot": screenshot_path,
                "edit_screenshot": "/tmp/estama_schedule_edit.png",
                "html": html,
                "message": f"出勤表＋編集ページのHTML/スクショを取得しました（{info}）",
            }

        except Exception as e:
            logger.error(f"出勤表デバッグ取得エラー: {e}")
            return {"success": False, "message": f"エラー: {str(e)}", "screenshot": "", "html": ""}

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

    async def post_diary(self, therapist_name: str, title: str, body: str, image_bytes: bytes) -> dict:
        """
        エスたまに写メ日記（ブログ）を投稿する
        """
        if not await self._ensure_login():
            return {"success": False, "message": "ログインに失敗しました"}

        tmp_path = None
        try:
            import tempfile

            page = self._page
            await page.goto(f"{ADMIN_URL}/blog_edit/", wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(2000)

            # タイトル入力
            title_input = page.locator("input[name*='title'], input[placeholder*='タイトル'], input[name='title']")
            if await title_input.count() > 0:
                await title_input.first.fill(title)

            # 本文入力
            body_input = page.locator("textarea[name*='body'], textarea[name*='content'], textarea[placeholder*='本文'], textarea")
            if await body_input.count() > 0:
                await body_input.first.fill(body)

            # 画像アップロード（画像がある場合のみ）
            if image_bytes:
                with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
                    tmp.write(image_bytes)
                    tmp_path = tmp.name
                file_input = page.locator("input[type='file']")
                if await file_input.count() > 0:
                    await file_input.first.set_input_files(tmp_path)

            # 送信ボタン
            submit_btn = page.locator(
                "input[type='submit'], button[type='submit'], "
                "button:has-text('投稿'), button:has-text('保存')"
            )
            if await submit_btn.count() > 0:
                await submit_btn.first.click()
                await page.wait_for_timeout(3000)
            else:
                return {"success": False, "message": "送信ボタンが見つかりません"}

            if await page.locator("text='エラー'").count() > 0:
                return {"success": False, "message": "投稿画面でエラーが発生しました"}

            return {"success": True, "message": "エスたま投稿完了"}

        except Exception as e:
            logger.error(f"エスたま日記投稿エラー: {e}")
            return {"success": False, "message": str(e)}
        finally:
            if tmp_path:
                try:
                    import os
                    os.unlink(tmp_path)
                except Exception:
                    pass

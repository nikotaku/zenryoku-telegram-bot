"""
キャスカン (caskan.jp) Playwright ブラウザクライアント
ヘッドレスブラウザでシフト登録・取得・削除を自動実行する。
"""

import os
import re
import logging
import asyncio
from datetime import datetime, timedelta, date as date_type
from typing import Optional

logger = logging.getLogger(__name__)

CASKAN_SHOP_ID = os.environ.get("CASKAN_SHOP_ID", "Zenryoku1209")
CASKAN_LOGIN_ID = os.environ.get("CASKAN_LOGIN_ID", "zr.sendai@gmail.com")
CASKAN_PASSWORD = os.environ.get("CASKAN_PASSWORD", "Zenryoku1209")

BASE_URL = "https://my.caskan.jp"


class CaskanBrowser:
    """Playwright を使ったキャスカン管理画面の自動操作クライアント"""

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
        """キャスカンにログイン（2段階フォーム）"""
        try:
            await self._ensure_browser()
            page = self._page

            # Step 1: ログインページへ移動
            await page.goto(f"{BASE_URL}/login", wait_until="networkidle", timeout=30000)
            await page.wait_for_timeout(1000)

            # 店舗IDを入力
            shop_input = page.locator('input[name="shop_code"]')
            if await shop_input.count() > 0:
                await shop_input.fill(CASKAN_SHOP_ID)
            else:
                # name属性が異なる場合のフォールバック
                inputs = page.locator("input[type='text']")
                if await inputs.count() > 0:
                    await inputs.first.fill(CASKAN_SHOP_ID)

            # ログインIDを入力
            login_input = page.locator('input[name="code"]')
            if await login_input.count() > 0:
                await login_input.fill(CASKAN_LOGIN_ID)
            else:
                inputs = page.locator("input[type='text'], input[type='email']")
                if await inputs.count() > 1:
                    await inputs.nth(1).fill(CASKAN_LOGIN_ID)

            # Step 1 送信
            submit_btn = page.locator('button[type="submit"], input[type="submit"]')
            if await submit_btn.count() > 0:
                await submit_btn.first.click()
            await page.wait_for_timeout(2000)

            # Step 2: パスワード入力
            pw_input = page.locator('input[name="login_password"], input[type="password"]')
            if await pw_input.count() > 0:
                await pw_input.first.fill(CASKAN_PASSWORD)

            submit_btn2 = page.locator('button[type="submit"], input[type="submit"]')
            if await submit_btn2.count() > 0:
                await submit_btn2.first.click()

            await page.wait_for_timeout(3000)

            # ログイン成功判定
            current_url = page.url
            if "/login" not in current_url:
                self._logged_in = True
                logger.info("キャスカンにPlaywrightでログイン成功")
                return True
            else:
                logger.error("キャスカンログイン失敗（リダイレクトされず）")
                return False

        except Exception as e:
            logger.error(f"キャスカンPlaywrightログインエラー: {e}")
            return False

    async def _ensure_login(self) -> bool:
        """ログイン状態を確認し、必要ならログインする"""
        if not self._logged_in:
            return await self.login()

        try:
            await self._ensure_browser()
            # セッション切れチェック
            current_url = self._page.url
            if "/login" in current_url:
                self._logged_in = False
                return await self.login()
            # ホームにアクセスしてリダイレクトを確認
            await self._page.goto(f"{BASE_URL}/", wait_until="networkidle", timeout=15000)
            if "/login" in self._page.url:
                self._logged_in = False
                return await self.login()
        except Exception:
            self._logged_in = False
            return await self.login()

        return True

    # ─── シフト取得 ─────────────────────────────────────────

    async def get_shift_page(self, target_date: Optional[str] = None) -> dict:
        """
        シフトページから指定日付周辺のシフト情報を取得する。

        Args:
            target_date: "YYYY-MM-DD" 形式の日付（Noneなら今日）

        Returns:
            {
                "shifts": [
                    {"date": "YYYY-MM-DD", "name": str, "start": str, "end": str, "room": str}
                ],
                "cast_names": [str],
                "room_names": [str],
            }
        """
        if not await self._ensure_login():
            return {"error": "ログインに失敗しました"}

        try:
            page = self._page
            if target_date:
                url = f"{BASE_URL}/shift/view?start_day={target_date}"
            else:
                url = f"{BASE_URL}/shift/view"

            await page.goto(url, wait_until="networkidle", timeout=30000)
            await page.wait_for_timeout(2000)

            # シフト情報を抽出
            shifts = await page.evaluate("""() => {
                const results = [];
                // parts-cast-table からシフト情報を取得
                const tables = document.querySelectorAll('.parts-cast-table, table');
                tables.forEach(table => {
                    const rows = table.querySelectorAll('tr');
                    rows.forEach(row => {
                        const spans = row.querySelectorAll('span[data-day][data-room-id]');
                        spans.forEach(span => {
                            const day = span.getAttribute('data-day');
                            const roomId = span.getAttribute('data-room-id');
                            const td = span.closest('td');
                            if (td) {
                                const divs = td.querySelectorAll('div');
                                const name = divs[0] ? divs[0].textContent.trim() : '';
                                const time = divs[1] ? divs[1].textContent.trim() : '';
                                if (name && day) {
                                    const timeParts = time.match(/(\\d{1,2}:\\d{2})[〜~\\-](\\d{1,2}:\\d{2})/);
                                    results.push({
                                        date: day,
                                        name: name,
                                        start: timeParts ? timeParts[1] : '',
                                        end: timeParts ? timeParts[2] : '',
                                        time_raw: time,
                                        room_id: roomId,
                                    });
                                }
                            }
                        });
                    });
                });
                return results;
            }""")

            # キャスト名一覧を取得
            cast_names = await page.evaluate("""() => {
                const names = new Set();
                document.querySelectorAll('.parts-cast-table td div:first-child').forEach(div => {
                    const name = div.textContent.trim();
                    if (name && name.length < 20) names.add(name);
                });
                return Array.from(names);
            }""")

            return {
                "shifts": shifts,
                "cast_names": cast_names,
            }

        except Exception as e:
            logger.error(f"シフト取得エラー: {e}")
            return {"error": str(e)}

    async def get_cast_list(self) -> list:
        """キャスト一覧を取得する"""
        if not await self._ensure_login():
            return []

        try:
            page = self._page
            await page.goto(f"{BASE_URL}/cast", wait_until="networkidle", timeout=30000)
            await page.wait_for_timeout(1500)

            casts = await page.evaluate("""() => {
                const results = [];
                const rows = document.querySelectorAll('tr');
                rows.forEach(row => {
                    const links = row.querySelectorAll('a[href*="/cast/"]');
                    links.forEach(link => {
                        const name = link.textContent.trim();
                        if (name && !name.includes('編集')) {
                            const rowText = row.textContent;
                            const status = rowText.includes('掲載中') ? '掲載中' : '未掲載';
                            results.push({name, status});
                        }
                    });
                });
                return results;
            }""")

            return casts

        except Exception as e:
            logger.error(f"キャスト一覧取得エラー: {e}")
            return []

    async def get_room_list(self) -> list:
        """ルーム一覧を取得する"""
        if not await self._ensure_login():
            return []

        try:
            page = self._page
            await page.goto(f"{BASE_URL}/room", wait_until="networkidle", timeout=30000)
            await page.wait_for_timeout(1500)

            rooms = await page.evaluate("""() => {
                const results = [];
                const rows = document.querySelectorAll('tr');
                rows.forEach(row => {
                    const link = row.querySelector('a[href*="/room/view"]');
                    const sortInput = row.querySelector('input[name^="sort["]');
                    if (link && sortInput) {
                        const name = link.textContent.trim().split(/\\s+/)[0];
                        const id = sortInput.value;
                        results.push({id, name});
                    }
                });
                return results;
            }""")

            return rooms

        except Exception as e:
            logger.error(f"ルーム一覧取得エラー: {e}")
            return []

    # ─── シフト登録 ─────────────────────────────────────────

    async def register_shift(
        self,
        cast_name: str,
        date_str: str,
        start_time: str,
        end_time: str,
        room_name: Optional[str] = None,
    ) -> dict:
        """
        キャスカンにシフトを登録する。

        Args:
            cast_name: セラピスト名（例: "りおん"）
            date_str: 日付 "YYYY-MM-DD"
            start_time: 開始時刻 "HH:MM"（例: "14:00"）
            end_time: 終了時刻 "HH:MM"（例: "23:00"）
            room_name: ルーム名（Noneなら自動選択）

        Returns:
            {"success": bool, "message": str}
        """
        if not await self._ensure_login():
            return {"success": False, "message": "ログインに失敗しました"}

        try:
            page = self._page

            # シフトページへ移動
            await page.goto(
                f"{BASE_URL}/shift/view?start_day={date_str}",
                wait_until="networkidle",
                timeout=30000,
            )
            await page.wait_for_timeout(2000)

            # 該当日のセルをクリックしてシフト登録ダイアログを開く
            # シフト表の該当日の空きセルを探す
            cell_clicked = await page.evaluate(f"""(params) => {{
                const targetDate = params.date;
                // 日付ヘッダーから列インデックスを特定
                const headers = document.querySelectorAll('th, .shift-date-header, [data-date]');
                let targetCol = -1;

                // data-day属性を持つ要素を探す
                const cells = document.querySelectorAll('td[data-date="' + targetDate + '"], ' +
                    '.shift-cell[data-date="' + targetDate + '"]');
                if (cells.length > 0) {{
                    cells[0].click();
                    return true;
                }}

                // フォールバック: 空のセルを探してクリック
                const allCells = document.querySelectorAll('.parts-cast-table td, .shift-table td');
                for (const cell of allCells) {{
                    if (cell.textContent.trim() === '' || cell.querySelector('.shift-add')) {{
                        const span = cell.querySelector('span[data-day="' + targetDate + '"]');
                        if (span) {{
                            cell.click();
                            return true;
                        }}
                    }}
                }}

                return false;
            }}""", {"date": date_str})

            await page.wait_for_timeout(1500)

            # シフト登録フォームが表示されたか確認
            # モーダルまたはフォームを探す
            modal_visible = await page.locator('.modal, .dialog, [role="dialog"], .shift-form, #shift-form').count()

            if modal_visible == 0:
                # 直接シフト登録URLにアクセスする方法を試す
                await page.goto(
                    f"{BASE_URL}/shift/add?day={date_str}",
                    wait_until="networkidle",
                    timeout=30000,
                )
                await page.wait_for_timeout(2000)

            # フォームに入力
            # キャスト選択
            cast_select = page.locator('select[name*="cast"], select[name*="therapist"], select#cast_id')
            if await cast_select.count() > 0:
                # セレクトボックスからキャスト名に一致するオプションを選択
                options = await cast_select.first.locator("option").all()
                for opt in options:
                    text = await opt.text_content()
                    if cast_name in text:
                        value = await opt.get_attribute("value")
                        await cast_select.first.select_option(value=value)
                        break

            # 日付入力
            date_input = page.locator('input[name*="day"], input[name*="date"], input[type="date"]')
            if await date_input.count() > 0:
                await date_input.first.fill(date_str)

            # 開始時刻
            start_selects = page.locator('select[name*="start"], select[name*="from"]')
            start_inputs = page.locator('input[name*="start_time"], input[name*="from_time"]')

            if await start_selects.count() > 0:
                # 時間と分を分けて選択する場合
                hour_select = page.locator('select[name*="start_hour"], select[name*="from_h"]')
                min_select = page.locator('select[name*="start_min"], select[name*="from_m"]')
                h, m = start_time.split(":")

                if await hour_select.count() > 0 and await min_select.count() > 0:
                    await hour_select.first.select_option(value=h.lstrip("0") or "0")
                    await min_select.first.select_option(value=m.lstrip("0") or "0")
                else:
                    await start_selects.first.select_option(label=start_time)
            elif await start_inputs.count() > 0:
                await start_inputs.first.fill(start_time)

            # 終了時刻
            end_selects = page.locator('select[name*="end"], select[name*="to"]')
            end_inputs = page.locator('input[name*="end_time"], input[name*="to_time"]')

            if await end_selects.count() > 0:
                hour_select = page.locator('select[name*="end_hour"], select[name*="to_h"]')
                min_select = page.locator('select[name*="end_min"], select[name*="to_m"]')
                h, m = end_time.split(":")

                if await hour_select.count() > 0 and await min_select.count() > 0:
                    await hour_select.first.select_option(value=h.lstrip("0") or "0")
                    await min_select.first.select_option(value=m.lstrip("0") or "0")
                else:
                    await end_selects.first.select_option(label=end_time)
            elif await end_inputs.count() > 0:
                await end_inputs.first.fill(end_time)

            # ルーム選択
            if room_name:
                room_select = page.locator('select[name*="room"]')
                if await room_select.count() > 0:
                    options = await room_select.first.locator("option").all()
                    for opt in options:
                        text = await opt.text_content()
                        if room_name in text:
                            value = await opt.get_attribute("value")
                            await room_select.first.select_option(value=value)
                            break

            await page.wait_for_timeout(500)

            # 保存ボタンをクリック
            save_btn = page.locator(
                'button:has-text("保存"), button:has-text("登録"), '
                'input[type="submit"][value*="保存"], input[type="submit"][value*="登録"], '
                '.btn-primary, .btn-success'
            )
            if await save_btn.count() > 0:
                await save_btn.first.click()
                await page.wait_for_timeout(3000)

                # 成功判定
                error_msg = await page.locator('.alert-danger, .error-message, .text-danger').count()
                if error_msg > 0:
                    error_text = await page.locator('.alert-danger, .error-message, .text-danger').first.text_content()
                    return {"success": False, "message": f"登録エラー: {error_text.strip()}"}

                return {
                    "success": True,
                    "message": f"シフト登録完了: {cast_name} {date_str} {start_time}〜{end_time}",
                }
            else:
                return {"success": False, "message": "保存ボタンが見つかりません"}

        except Exception as e:
            logger.error(f"シフト登録エラー: {e}")
            return {"success": False, "message": f"エラー: {str(e)}"}

    async def delete_shift(
        self,
        cast_name: str,
        date_str: str,
    ) -> dict:
        """
        キャスカンのシフトを削除する。

        Args:
            cast_name: セラピスト名
            date_str: 日付 "YYYY-MM-DD"

        Returns:
            {"success": bool, "message": str}
        """
        if not await self._ensure_login():
            return {"success": False, "message": "ログインに失敗しました"}

        try:
            page = self._page
            await page.goto(
                f"{BASE_URL}/shift/view?start_day={date_str}",
                wait_until="networkidle",
                timeout=30000,
            )
            await page.wait_for_timeout(2000)

            # 該当キャスト・日付のシフトセルを探してクリック
            clicked = await page.evaluate(f"""(params) => {{
                const spans = document.querySelectorAll('span[data-day="{date_str}"]');
                for (const span of spans) {{
                    const td = span.closest('td');
                    if (td) {{
                        const nameDiv = td.querySelector('div');
                        if (nameDiv && nameDiv.textContent.trim().includes('{cast_name}')) {{
                            td.click();
                            return true;
                        }}
                    }}
                }}
                return false;
            }}""", {"date": date_str, "name": cast_name})

            if not clicked:
                return {"success": False, "message": f"{cast_name}の{date_str}のシフトが見つかりません"}

            await page.wait_for_timeout(1500)

            # 削除ボタンを探してクリック
            delete_btn = page.locator(
                'button:has-text("削除"), a:has-text("削除"), '
                '.btn-danger, [data-action="delete"]'
            )
            if await delete_btn.count() > 0:
                await delete_btn.first.click()
                await page.wait_for_timeout(1000)

                # 確認ダイアログがあれば承認
                confirm_btn = page.locator(
                    'button:has-text("OK"), button:has-text("はい"), '
                    'button:has-text("確認"), .btn-primary'
                )
                if await confirm_btn.count() > 0:
                    await confirm_btn.first.click()

                await page.wait_for_timeout(2000)
                return {
                    "success": True,
                    "message": f"シフト削除完了: {cast_name} {date_str}",
                }
            else:
                return {"success": False, "message": "削除ボタンが見つかりません"}

        except Exception as e:
            logger.error(f"シフト削除エラー: {e}")
            return {"success": False, "message": f"エラー: {str(e)}"}

    async def get_today_schedule(self) -> dict:
        """今日のスケジュール（出勤中セラピスト一覧）を取得する"""
        today = datetime.now().strftime("%Y-%m-%d")
        return await self.get_shift_page(today)

    async def take_screenshot(self, path: str = "/tmp/caskan_screenshot.png") -> str:
        """デバッグ用スクリーンショットを撮る"""
        try:
            await self._ensure_browser()
            await self._page.screenshot(path=path, full_page=True)
            return path
        except Exception as e:
            logger.error(f"スクリーンショットエラー: {e}")
            return ""

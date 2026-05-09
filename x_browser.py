import asyncio
import logging
from playwright.async_api import async_playwright

logger = logging.getLogger(__name__)

class XBrowser:
    def __init__(self, email, username, password):
        self.email = email
        self.username = username
        self.password = password
        self._browser = None
        self._context = None
        self._page = None
        self._logged_in = False

    async def _ensure_browser(self):
        if self._browser is None:
            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(
                headless=True,
                args=['--no-sandbox', '--disable-setuid-sandbox', '--window-size=1280,800']
            )
            self._context = await self._browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                viewport={'width': 1280, 'height': 800}
            )
            self._page = await self._context.new_page()

    async def login(self) -> bool:
        try:
            await self._ensure_browser()
            page = self._page
            logger.info("Navigating to X login...")
            await page.goto("https://x.com/i/flow/login")
            
            # Step 1: Email/Username
            await page.wait_for_selector('input[autocomplete="username"]')
            await page.fill('input[autocomplete="username"]', self.email)
            await page.click('button:has-text("Next")')
            
            # Step 2: Sometime it asks for username if suspicious
            try:
                await page.wait_for_selector('input[data-testid="ocfEnterTextTextInput"]', timeout=3000)
                await page.fill('input[data-testid="ocfEnterTextTextInput"]', self.username)
                await page.click('button:has-text("Next")')
            except:
                pass
                
            # Step 3: Password
            await page.wait_for_selector('input[name="password"]')
            await page.fill('input[name="password"]', self.password)
            await page.click('button[data-testid="LoginForm_Login_Button"]')
            
            await page.wait_for_url("https://x.com/home", timeout=15000)
            self._logged_in = True
            logger.info("X Login successful")
            return True
        except Exception as e:
            logger.error(f"X Login Error: {e}")
            await self._page.screenshot(path="/root/.openclaw/workspace/x_login_error.png")
            return False

    async def post_tweet(self, text: str, image_path: str = None) -> dict:
        if not self._logged_in:
            success = await self.login()
            if not success:
                return {"success": False, "message": "Failed to login"}
                
        try:
            page = self._page
            await page.goto("https://x.com/home")
            await page.wait_for_selector('div[data-testid="tweetTextarea_0"]')
            
            await page.click('div[data-testid="tweetTextarea_0"]')
            await page.fill('div[data-testid="tweetTextarea_0"]', text)
            
            if image_path:
                try:
                    async with page.expect_file_chooser() as fc_info:
                        await page.click('div[aria-label="Add photos or video"]')
                    file_chooser = await fc_info.value
                    await file_chooser.set_files(image_path)
                    await page.wait_for_timeout(2000)
                except Exception as e:
                    logger.warning(f"Failed to attach image to X: {e}")
            
            await page.click('button[data-testid="tweetButtonInline"]')
            # wait for toast or some indication
            await page.wait_for_timeout(3000)
            
            logger.info("X Post successful")
            return {"success": True}
        except Exception as e:
            logger.error(f"X Post Error: {e}")
            return {"success": False, "message": str(e)}

    async def close(self):
        if self._browser:
            await self._browser.close()
        if hasattr(self, "_playwright"):
            await self._playwright.stop()

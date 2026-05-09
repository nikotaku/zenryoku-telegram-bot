import asyncio
import logging
from playwright.async_api import async_playwright

logger = logging.getLogger(__name__)

class ZeroTwoBrowser:
    def __init__(self):
        self._browser = None
        self._context = None
        self._page = None
        self._logged_in = False
        
    async def _ensure_browser(self):
        if self._browser is None:
            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(
                headless=True,
                args=['--no-sandbox', '--disable-setuid-sandbox']
            )
            self._context = await self._browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
            self._page = await self._context.new_page()

    async def login(self) -> bool:
        try:
            await self._ensure_browser()
            page = self._page
            await page.goto("https://m-sns.net/shop/login/")
            
            await page.fill('input[name="email"]', "chelsy.ox.0913@gmail.com")
            await page.fill('input[name="password"]', "zenryoku0913")
            
            await asyncio.gather(
                page.click('button[type="submit"]'),
                page.wait_for_load_state("networkidle")
            )
            
            if "dashboard" in page.url:
                self._logged_in = True
                logger.info("ZeroTwo Login successful")
                return True
            else:
                logger.error("ZeroTwo Login failed")
                return False
        except Exception as e:
            logger.error(f"ZeroTwo Login Error: {e}")
            return False

    async def post_news(self, content: str, image_path: str = None) -> dict:
        if not self._logged_in:
            success = await self.login()
            if not success:
                return {"success": False, "message": "Failed to login"}
                
        try:
            page = self._page
            await page.goto("https://m-sns.net/shop/post/create/", wait_until="networkidle")
            
            await page.fill('textarea[name="content"]', content)
            
            if image_path:
                try:
                    async with page.expect_file_chooser() as fc_info:
                        await page.click('div#mainDropzone')
                    file_chooser = await fc_info.value
                    await file_chooser.set_files(image_path)
                    await page.wait_for_timeout(1000)
                except Exception as e:
                    logger.warning(f"Failed to attach image to ZeroTwo: {e}")
            
            await asyncio.gather(
                page.click('button[type="submit"]'),
                page.wait_for_load_state("networkidle")
            )
            
            logger.info("ZeroTwo Post successful")
            return {"success": True}
        except Exception as e:
            logger.error(f"ZeroTwo Post Error: {e}")
            return {"success": False, "message": str(e)}
            
    async def close(self):
        if self._browser:
            await self._browser.close()
        if hasattr(self, "_playwright"):
            await self._playwright.stop()

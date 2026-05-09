import asyncio
import sys
import os
from dotenv import load_dotenv
sys.path.append('/root/.openclaw/workspace/zenryoku-telegram-bot')
load_dotenv('/root/.openclaw/workspace/zenryoku-telegram-bot/.env')
from caskan_browser import CaskanBrowser

async def test():
    print("Testing Caskan Login...")
    browser = CaskanBrowser()
    try:
        success = await browser.login()
        print(f"Login success: {success}")
        if success:
            page = browser._page
            await page.goto("https://my.caskan.jp/", wait_until="domcontentloaded")
            title = await page.title()
            print(f"Page title: {title}")
    except Exception as e:
        print(f"Error: {e}")
    finally:
        await browser.close()

if __name__ == '__main__':
    asyncio.run(test())

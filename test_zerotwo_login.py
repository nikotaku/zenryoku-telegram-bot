import asyncio
import logging
from playwright.async_api import async_playwright

logging.basicConfig(level=logging.INFO)

async def test_zerotwo():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=['--no-sandbox', '--disable-setuid-sandbox'])
        page = await browser.new_page()
        
        print("Navigating to login...")
        await page.goto("https://m-sns.net/shop/login/")
        
        print("Filling credentials...")
        await page.fill('input[name="email"]', "chelsy.ox.0913@gmail.com")
        await page.fill('input[name="password"]', "zenryoku0913")
        
        print("Submitting...")
        await asyncio.gather(
            page.click('button[type="submit"]'),
            page.wait_for_load_state("networkidle")
        )
        
        title = await page.title()
        url = page.url
        print(f"Logged in! Title: {title}, URL: {url}")
        
        print("Taking screenshot...")
        await page.screenshot(path="/root/.openclaw/workspace/zerotwo_dashboard.png")
        
        # Navigate to post create
        await page.goto("https://m-sns.net/shop/post/create/")
        await page.screenshot(path="/root/.openclaw/workspace/zerotwo_post_form.png")
        
        print("Checking form fields...")
        form_html = await page.evaluate("document.querySelector('form').innerHTML")
        with open("/root/.openclaw/workspace/zerotwo_form.txt", "w") as f:
            f.write(form_html)
            
        await browser.close()

if __name__ == "__main__":
    asyncio.run(test_zerotwo())

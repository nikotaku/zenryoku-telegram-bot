"""
一斉投稿テスト: エスたま + 02
"""
import asyncio
import logging
import os
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

TEST_TITLE = "テスト投稿"
TEST_BODY = "これはシステムテストです。自動投稿の確認のために送信しています。"

async def test_estama():
    print("\n=== エスたま テスト ===")
    from estama_client import EstamaClient
    client = EstamaClient()
    result = client.post_diary(TEST_TITLE, TEST_BODY)
    print(f"結果: {result}")
    return result

async def test_zerotwo():
    print("\n=== 02 (ZeroTwo) テスト ===")
    from zerotwo_browser import ZeroTwoBrowser
    browser = ZeroTwoBrowser()
    try:
        result = await browser.post_news(f"{TEST_TITLE}\n\n{TEST_BODY}")
        print(f"結果: {result}")
        return result
    finally:
        await browser.close()

async def main():
    print("一斉投稿テスト開始")

    # エスたまテスト
    try:
        estama_result = await asyncio.get_event_loop().run_in_executor(None, lambda: asyncio.run(test_estama_sync()))
    except Exception as e:
        print(f"エスたまエラー: {e}")

    # 02テスト
    try:
        zt_result = await test_zerotwo()
    except Exception as e:
        print(f"02エラー: {e}")

def test_estama_sync():
    from estama_client import EstamaClient
    client = EstamaClient()
    result = client.post_diary(TEST_TITLE, TEST_BODY)
    return result

async def run():
    print("=== エスたま テスト ===")
    try:
        loop = asyncio.get_event_loop()
        estama_result = await loop.run_in_executor(None, test_estama_sync)
        print(f"エスたま結果: {estama_result}")
    except Exception as e:
        print(f"エスたまエラー: {e}")

    print("\n=== 02 テスト ===")
    try:
        from zerotwo_browser import ZeroTwoBrowser
        browser = ZeroTwoBrowser()
        zt_result = await browser.post_news(f"{TEST_TITLE}\n\n{TEST_BODY}")
        print(f"02結果: {zt_result}")
        await browser.close()
    except Exception as e:
        print(f"02エラー: {e}")

if __name__ == "__main__":
    asyncio.run(run())

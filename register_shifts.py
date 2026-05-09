import asyncio
import sys
import logging
from dotenv import load_dotenv
sys.path.append('/root/.openclaw/workspace/zenryoku-telegram-bot')
load_dotenv('/root/.openclaw/workspace/zenryoku-telegram-bot/.env')
from caskan_browser import CaskanBrowser

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def register_shifts():
    browser = CaskanBrowser()
    try:
        success = await browser.login()
        if not success:
            logger.error("Caskan Login failed")
            return
            
        shifts = [
            ("2026-05-08", "17:30", "25:00"),
            ("2026-05-09", "15:00", "25:00"),
            ("2026-05-10", "14:00", "22:00"),
            ("2026-05-12", "13:30", "22:00"),
            ("2026-05-13", "13:30", "22:00"),
            ("2026-05-16", "13:00", "25:00"),
            ("2026-05-17", "14:00", "22:00"),
        ]
        
        cast_name = "りな"
        
        for date_str, start, end in shifts:
            logger.info(f"Registering shift: {cast_name} on {date_str} from {start} to {end}")
            result = await browser.register_shift(
                cast_name=cast_name,
                date_str=date_str,
                start_time=start,
                end_time=end,
                room_name="インルーム" # 必須項目のためデフォルト値を指定
            )
            logger.info(f"Result: {result}")
            
    except Exception as e:
        logger.error(f"Error: {e}")
    finally:
        await browser.close()

if __name__ == "__main__":
    asyncio.run(register_shifts())

"""
りおん (@rion_zenryoku) X自動運用システム

必要な環境変数:
  RION_X_API_KEY          - X API Key (Consumer Key)
  RION_X_API_SECRET       - X API Secret (Consumer Secret)
  RION_X_ACCESS_TOKEN     - Access Token
  RION_X_ACCESS_SECRET    - Access Token Secret

投稿スケジュール (JST):
  08:30  おはよう
  13:00  美容 / ピラティス / 旅行 ランダム
  17:30  出勤告知
  23:30  おやすみ / お礼 ランダム

自動リプ:
  30分おきに仙台関連キーワードを検索 → 未返信ツイートへ返信
"""

import os
import asyncio
import logging
import json
import random
from datetime import datetime, timedelta
from pathlib import Path

import tweepy
import pytz

import rion_config
from rion_persona import (
    generate_post,
    generate_reply,
    generate_post_from_article,
    load_articles,
    load_rt_accounts,
    SENDAI_CUSTOMER_KEYWORDS,
)

logger = logging.getLogger(__name__)
JST = pytz.timezone("Asia/Tokyo")

# 既返信済みツイートIDを保存するファイル
REPLIED_IDS_FILE = Path("rion_replied_ids.json")


def _get_client() -> tweepy.Client | None:
    # 設定ファイル優先、なければ環境変数
    api_key = rion_config.get_credential("RION_X_API_KEY")
    api_secret = rion_config.get_credential("RION_X_API_SECRET")
    access_token = rion_config.get_credential("RION_X_ACCESS_TOKEN")
    access_secret = rion_config.get_credential("RION_X_ACCESS_SECRET")

    if not all([api_key, api_secret, access_token, access_secret]):
        logger.error("X API 認証情報が不足しています。環境変数を確認してください。")
        return None

    return tweepy.Client(
        consumer_key=api_key,
        consumer_secret=api_secret,
        access_token=access_token,
        access_token_secret=access_secret,
        wait_on_rate_limit=True,
    )


def _load_replied_ids() -> set:
    if REPLIED_IDS_FILE.exists():
        try:
            data = json.loads(REPLIED_IDS_FILE.read_text())
            # 48時間以内のIDだけ保持
            cutoff = (datetime.now() - timedelta(hours=48)).timestamp()
            return {str(item["id"]) for item in data if item.get("ts", 0) > cutoff}
        except Exception:
            pass
    return set()


def _save_replied_id(tweet_id: str):
    ids = []
    if REPLIED_IDS_FILE.exists():
        try:
            ids = json.loads(REPLIED_IDS_FILE.read_text())
        except Exception:
            pass
    ids.append({"id": str(tweet_id), "ts": datetime.now().timestamp()})
    # 最大1000件まで
    ids = ids[-1000:]
    REPLIED_IDS_FILE.write_text(json.dumps(ids, ensure_ascii=False))


# 既RT済みツイートIDを保存するファイル
RETWEETED_IDS_FILE = Path("rion_retweeted_ids.json")


def _load_retweeted_ids() -> set:
    if RETWEETED_IDS_FILE.exists():
        try:
            return set(json.loads(RETWEETED_IDS_FILE.read_text()))
        except Exception:
            pass
    return set()


def _save_retweeted_ids(ids: set):
    # 最大2000件まで保持
    RETWEETED_IDS_FILE.write_text(json.dumps(list(ids)[-2000:], ensure_ascii=False))


def retweet_from_accounts(max_per_account: int = 1) -> int:
    """RT対象アカウントの最新ツイートを自動RTする。RTした件数を返す。"""
    accounts = load_rt_accounts()
    if not accounts:
        return 0
    client = _get_client()
    if not client:
        return 0

    # 自分のユーザーIDを取得（RTに必要）
    try:
        me = client.get_me()
        my_id = me.data.id
    except Exception as e:
        logger.error(f"get_me エラー: {e}")
        return 0

    done = _load_retweeted_ids()
    rt_count = 0

    for username in accounts:
        try:
            user = client.get_user(username=username)
            if not user.data:
                continue
            tweets = client.get_users_tweets(
                user.data.id,
                max_results=5,
                exclude=["retweets", "replies"],
                tweet_fields=["created_at"],
            )
            if not tweets.data:
                continue
            posted = 0
            for tw in tweets.data:  # 新しい順
                if posted >= max_per_account:
                    break
                tid = str(tw.id)
                if tid in done:
                    continue
                try:
                    client.retweet(tid)
                    done.add(tid)
                    rt_count += 1
                    posted += 1
                    logger.info(f"RT: @{username} | {tid}")
                except Exception as e:
                    logger.error(f"RTエラー @{username} {tid}: {e}")
                    done.add(tid)  # 失敗（既RT等）も記録して再試行を防ぐ
        except Exception as e:
            logger.error(f"アカウント取得エラー @{username}: {e}")

    _save_retweeted_ids(done)
    return rt_count


def post_tweet(text: str) -> tuple[bool, str]:
    """ツイートを投稿する。(success, error_message) を返す。"""
    client = _get_client()
    if not client:
        return False, "X API 認証情報が不足しています（RION_X_* 環境変数を確認）"
    try:
        resp = client.create_tweet(text=text)
        tweet_id = resp.data["id"]
        logger.info(f"投稿成功: {tweet_id} | {text[:30]}...")
        return True, ""
    except Exception as e:
        logger.error(f"投稿エラー: {e}")
        return False, str(e)


def search_and_reply(max_replies: int = 5) -> int:
    """
    仙台関連キーワードでツイートを検索し、未返信のものへ自動リプする。
    1回の実行で max_replies 件まで返信。
    """
    client = _get_client()
    if not client:
        return 0

    replied_ids = _load_replied_ids()
    reply_count = 0

    for keyword in SENDAI_CUSTOMER_KEYWORDS:
        if reply_count >= max_replies:
            break
        try:
            # 日本語ツイート・リプライ除外・最近1時間以内
            query = f"{keyword} lang:ja -is:retweet -is:reply"
            results = client.search_recent_tweets(
                query=query,
                max_results=10,
                tweet_fields=["author_id", "text", "created_at"],
                expansions=["author_id"],
                user_fields=["username"],
            )
            if not results.data:
                continue

            # ユーザー情報マッピング
            users = {}
            if results.includes and results.includes.get("users"):
                for u in results.includes["users"]:
                    users[u.id] = u.username

            for tweet in results.data:
                if reply_count >= max_replies:
                    break
                tweet_id = str(tweet.id)
                if tweet_id in replied_ids:
                    continue

                username = users.get(tweet.author_id, "")
                if not username:
                    continue

                reply_text = generate_reply(tweet.text, username)
                if not reply_text:
                    continue

                try:
                    client.create_tweet(
                        text=reply_text,
                        in_reply_to_tweet_id=tweet.id,
                    )
                    _save_replied_id(tweet_id)
                    replied_ids.add(tweet_id)
                    reply_count += 1
                    logger.info(f"返信: @{username} | {reply_text[:30]}...")
                except Exception as e:
                    logger.error(f"返信エラー: {e}")

        except Exception as e:
            logger.error(f"検索エラー ({keyword}): {e}")

    return reply_count


# ──────────────────────────────────────────
# スケジューラー
# ──────────────────────────────────────────
SCHEDULE = [
    {"hour": 8,  "minute": 30, "type": None},  # 朝（内容ランダム）
    {"hour": 13, "minute": 0,  "type": None},  # 昼（内容ランダム）
    {"hour": 17, "minute": 30, "type": None},  # 夕（内容ランダム）
    {"hour": 23, "minute": 30, "type": None},  # 夜（内容ランダム）
]

DAYTIME_TYPES = ["beauty", "pilates", "travel_power", "daily"]
NIGHT_TYPES   = ["night", "thanks"]


def _pick_post_type(slot: dict) -> str:
    if slot["type"]:
        return slot["type"]
    if slot["hour"] < 20:
        import random
        return random.choice(DAYTIME_TYPES)
    else:
        import random
        return random.choice(NIGHT_TYPES)


async def run_scheduler():
    """メインスケジューラーループ。bot.pyから asyncio.create_task で起動する。"""
    logger.info("りおん自動投稿スケジューラー起動")
    posted_today: set[int] = set()  # 今日投稿済みスロットindex

    while True:
        now = datetime.now(JST)

        # 日付変わりでリセット
        if now.hour == 0 and now.minute < 2:
            posted_today.clear()

        # 自動運用が無効なら何もせず待機（枠組みは残す）
        if not rion_config.is_enabled():
            await asyncio.sleep(60)
            continue

        for i, slot in enumerate(SCHEDULE):
            if i in posted_today:
                continue
            if now.hour == slot["hour"] and now.minute >= slot["minute"]:
                post_type = _pick_post_type(slot)
                # 美容系スロットは記事があれば記事ベースで生成
                articles = load_articles()
                if post_type in ("beauty", "daily") and articles:
                    article = random.choice(articles)
                    text = generate_post_from_article(article)
                else:
                    text = generate_post(post_type)
                if text:
                    success, err = post_tweet(text)
                    if success:
                        posted_today.add(i)
                        logger.info(f"スロット{i}投稿完了: {post_type}")
                    else:
                        logger.error(f"スロット{i}投稿失敗: {err}")

        # 30分おきに自動リプ（生成APIキーがある時のみ。無いと返信文を作れず検索枠が無駄になる）
        if now.minute % 30 == 0 and os.environ.get("ANTHROPIC_API_KEY"):
            count = search_and_reply(max_replies=3)
            if count:
                logger.info(f"自動リプ: {count}件")

        # 1時間おきに対象アカウントの最新を自動RT
        if now.minute == 0:
            rt = retweet_from_accounts(max_per_account=1)
            if rt:
                logger.info(f"自動RT: {rt}件")

        await asyncio.sleep(60)  # 1分ごとにチェック


if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_scheduler())

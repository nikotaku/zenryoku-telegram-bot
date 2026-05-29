"""
りおん (@rion_zenryoku) アカウントの投稿済みツイートを全削除するワンオフスクリプト。

使い方:
  python delete_all_tweets.py          # ドライラン（件数を数えるだけ・削除しない）
  python delete_all_tweets.py --yes     # 実際に削除する

※ X APIのタイムラインは直近約3200件まで取得可能。
※ delete_tweet はレート制限あり（wait_on_rate_limit=True で自動待機）。
"""
import os
import sys
import time
from dotenv import load_dotenv
import tweepy

load_dotenv()


def _client():
    return tweepy.Client(
        consumer_key=os.environ["RION_X_API_KEY"],
        consumer_secret=os.environ["RION_X_API_SECRET"],
        access_token=os.environ["RION_X_ACCESS_TOKEN"],
        access_token_secret=os.environ["RION_X_ACCESS_SECRET"],
        wait_on_rate_limit=True,
    )


def fetch_all_tweet_ids(client, my_id) -> list[str]:
    ids: list[str] = []
    pagination_token = None
    while True:
        resp = client.get_users_tweets(
            my_id,
            max_results=100,
            pagination_token=pagination_token,
        )
        if resp.data:
            ids.extend(str(t.id) for t in resp.data)
        meta = resp.meta or {}
        pagination_token = meta.get("next_token")
        if not pagination_token:
            break
    return ids


def main():
    execute = "--yes" in sys.argv
    client = _client()
    me = client.get_me()
    my_id = me.data.id
    username = me.data.username
    print(f"対象アカウント: @{username} (id={my_id})")

    ids = fetch_all_tweet_ids(client, my_id)
    print(f"取得できたツイート: {len(ids)} 件")

    if not ids:
        print("削除対象なし。")
        return

    if not execute:
        print("\n[ドライラン] 削除はしていません。実行するには --yes を付けてください。")
        return

    print(f"\n削除を開始します（{len(ids)}件）...")
    deleted = 0
    for tid in ids:
        try:
            client.delete_tweet(tid)
            deleted += 1
            if deleted % 20 == 0:
                print(f"  {deleted}/{len(ids)} 件削除")
            time.sleep(0.3)
        except Exception as e:
            print(f"  削除失敗 {tid}: {e}")
    print(f"完了: {deleted}/{len(ids)} 件削除しました。")


if __name__ == "__main__":
    main()

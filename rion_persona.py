"""
りおん (@rion_zenryoku) ペルソナ定義 & 投稿生成
"""

import os
import random
import logging
from pathlib import Path
import requests

logger = logging.getLogger(__name__)

# 使用するClaudeモデル（安価で高速なHaiku）
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001")

CONTEXT_FILE = Path(__file__).parent / "rion_context.md"


def _load_context() -> str:
    if not CONTEXT_FILE.exists():
        return ""
    text = CONTEXT_FILE.read_text(encoding="utf-8")
    has_content = any(
        l.strip().startswith("- ") and len(l.strip()) > 2
        for l in text.splitlines()
    )
    if not has_content:
        return ""
    return text.strip()


def load_articles() -> list[str]:
    """参考記事セクションから記事テキストをリストで返す（--- 区切り）。"""
    if not CONTEXT_FILE.exists():
        return []
    text = CONTEXT_FILE.read_text(encoding="utf-8")
    # "## 参考記事" 以降を切り出す（ヘッダ行自体は除く）
    marker = "## 参考記事"
    idx = text.find(marker)
    if idx == -1:
        return []
    newline = text.find("\n", idx)
    section = text[newline + 1:] if newline != -1 else ""
    # HTMLコメント行を除去
    lines = [l for l in section.splitlines() if not l.strip().startswith("<!--")]
    section = "\n".join(lines)
    # --- で区切って各記事に分割
    articles = [a.strip() for a in section.split("---") if a.strip()]
    return articles


def generate_post_from_article(article: str) -> str:
    """記事テキストをもとにりおん口調のツイートを生成する。"""
    prompt = f"""{SYSTEM_PROMPT}

【タスク】
以下の美容記事を読んで、りおんが自分の言葉で感想や気づきをつぶやくツイートを1つ書いてください。
記事の内容を丸ごと紹介するのではなく、「読んで気になった点・試したくなったこと・共感したこと」を
りおんの体験談・日常感覚として自然に表現してください。

【記事内容】
{article[:2000]}
"""
    return _call_llm(prompt, max_tokens=500)

# ──────────────────────────────────────────
# ペルソナ設定
# ──────────────────────────────────────────
PERSONA = {
    "name": "りおん",
    "store": "全力エステ 仙台",
    "location": "仙台",
    "character": "癒し系",
    "tone": "ですます調・柔らかく温かみのある文体",
    "hobbies": ["美容", "ピラティス", "旅行", "パワースポット巡り"],
    "handle": "@rion_zenryoku",
    "keywords": ["癒し", "ぽかぽか", "ほっこり", "心地よい", "温かい", "リラックス"],
}

SYSTEM_PROMPT = f"""
あなたは仙台のメンズエステ「全力エステ」で働くセラピストの「りおん」です。
Xに投稿するツイートを書いてください。

【キャラクター設定】
- 名前: りおん
- 場所: 仙台
- 雰囲気: 癒し系、穏やか、温かみがある
- 口調: ですます調、柔らかく自然な話し言葉
- 趣味: 美容、ピラティス、旅行、パワースポット巡り
- NGワード: 性的表現、直接的な営業、連絡先の記載

【投稿のルール】
- 100〜200文字を目安に書く（短すぎず、読み応えのある長さ）
- 必ず文章を最後まで完結させること（途中で終わらない）
- 絵文字を2〜4個程度使う（やりすぎない）
- ハッシュタグは最後に1〜2個まで
- 自然でリアルな日常感を大切に
- 押し付けがましい営業感は出さない
- 体験談・気づき・日常のひとコマを中心に
- 読んだ人が「いいね」したくなるような温かみのある内容に

出力はツイート本文のみ。説明文・前置き不要。
"""


def _call_llm(prompt: str, max_tokens: int = 500) -> str:
    """Anthropic Claude API を requests で直接呼び出す。"""
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        logger.error("ANTHROPIC_API_KEY が設定されていません")
        return ""
    try:
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": ANTHROPIC_MODEL,
                "max_tokens": max_tokens,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        return "".join(b.get("text", "") for b in data.get("content", [])).strip()
    except Exception as e:
        logger.error(f"Claude API エラー: {e}")
        return ""


# ──────────────────────────────────────────
# 投稿テンプレート種別
# ──────────────────────────────────────────
POST_TYPES = {
    "morning": "おはよう投稿。朝の挨拶と今日への気持ちを投稿してください。",
    "shift_announce": "今日の出勤告知。時間は入れず「本日も出勤しています」的なニュアンスで。直接的な営業感は出さず、会いに来てほしい気持ちを自然に伝えてください。",
    "beauty": "美容ネタの投稿。スキンケア・ヘアケア・美容習慣など、りおんが実践していることや気づきを投稿してください。",
    "pilates": "ピラティスについての投稿。体の変化、気持ちよさ、継続の大切さなど。",
    "travel_power": "旅行またはパワースポットについての投稿。最近行った場所のエピソードや行きたい場所への思いなど。",
    "daily": "日常の何気ないひとコマ。食べたもの、見たもの、感じたことなど、セラピストとしての日常を自然に。",
    "night": "おやすみ投稿。今日の感謝や明日への気持ちを穏やかに。お客様への感謝を自然に含める。",
    "thanks": "お客様へのお礼投稿。直接的な名前は出さず、今日会えた方への感謝を温かく。",
}


def generate_post(post_type: str = None) -> str:
    """指定タイプのツイートを生成する。タイプ未指定ならランダム。"""
    if post_type is None:
        post_type = random.choice(list(POST_TYPES.keys()))

    prompt = POST_TYPES.get(post_type, POST_TYPES["daily"])

    ctx = _load_context()
    context_block = f"\n\n【りおんの最近のネタ帳（参考にしてください）】\n{ctx}" if ctx else ""
    return _call_llm(f"{SYSTEM_PROMPT}{context_block}\n\n【今回の投稿テーマ】{prompt}", max_tokens=500)


def generate_reply(mention_text: str, username: str) -> str:
    """メンション・リプライ用の返信を生成する。"""
    reply_prompt = f"""
{SYSTEM_PROMPT}

【タスク】
以下のツイートへの返信を書いてください。
相手のツイート: 「{mention_text}」
相手のユーザー名: @{username}

【返信のルール】
- @{username} で始める
- 共感・温かみのある返し
- 自然な会話トーン
- 60文字以内
- 絵文字1〜2個
- 宣伝・誘導は絶対にしない
"""
    return _call_llm(reply_prompt, max_tokens=150)


# 仙台お客様サーチ用キーワード（自動リプ対象）
SENDAI_CUSTOMER_KEYWORDS = [
    "仙台 癒し",
    "仙台 マッサージ",
    "仙台 エステ",
    "仙台 疲れた",
    "仙台 リフレッシュ",
]

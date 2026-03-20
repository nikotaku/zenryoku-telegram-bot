"""
ブラウザエージェント — LLM インテント解析 + Playwright 自動操作

ユーザーの自然言語指示を Gemini API で解析し、
キャスカン・エスたまのブラウザ操作を自動実行する。

フロー:
  1. ユーザーが Telegram で自然言語の指示を送信
  2. LLM がインテント（意図）を JSON で返す
  3. 対応するブラウザ操作を Playwright で実行
  4. 結果を Telegram に返す
"""

import os
import json
import logging
import asyncio
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

# ─── LLM インテント解析 ──────────────────────────────────────

SYSTEM_PROMPT = """あなたは「全力エステ」（仙台のメンズエステ）の業務アシスタントAIです。
ユーザーからの自然言語の指示を解析し、実行すべきアクションをJSON形式で返してください。

## 対応可能なアクション

### キャスカン (caskan) 操作
- `caskan_register_shift`: シフト登録
  - params: cast_name, date, start_time, end_time, room_name(optional)
- `caskan_delete_shift`: シフト削除
  - params: cast_name, date
- `caskan_get_shifts`: シフト確認・取得
  - params: date(optional, default=today)
- `caskan_get_casts`: キャスト一覧取得
  - params: なし
- `caskan_get_rooms`: ルーム一覧取得
  - params: なし

### エスたま (estama) 操作
- `estama_register_schedule`: 出勤登録
  - params: therapist_name, date, start_time, end_time
- `estama_get_schedule`: 出勤表取得
  - params: なし
- `estama_get_therapists`: セラピスト一覧取得
  - params: なし
- `estama_set_guidance`: ご案内状況設定
  - params: status ("now", "accepting", "ended")
- `estama_appeal`: 集客ワンクリックアピール実行
  - params: なし

### 同期操作
- `sync_shifts`: キャスカン→エスたまのシフト同期
  - params: date(optional, default=today)
- `sync_all_week`: 今週のシフトを一括同期
  - params: なし
- `diff_shifts`: キャスカンとエスたまのシフト差異を比較して報告
  - params: date(optional, default=today)

### 複合操作
- `register_both`: キャスカンとエスたま両方にシフト登録
  - params: cast_name, date, start_time, end_time, room_name(optional)

### その他
- `unknown`: 対応できない指示
  - params: reason(str)

## 日付の解釈ルール
- 「今日」→ 今日の日付
- 「明日」→ 明日の日付
- 「明後日」→ 明後日の日付
- 「来週月曜」→ 次の月曜日の日付
- 「3/25」「3月25日」→ 今年の3月25日
- 具体的な日付がない場合は today を使用

## 時刻の解釈ルール
- 「14時」→ "14:00"
- 「14時半」→ "14:30"
- 「夜10時」→ "22:00"
- 「25時」→ "25:00"（深夜1時、業界慣習で25時表記）

## 出力形式
必ず以下のJSON形式で返してください。余計なテキストは含めないでください。

```json
{
  "action": "アクション名",
  "params": {
    "パラメータ名": "値"
  },
  "confirmation_message": "実行前にユーザーに確認するメッセージ（日本語）"
}
```

## 複数アクションの場合
```json
{
  "actions": [
    {
      "action": "アクション名1",
      "params": {...}
    },
    {
      "action": "アクション名2",
      "params": {...}
    }
  ],
  "confirmation_message": "確認メッセージ"
}
```

## 注意事項
- セラピスト名は絵文字や数字を除いた名前のみを使用すること
- 日付は必ず "YYYY-MM-DD" 形式に変換すること
- 時刻は必ず "HH:MM" 形式に変換すること
- 不明な情報がある場合は confirmation_message で確認を求めること
"""


async def parse_intent(user_message: str) -> dict:
    """
    ユーザーの自然言語メッセージを LLM で解析し、
    実行すべきアクションを JSON で返す。

    Args:
        user_message: ユーザーからのテキストメッセージ

    Returns:
        {
            "action": str or None,
            "actions": list or None,
            "params": dict,
            "confirmation_message": str,
        }
    """
    try:
        import google.generativeai as genai
        genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))

        model = genai.GenerativeModel("gemini-2.5-flash")

        # 現在日時のコンテキストを追加
        now = datetime.now()
        today_str = now.strftime("%Y-%m-%d")
        tomorrow_str = (now + timedelta(days=1)).strftime("%Y-%m-%d")
        day_after_str = (now + timedelta(days=2)).strftime("%Y-%m-%d")

        # 曜日名
        weekday_names = ["月", "火", "水", "木", "金", "土", "日"]
        today_weekday = weekday_names[now.weekday()]

        # 来週の各曜日
        next_week_dates = {}
        for i in range(7):
            d = now + timedelta(days=(7 - now.weekday() + i) % 7 or 7)
            next_week_dates[weekday_names[d.weekday()]] = d.strftime("%Y-%m-%d")

        context_msg = (
            f"現在日時: {now.strftime('%Y年%m月%d日(%a) %H:%M')}\n"
            f"今日: {today_str}（{today_weekday}曜日）\n"
            f"明日: {tomorrow_str}\n"
            f"明後日: {day_after_str}\n"
            f"来週の日付: {json.dumps(next_week_dates, ensure_ascii=False)}"
        )

        prompt = f"{SYSTEM_PROMPT}\n\n{context_msg}\n\n指示: {user_message}"

        response = model.generate_content(
            contents=[{"role": "user", "parts": [{"text": prompt}]}],
            generation_config=genai.types.GenerationConfig(
                max_output_tokens=1000,
                temperature=0.1,
                response_mime_type="application/json",
            ),
        )

        result_text = response.text.strip()
        result = json.loads(result_text)

        logger.info(f"LLM解析結果: {result}")
        return result

    except json.JSONDecodeError as e:
        logger.error(f"LLM応答のJSON解析エラー: {e}")
        return {
            "action": "unknown",
            "params": {"reason": "LLMの応答を解析できませんでした"},
            "confirmation_message": "申し訳ありません。指示を理解できませんでした。もう少し具体的に教えてください。",
        }
    except Exception as e:
        logger.error(f"LLMインテント解析エラー: {e}")
        return {
            "action": "unknown",
            "params": {"reason": str(e)},
            "confirmation_message": f"エラーが発生しました: {str(e)[:100]}",
        }


# ─── ブラウザ操作エグゼキューター ────────────────────────────

class BrowserAgent:
    """LLM解析結果に基づいてブラウザ操作を実行するエージェント"""

    def __init__(self):
        self._caskan = None
        self._estama = None

    async def _get_caskan(self):
        if self._caskan is None:
            from caskan_browser import CaskanBrowser
            self._caskan = CaskanBrowser()
        return self._caskan

    async def _get_estama(self):
        if self._estama is None:
            from estama_browser import EstamaBrowser
            self._estama = EstamaBrowser()
        return self._estama

    async def close(self):
        """全ブラウザインスタンスを閉じる"""
        if self._caskan:
            await self._caskan.close()
            self._caskan = None
        if self._estama:
            await self._estama.close()
            self._estama = None

    async def execute(self, intent: dict) -> str:
        """
        LLM解析結果のインテントを実行し、結果メッセージを返す。

        Args:
            intent: parse_intent() の戻り値

        Returns:
            実行結果のテキストメッセージ
        """
        # 複数アクションの場合
        if "actions" in intent and isinstance(intent["actions"], list):
            results = []
            for action_item in intent["actions"]:
                single_intent = {
                    "action": action_item.get("action"),
                    "params": action_item.get("params", {}),
                }
                result = await self._execute_single(single_intent)
                results.append(result)
            return "\n\n".join(results)

        # 単一アクションの場合
        return await self._execute_single(intent)

    async def _execute_single(self, intent: dict) -> str:
        """単一アクションを実行する"""
        action = intent.get("action", "unknown")
        params = intent.get("params", {})

        try:
            # ─── キャスカン操作 ─────────────────────────
            if action == "caskan_register_shift":
                return await self._caskan_register_shift(params)

            elif action == "caskan_delete_shift":
                return await self._caskan_delete_shift(params)

            elif action == "caskan_get_shifts":
                return await self._caskan_get_shifts(params)

            elif action == "caskan_get_casts":
                return await self._caskan_get_casts()

            elif action == "caskan_get_rooms":
                return await self._caskan_get_rooms()

            # ─── エスたま操作 ──────────────────────────
            elif action == "estama_register_schedule":
                return await self._estama_register_schedule(params)

            elif action == "estama_get_schedule":
                return await self._estama_get_schedule()

            elif action == "estama_get_therapists":
                return await self._estama_get_therapists()

            elif action == "estama_set_guidance":
                return await self._estama_set_guidance(params)

            elif action == "estama_appeal":
                return await self._estama_appeal()

            # ─── 同期操作 ─────────────────────────────
            elif action == "sync_shifts":
                return await self._sync_shifts(params)

            elif action == "sync_all_week":
                return await self._sync_all_week()

            elif action == "diff_shifts":
                return await self._diff_shifts(params)

            # ─── 複合操作 ─────────────────────────────
            elif action == "register_both":
                return await self._register_both(params)

            # ─── 不明 ────────────────────────────────
            elif action == "unknown":
                reason = params.get("reason", "対応できない指示です")
                return f"⚠️ {reason}\n\n使い方のヒント:\n• 「明日りおんを14時から23時でキャスカンに登録して」\n• 「今日のシフトを確認して」\n• 「キャスカンからエスたまにシフト同期して」\n• 「エスたまでアピールして」"

            else:
                return f"⚠️ 未対応のアクション: {action}"

        except Exception as e:
            logger.error(f"アクション実行エラー [{action}]: {e}")
            return f"❌ 実行中にエラーが発生しました: {str(e)[:200]}"

    # ─── キャスカン操作の実装 ────────────────────────────────

    async def _caskan_register_shift(self, params: dict) -> str:
        caskan = await self._get_caskan()
        result = await caskan.register_shift(
            cast_name=params.get("cast_name", ""),
            date_str=params.get("date", datetime.now().strftime("%Y-%m-%d")),
            start_time=params.get("start_time", ""),
            end_time=params.get("end_time", ""),
            room_name=params.get("room_name"),
        )
        if result.get("success"):
            return f"✅ 【キャスカン】{result['message']}"
        else:
            return f"❌ 【キャスカン】{result['message']}"

    async def _caskan_delete_shift(self, params: dict) -> str:
        caskan = await self._get_caskan()
        result = await caskan.delete_shift(
            cast_name=params.get("cast_name", ""),
            date_str=params.get("date", datetime.now().strftime("%Y-%m-%d")),
        )
        if result.get("success"):
            return f"✅ 【キャスカン】{result['message']}"
        else:
            return f"❌ 【キャスカン】{result['message']}"

    async def _caskan_get_shifts(self, params: dict) -> str:
        caskan = await self._get_caskan()
        date = params.get("date")
        result = await caskan.get_shift_page(date)

        if "error" in result:
            return f"❌ 【キャスカン】{result['error']}"

        shifts = result.get("shifts", [])
        if not shifts:
            date_display = date or "今日"
            return f"📅 【キャスカン】{date_display}のシフトはありません。"

        text = "📅 【キャスカン シフト一覧】\n\n"
        current_date = ""
        for s in shifts:
            if s.get("date") != current_date:
                current_date = s["date"]
                text += f"\n📆 {current_date}\n"
            name = s.get("name", "不明")
            time_raw = s.get("time_raw", f"{s.get('start', '?')}〜{s.get('end', '?')}")
            text += f"  👤 {name}  ⏰ {time_raw}\n"

        return text

    async def _caskan_get_casts(self) -> str:
        caskan = await self._get_caskan()
        casts = await caskan.get_cast_list()

        if not casts:
            return "❌ 【キャスカン】キャスト一覧の取得に失敗しました。"

        text = "👥 【キャスカン キャスト一覧】\n\n"
        for i, cast in enumerate(casts, 1):
            name = cast.get("name", "不明")
            status = cast.get("status", "不明")
            text += f"{i}. {name} [{status}]\n"

        return text

    async def _caskan_get_rooms(self) -> str:
        caskan = await self._get_caskan()
        rooms = await caskan.get_room_list()

        if not rooms:
            return "❌ 【キャスカン】ルーム一覧の取得に失敗しました。"

        text = "🏠 【キャスカン ルーム一覧】\n\n"
        for room in rooms:
            text += f"• {room.get('name', '不明')} (ID: {room.get('id', '?')})\n"

        return text

    # ─── エスたま操作の実装 ──────────────────────────────────

    async def _estama_register_schedule(self, params: dict) -> str:
        estama = await self._get_estama()
        result = await estama.register_schedule(
            therapist_name=params.get("therapist_name", params.get("cast_name", "")),
            date_str=params.get("date", datetime.now().strftime("%Y-%m-%d")),
            start_time=params.get("start_time", ""),
            end_time=params.get("end_time", ""),
        )
        if result.get("success"):
            return f"✅ 【エスたま】{result['message']}"
        else:
            return f"❌ 【エスたま】{result['message']}"

    async def _estama_get_schedule(self) -> str:
        estama = await self._get_estama()
        result = await estama.get_schedule()

        if "error" in result:
            return f"❌ 【エスたま】{result['error']}"

        schedules = result.get("schedules", [])
        if not schedules:
            return "📅 【エスたま】出勤情報はありません。"

        text = "📅 【エスたま 出勤表】\n\n"
        for s in schedules:
            name = s.get("name", "不明")
            start = s.get("start", "?")
            end = s.get("end", "?")
            text += f"  👤 {name}  ⏰ {start}〜{end}\n"

        return text

    async def _estama_get_therapists(self) -> str:
        estama = await self._get_estama()
        therapists = await estama.get_therapist_list()

        if not therapists:
            return "❌ 【エスたま】セラピスト一覧の取得に失敗しました。"

        text = "👥 【エスたま セラピスト一覧】\n\n"
        for i, t in enumerate(therapists, 1):
            text += f"{i}. {t.get('name', '不明')}\n"

        return text

    async def _estama_set_guidance(self, params: dict) -> str:
        estama = await self._get_estama()
        status = params.get("status", "now")
        result = await estama.set_guidance_status(status)

        if result.get("success"):
            return f"✅ 【エスたま】{result['message']}"
        else:
            return f"❌ 【エスたま】{result['message']}"

    async def _estama_appeal(self) -> str:
        estama = await self._get_estama()
        result = await estama.click_appeal()

        if result.get("success"):
            return f"✅ 【エスたま】{result['message']}"
        else:
            return f"❌ 【エスたま】{result['message']}"

    # ─── 同期操作の実装 ─────────────────────────────────────

    async def _sync_shifts(self, params: dict) -> str:
        """キャスカンのシフトをエスたまに同期する"""
        date = params.get("date", datetime.now().strftime("%Y-%m-%d"))

        caskan = await self._get_caskan()
        estama = await self._get_estama()

        # キャスカンからシフト取得
        caskan_data = await caskan.get_shift_page(date)
        if "error" in caskan_data:
            return f"❌ キャスカンからのシフト取得に失敗: {caskan_data['error']}"

        shifts = caskan_data.get("shifts", [])
        if not shifts:
            return f"📅 {date}のキャスカンシフトはありません。同期するデータがありません。"

        # エスたまに同期
        result = await estama.sync_from_caskan(shifts)

        text = f"🔄 【シフト同期結果】{date}\n\n"
        text += f"✅ 成功: {result['synced']}件\n"
        text += f"❌ 失敗: {result['failed']}件\n"

        if result.get("details"):
            text += "\n詳細:\n"
            for detail in result["details"][:10]:
                text += f"  {detail}\n"

        return text

    async def _sync_all_week(self) -> str:
        """今週のシフトを一括同期する"""
        now = datetime.now()
        results = []

        for i in range(7):
            date = (now + timedelta(days=i)).strftime("%Y-%m-%d")
            result = await self._sync_shifts({"date": date})
            results.append(result)
            await asyncio.sleep(2)  # 連続アクセスの間隔

        return "\n\n".join(results)

    async def _diff_shifts(self, params: dict) -> str:
        """キャスカンとエスたまのシフトを比較して差異を報告する"""
        date = params.get("date", datetime.now().strftime("%Y-%m-%d"))

        caskan = await self._get_caskan()
        estama = await self._get_estama()

        # キャスカンのシフト取得
        caskan_data = await caskan.get_shift_page(date)
        if "error" in caskan_data:
            return f"❌ キャスカンからのシフト取得に失敗: {caskan_data['error']}"

        caskan_shifts = caskan_data.get("shifts", [])

        # エスたまのスケジュール取得
        estama_data = await estama.get_schedule()
        if "error" in estama_data:
            return f"❌ エスたまからのスケジュール取得に失敗: {estama_data['error']}"

        estama_schedules = estama_data.get("schedules", [])

        # キャスカンのシフトを名前→(start, end) のマップに変換
        caskan_map = {}
        for s in caskan_shifts:
            name = s.get("name", "").strip()
            if name:
                caskan_map[name] = {
                    "start": s.get("start", ""),
                    "end": s.get("end", ""),
                    "time_raw": s.get("time_raw", ""),
                }

        # エスたまのスケジュールを名前→(start, end) のマップに変換
        estama_map = {}
        for s in estama_schedules:
            name = s.get("name", "").strip()
            if name:
                estama_map[name] = {
                    "start": s.get("start", ""),
                    "end": s.get("end", ""),
                }

        # 差異を検出
        all_names = set(caskan_map.keys()) | set(estama_map.keys())
        diffs = []
        matched = []

        for name in sorted(all_names):
            in_caskan = name in caskan_map
            in_estama = name in estama_map

            if in_caskan and not in_estama:
                c = caskan_map[name]
                diffs.append(
                    f"⚠️ {name}: キャスカンにあるがエスたまに未登録\n"
                    f"   キャスカン: {c.get('time_raw') or c['start']+'〜'+c['end']}"
                )
            elif not in_caskan and in_estama:
                e = estama_map[name]
                diffs.append(
                    f"⚠️ {name}: エスたまにあるがキャスカンに未登録\n"
                    f"   エスたま: {e['start']}〜{e['end']}"
                )
            else:
                c = caskan_map[name]
                e = estama_map[name]
                c_start = c["start"]
                c_end = c["end"]
                e_start = e["start"]
                e_end = e["end"]
                if c_start != e_start or c_end != e_end:
                    diffs.append(
                        f"⚠️ {name}: 時刻がズレています\n"
                        f"   キャスカン: {c.get('time_raw') or c_start+'〜'+c_end}\n"
                        f"   エスたま:   {e_start}〜{e_end}"
                    )
                else:
                    matched.append(f"✅ {name}: {c.get('time_raw') or c_start+'〜'+c_end}")

        # 結果メッセージを組み立て
        text = f"📋 【シフト差異確認】{date}\n\n"

        if not caskan_map and not estama_map:
            text += "両システムにシフト情報がありません。"
            return text

        if diffs:
            text += f"🔴 差異あり ({len(diffs)}件):\n\n"
            text += "\n\n".join(diffs)
            text += "\n"
        else:
            text += "🟢 差異なし: 全シフトが一致しています。\n"

        if matched:
            text += f"\n✅ 一致 ({len(matched)}件):\n"
            text += "\n".join(matched)

        return text

    # ─── 複合操作の実装 ─────────────────────────────────────

    async def _register_both(self, params: dict) -> str:
        """キャスカンとエスたま両方にシフト登録する"""
        cast_name = params.get("cast_name", "")
        date = params.get("date", datetime.now().strftime("%Y-%m-%d"))
        start_time = params.get("start_time", "")
        end_time = params.get("end_time", "")
        room_name = params.get("room_name")

        results = []

        # キャスカンに登録
        caskan_result = await self._caskan_register_shift({
            "cast_name": cast_name,
            "date": date,
            "start_time": start_time,
            "end_time": end_time,
            "room_name": room_name,
        })
        results.append(caskan_result)

        await asyncio.sleep(2)

        # エスたまに登録
        estama_result = await self._estama_register_schedule({
            "therapist_name": cast_name,
            "date": date,
            "start_time": start_time,
            "end_time": end_time,
        })
        results.append(estama_result)

        return "\n".join(results)


# ─── メインの処理フロー ──────────────────────────────────────

# シングルトンインスタンス
_agent_instance: Optional[BrowserAgent] = None


def get_agent() -> BrowserAgent:
    """BrowserAgent のシングルトンインスタンスを取得する"""
    global _agent_instance
    if _agent_instance is None:
        _agent_instance = BrowserAgent()
    return _agent_instance


async def process_agent_command(user_message: str) -> tuple[str, str]:
    """
    ユーザーメッセージを処理し、確認メッセージと実行結果を返す。

    Args:
        user_message: ユーザーからのテキストメッセージ

    Returns:
        (confirmation_message, action_json_str)
        confirmation_message: ユーザーに確認を求めるメッセージ
        action_json_str: 実行するアクションのJSON文字列（確認後に execute_confirmed で使用）
    """
    intent = await parse_intent(user_message)

    confirmation = intent.get("confirmation_message", "")
    action_json = json.dumps(intent, ensure_ascii=False)

    return confirmation, action_json


async def execute_confirmed(action_json: str) -> str:
    """
    確認済みのアクションを実行する。

    Args:
        action_json: process_agent_command で返された action_json_str

    Returns:
        実行結果のテキストメッセージ
    """
    try:
        intent = json.loads(action_json)
        agent = get_agent()
        result = await agent.execute(intent)
        return result
    except Exception as e:
        logger.error(f"アクション実行エラー: {e}")
        return f"❌ 実行中にエラーが発生しました: {str(e)[:200]}"


async def execute_direct(user_message: str) -> str:
    """
    確認なしで直接実行する（シフト確認など読み取り系の操作向け）。

    Args:
        user_message: ユーザーからのテキストメッセージ

    Returns:
        実行結果のテキストメッセージ
    """
    intent = await parse_intent(user_message)

    # 読み取り系のアクションは確認なしで実行
    read_actions = {
        "caskan_get_shifts", "caskan_get_casts", "caskan_get_rooms",
        "estama_get_schedule", "estama_get_therapists", "diff_shifts",
    }

    action = intent.get("action", "")
    actions = intent.get("actions", [])

    # 単一の読み取りアクション
    if action in read_actions:
        agent = get_agent()
        return await agent.execute(intent)

    # 複数アクションの場合、全て読み取り系なら直接実行
    if actions and all(a.get("action") in read_actions for a in actions):
        agent = get_agent()
        return await agent.execute(intent)

    # 書き込み系は確認メッセージを返す
    confirmation = intent.get("confirmation_message", "この操作を実行しますか？")
    return confirmation, json.dumps(intent, ensure_ascii=False)

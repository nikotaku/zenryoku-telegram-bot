"""
ブラウザエージェント — LLM インテント解析 + Playwright 自動操作

ユーザーの自然言語指示を Gemini API で解析し、
キャスカン・エスたまのブラウザ操作を自動実行する。

同期フロー（NotionシフトDBがマスタ）:
  - NotionシフトDB → キャスカン に同期
  - NotionシフトDB → エスたま に同期
  - ステータス管理: 未着手 → ｷｬｽｶﾝ完了/エスたま未登録 → 完了
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

### NotionシフトDB操作
- `notion_get_shifts`: NotionシフトDBからシフト取得
  - params: date(optional, default=today), days_range(optional, default=0)
- `notion_get_pending`: 同期が必要なシフトを取得
  - params: target("caskan" or "estama")
- `notion_add_shift`: NotionシフトDBにシフトを新規登録
  - params: name, date, in_time, out_time, room(optional)
- `notion_delete_shift`: NotionシフトDBからシフトを削除
  - params: name, date


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

### 同期操作（NotionシフトDBがマスタ）
- `sync_to_caskan`: NotionシフトDB → キャスカンにシフト同期
  - params: date(optional, default=today)
- `sync_to_estama`: NotionシフトDB → エスたまにシフト同期
  - params: date(optional, default=today)
- `sync_all`: NotionシフトDB → キャスカン＆エスたま両方に同期
  - params: date(optional, default=today)
- `sync_all_week`: 今週のシフトを一括同期（Notion→キャスカン＆エスたま）
  - params: なし
- `diff_shifts`: NotionシフトDBとキャスカン・エスたまのシフト差異を比較
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
- 「同期」「シフト同期」と言われたら sync_all を使用すること
- 「キャスカンに同期」→ sync_to_caskan、「エスたまに同期」→ sync_to_estama
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
            # ─── NotionシフトDB操作 ────────────────────
            if action == "notion_get_shifts":
                return await self._notion_get_shifts(params)

            elif action == "notion_get_pending":
                return await self._notion_get_pending(params)

            elif action == "notion_add_shift":
                return await self._notion_add_shift(params)

            elif action == "notion_delete_shift":
                return await self._notion_delete_shift(params)



            # ─── キャスカン操作 ─────────────────────────
            elif action == "caskan_register_shift":
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

            # ─── 同期操作（Notionマスタ）──────────────────
            elif action == "sync_to_caskan":
                return await self._sync_to_caskan(params)

            elif action == "sync_to_estama":
                return await self._sync_to_estama(params)

            elif action == "sync_all":
                return await self._sync_all(params)

            elif action == "sync_shifts":
                # 旧アクション名の互換性
                return await self._sync_all(params)

            elif action == "sync_all_week":
                return await self._sync_all_week()

            elif action == "sync_to_caskan_week":
                return await self._sync_to_caskan_week()

            elif action == "sync_to_estama_week":
                return await self._sync_to_estama_week()

            elif action == "diff_shifts_week":
                return await self._diff_shifts_week()

            elif action == "diff_shifts":
                return await self._diff_shifts(params)

            # ─── 複合操作 ─────────────────────────────
            elif action == "register_both":
                return await self._register_both(params)

            # ─── 不明 ────────────────────────────────
            elif action == "unknown":
                reason = params.get("reason", "対応できない指示です")
                return (
                    f"⚠️ {reason}\n\n"
                    "使い方のヒント:\n"
                    "• 「明日りおんを14時から23時でキャスカンに登録して」\n"
                    "• 「今日のシフトを確認して」\n"
                    "• 「NotionシフトDBからキャスカンに同期して」\n"
                    "• 「エスたまでアピールして」"
                )

            else:
                return f"⚠️ 未対応のアクション: {action}"

        except Exception as e:
            logger.error(f"アクション実行エラー [{action}]: {e}")
            return f"❌ 実行中にエラーが発生しました: {str(e)[:200]}"

    # ─── NotionシフトDB操作の実装 ───────────────────────────────

    async def _notion_get_shifts(self, params: dict) -> str:
        """NotionシフトDBからシフトを取得して表示する"""
        from notion_shift_client import query_shifts, format_shifts_message

        date = params.get("date")
        days_range = int(params.get("days_range", 0))
        shifts = query_shifts(date_str=date, days_range=days_range)
        return format_shifts_message(shifts, "NotionシフトDB")


    async def _notion_add_shift(self, params: dict) -> str:
        name = params.get("name", "")
        date_str = params.get("date", "")
        in_time = params.get("in_time", "")
        out_time = params.get("out_time", "")
        room = params.get("room", "")

        if not (name and date_str and in_time and out_time):
            return "❌ エラー: セラピスト名、日付、IN時間、OUT時間は必須です。"

        import notion_shift_client
        page_id = notion_shift_client.create_shift(name, date_str, in_time, out_time, room)
        if page_id:
            room_str = f" 🏠{room}" if room else ""
            return f"✅ Notionにシフトを登録しました！\n👤 {name}\n📅 {date_str}\n🕒 {in_time}〜{out_time}{room_str}"
        else:
            return "❌ Notionへの登録に失敗しました。"

    async def _notion_delete_shift(self, params: dict) -> str:
        name = params.get("name", "")
        date_str = params.get("date", "")

        if not (name and date_str):
            return "❌ エラー: セラピスト名と日付は必須です。"

        import notion_shift_client
        shifts = notion_shift_client.query_shifts(date_str)
        target_shift = next((s for s in shifts if s["name"] == name), None)
        
        if not target_shift:
            return f"⚠️ {date_str} の {name} さんのシフトが見つかりませんでした。"
            
        success = notion_shift_client.delete_shift(target_shift["page_id"])
        if success:
            return f"🗑️ Notionからシフトを削除しました！\n👤 {name}\n📅 {date_str}"
        else:
            return "❌ Notionからの削除に失敗しました。"

    async def _notion_get_pending(self, params: dict) -> str:
        """同期が必要なシフトを取得して表示する"""
        from notion_shift_client import query_pending_shifts, format_shifts_message

        target = params.get("target", "caskan")
        shifts = query_pending_shifts(target=target)

        if target == "caskan":
            title = "キャスカン未同期シフト"
        else:
            title = "エスたま未同期シフト"

        return format_shifts_message(shifts, title)

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

    # ─── 同期操作の実装（Notionマスタ）─────────────────────────

    async def _sync_to_caskan(self, params: dict) -> str:
        """NotionシフトDB → キャスカンにシフト同期"""
        from notion_shift_client import (
            query_shifts,
            update_shift_status,
            STATUS_NOT_STARTED,
            STATUS_CASKAN_DONE,
        )

        date = params.get("date", datetime.now().strftime("%Y-%m-%d"))

        # Notionからシフト取得
        shifts = query_shifts(date_str=date)
        if not shifts:
            return f"📅 {date}のNotionシフトDBにシフトがありません。"

        # 未着手のシフトのみ同期
        pending = [s for s in shifts if s["status"] == STATUS_NOT_STARTED]
        if not pending:
            return f"📅 {date}のキャスカン未同期シフトはありません。（全て同期済み）"

        caskan = await self._get_caskan()

        synced = 0
        failed = 0
        details = []

        for shift in pending:
            try:
                result = await caskan.register_shift(
                    cast_name=shift["name"],
                    date_str=shift["date"],
                    start_time=shift["start"],
                    end_time=shift["end"],
                    room_name=shift.get("room"),
                )

                if result.get("success"):
                    # ステータスを「ｷｬｽｶﾝ完了/エスたま未登録」に更新
                    update_shift_status(shift["page_id"], STATUS_CASKAN_DONE)
                    synced += 1
                    details.append(f"✅ {shift['name']} {shift['date']} {shift['start']}〜{shift['end']}")
                else:
                    failed += 1
                    details.append(f"❌ {shift['name']} {shift['date']}: {result['message']}")

            except Exception as e:
                failed += 1
                details.append(f"❌ {shift['name']} {shift['date']}: {str(e)[:100]}")

            await asyncio.sleep(2)

        text = f"🔄 【Notion→キャスカン同期結果】{date}\n\n"
        text += f"✅ 成功: {synced}件\n"
        text += f"❌ 失敗: {failed}件\n"

        if details:
            text += "\n詳細:\n"
            for detail in details[:15]:
                text += f"  {detail}\n"

        return text

    async def _sync_to_estama(self, params: dict) -> str:
        """NotionシフトDB → エスたまにシフト同期"""
        from notion_shift_client import (
            query_shifts,
            update_shift_status,
            STATUS_NOT_STARTED,
            STATUS_CASKAN_DONE,
            STATUS_COMPLETED,
        )

        date = params.get("date", datetime.now().strftime("%Y-%m-%d"))

        # Notionからシフト取得
        shifts = query_shifts(date_str=date)
        if not shifts:
            return f"📅 {date}のNotionシフトDBにシフトがありません。"

        # エスたま未同期のシフト（未着手 or ｷｬｽｶﾝ完了/エスたま未登録）
        pending = [
            s for s in shifts
            if s["status"] in (STATUS_NOT_STARTED, STATUS_CASKAN_DONE)
        ]
        if not pending:
            return f"📅 {date}のエスたま未同期シフトはありません。（全て同期済み）"

        estama = await self._get_estama()

        synced = 0
        failed = 0
        details = []

        for shift in pending:
            try:
                result = await estama.register_schedule(
                    therapist_name=shift["name"],
                    date_str=shift["date"],
                    start_time=shift["start"],
                    end_time=shift["end"],
                )

                if result.get("success"):
                    # ステータスを「完了」に更新
                    if shift["status"] == STATUS_CASKAN_DONE:
                        update_shift_status(shift["page_id"], STATUS_COMPLETED)
                    elif shift["status"] == STATUS_NOT_STARTED:
                        # キャスカン未同期のままエスたまだけ完了した場合
                        # ステータスは変えない（キャスカン同期が先に必要）
                        pass
                    synced += 1
                    details.append(f"✅ {shift['name']} {shift['date']} {shift['start']}〜{shift['end']}")
                else:
                    failed += 1
                    details.append(f"❌ {shift['name']} {shift['date']}: {result['message']}")

            except Exception as e:
                failed += 1
                details.append(f"❌ {shift['name']} {shift['date']}: {str(e)[:100]}")

            await asyncio.sleep(2)

        text = f"🔄 【Notion→エスたま同期結果】{date}\n\n"
        text += f"✅ 成功: {synced}件\n"
        text += f"❌ 失敗: {failed}件\n"

        if details:
            text += "\n詳細:\n"
            for detail in details[:15]:
                text += f"  {detail}\n"

        return text

    async def _sync_all(self, params: dict) -> str:
        """NotionシフトDB → キャスカン＆エスたま両方に同期"""
        from notion_shift_client import (
            query_shifts,
            update_shift_status,
            STATUS_NOT_STARTED,
            STATUS_CASKAN_DONE,
            STATUS_COMPLETED,
        )

        date = params.get("date", datetime.now().strftime("%Y-%m-%d"))

        # Notionからシフト取得
        shifts = query_shifts(date_str=date)
        if not shifts:
            return f"📅 {date}のNotionシフトDBにシフトがありません。"

        caskan = await self._get_caskan()
        estama = await self._get_estama()

        caskan_synced = 0
        caskan_failed = 0
        estama_synced = 0
        estama_failed = 0
        details = []

        for shift in shifts:
            status = shift["status"]

            # ─── キャスカン同期 ───
            if status == STATUS_NOT_STARTED:
                try:
                    result = await caskan.register_shift(
                        cast_name=shift["name"],
                        date_str=shift["date"],
                        start_time=shift["start"],
                        end_time=shift["end"],
                        room_name=shift.get("room"),
                    )
                    if result.get("success"):
                        caskan_synced += 1
                        details.append(f"✅ キャスカン: {shift['name']} {shift['start']}〜{shift['end']}")
                        # ステータス更新
                        update_shift_status(shift["page_id"], STATUS_CASKAN_DONE)
                        shift["status"] = STATUS_CASKAN_DONE
                    else:
                        caskan_failed += 1
                        details.append(f"❌ キャスカン: {shift['name']}: {result['message']}")
                except Exception as e:
                    caskan_failed += 1
                    details.append(f"❌ キャスカン: {shift['name']}: {str(e)[:80]}")

                await asyncio.sleep(2)

            # ─── エスたま同期 ───
            if shift["status"] in (STATUS_CASKAN_DONE, STATUS_NOT_STARTED):
                try:
                    result = await estama.register_schedule(
                        therapist_name=shift["name"],
                        date_str=shift["date"],
                        start_time=shift["start"],
                        end_time=shift["end"],
                    )
                    if result.get("success"):
                        estama_synced += 1
                        details.append(f"✅ エスたま: {shift['name']} {shift['start']}〜{shift['end']}")
                        # キャスカンも完了していれば「完了」に
                        if shift["status"] == STATUS_CASKAN_DONE:
                            update_shift_status(shift["page_id"], STATUS_COMPLETED)
                    else:
                        estama_failed += 1
                        details.append(f"❌ エスたま: {shift['name']}: {result['message']}")
                except Exception as e:
                    estama_failed += 1
                    details.append(f"❌ エスたま: {shift['name']}: {str(e)[:80]}")

                await asyncio.sleep(2)

        text = f"🔄 【Notion→全同期結果】{date}\n\n"
        text += f"📌 キャスカン: ✅{caskan_synced} ❌{caskan_failed}\n"
        text += f"📌 エスたま:   ✅{estama_synced} ❌{estama_failed}\n"

        if details:
            text += "\n詳細:\n"
            for detail in details[:20]:
                text += f"  {detail}\n"

        return text

    async def _sync_all_week(self) -> str:
        """今週のシフトを一括同期する"""
        now = datetime.now()
        results = []

        for i in range(7):
            date = (now + timedelta(days=i)).strftime("%Y-%m-%d")
            result = await self._sync_all({"date": date})
            results.append(result)
            await asyncio.sleep(2)

        return "\n\n".join(results)


    async def _sync_to_caskan_week(self) -> str:
        from datetime import datetime, timedelta
        import asyncio
        now = datetime.now()
        results = []
        for i in range(7):
            date = (now + timedelta(days=i)).strftime("%Y-%m-%d")
            result = await self._sync_to_caskan({"date": date})
            results.append(result)
            await asyncio.sleep(1)
        return "\n\n".join(results)

    async def _sync_to_estama_week(self) -> str:
        from datetime import datetime, timedelta
        import asyncio
        now = datetime.now()
        results = []
        for i in range(7):
            date = (now + timedelta(days=i)).strftime("%Y-%m-%d")
            result = await self._sync_to_estama({"date": date})
            results.append(result)
            await asyncio.sleep(1)
        return "\n\n".join(results)

    async def _diff_shifts_week(self) -> str:
        from datetime import datetime, timedelta
        import asyncio
        now = datetime.now()
        results = []
        for i in range(7):
            date = (now + timedelta(days=i)).strftime("%Y-%m-%d")
            result = await self._diff_shifts({"date": date})
            results.append(result)
            await asyncio.sleep(1)
        return "\n\n".join(results)

    async def _diff_shifts(self, params: dict) -> str:
        """NotionシフトDBとキャスカン・エスたまのシフトを比較して差異を報告する"""
        from notion_shift_client import query_shifts

        date = params.get("date", datetime.now().strftime("%Y-%m-%d"))

        # Notionからシフト取得
        notion_shifts = query_shifts(date_str=date)

        caskan = await self._get_caskan()
        estama = await self._get_estama()

        # キャスカンのシフト取得
        caskan_data = await caskan.get_shift_page(date)
        caskan_shifts = caskan_data.get("shifts", []) if "error" not in caskan_data else []

        # エスたまのスケジュール取得
        estama_data = await estama.get_schedule()
        estama_schedules = estama_data.get("schedules", []) if "error" not in estama_data else []

        # マップ化
        notion_map = {}
        for s in notion_shifts:
            if s["name"]:
                notion_map[s["name"]] = {
                    "start": s["start"],
                    "end": s["end"],
                    "room": s["room"],
                    "status": s["status"],
                }

        caskan_map = {}
        for s in caskan_shifts:
            name = s.get("name", "").strip()
            if name:
                caskan_map[name] = {
                    "start": s.get("start", ""),
                    "end": s.get("end", ""),
                    "time_raw": s.get("time_raw", ""),
                }

        estama_map = {}
        for s in estama_schedules:
            name = s.get("name", "").strip()
            if name:
                estama_map[name] = {
                    "start": s.get("start", ""),
                    "end": s.get("end", ""),
                }

        # 差異を検出
        all_names = set(notion_map.keys()) | set(caskan_map.keys()) | set(estama_map.keys())
        diffs = []
        matched = []

        for name in sorted(all_names):
            in_notion = name in notion_map
            in_caskan = name in caskan_map
            in_estama = name in estama_map

            if in_notion and not in_caskan and not in_estama:
                n = notion_map[name]
                diffs.append(
                    f"⚠️ {name}: Notionにあるがキャスカン・エスたま未登録\n"
                    f"   Notion: {n['start']}〜{n['end']} ({n['status']})"
                )
            elif in_notion and in_caskan and not in_estama:
                n = notion_map[name]
                diffs.append(
                    f"🟡 {name}: エスたま未登録\n"
                    f"   Notion: {n['start']}〜{n['end']}"
                )
            elif in_notion and not in_caskan and in_estama:
                n = notion_map[name]
                diffs.append(
                    f"🟡 {name}: キャスカン未登録\n"
                    f"   Notion: {n['start']}〜{n['end']}"
                )
            elif not in_notion and (in_caskan or in_estama):
                sources = []
                if in_caskan:
                    c = caskan_map[name]
                    sources.append(f"キャスカン: {c.get('time_raw') or c['start']+'〜'+c['end']}")
                if in_estama:
                    e = estama_map[name]
                    sources.append(f"エスたま: {e['start']}〜{e['end']}")
                diffs.append(
                    f"⚠️ {name}: Notionに未登録だが他システムに存在\n"
                    f"   {', '.join(sources)}"
                )
            elif in_notion and in_caskan and in_estama:
                n = notion_map[name]
                c = caskan_map[name]
                e = estama_map[name]

                time_issues = []
                if n["start"] != c["start"] or n["end"] != c["end"]:
                    time_issues.append(
                        f"キャスカン: {c.get('time_raw') or c['start']+'〜'+c['end']}"
                    )
                if n["start"] != e["start"] or n["end"] != e["end"]:
                    time_issues.append(
                        f"エスたま: {e['start']}〜{e['end']}"
                    )

                if time_issues:
                    diffs.append(
                        f"⚠️ {name}: 時刻がズレています\n"
                        f"   Notion: {n['start']}〜{n['end']}\n"
                        f"   {chr(10).join('   ' + t for t in time_issues)}"
                    )
                else:
                    matched.append(f"✅ {name}: {n['start']}〜{n['end']}")

        # 結果メッセージ
        text = f"📋 【シフト差異確認（Notionマスタ）】{date}\n\n"

        if not notion_map and not caskan_map and not estama_map:
            text += "全システムにシフト情報がありません。"
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
        "notion_get_shifts", "notion_get_pending",
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

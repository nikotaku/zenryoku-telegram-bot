"""
キャスカン月カレンダー画像生成モジュール
Pillowを使ってシフト・ルーム空き状況をカレンダー画像として生成する
"""

import io
import calendar
from datetime import date as date_type
from PIL import Image, ImageDraw, ImageFont

# フォントパス（複数の候補を試す）
import os

def _find_font(bold: bool = False) -> str:
    """利用可能な日本語フォントパスを返す"""
    candidates = []
    if bold:
        candidates = [
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
            "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",
            "/usr/share/fonts/noto-cjk/NotoSansCJK-Bold.ttc",
            "/usr/share/fonts/opentype/noto/NotoSansCJKjp-Bold.otf",
        ]
    else:
        candidates = [
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/opentype/noto/NotoSansCJKjp-Regular.otf",
        ]
    for path in candidates:
        if os.path.exists(path):
            return path
    return None  # フォールバック: デフォルトフォント使用

FONT_PATH = _find_font(bold=False)
FONT_BOLD_PATH = _find_font(bold=True)

# カラーパレット
COLOR_BG = (245, 247, 250)          # 背景
COLOR_HEADER = (40, 60, 100)        # ヘッダー背景（濃紺）
COLOR_HEADER_TEXT = (255, 255, 255) # ヘッダーテキスト
COLOR_WEEKDAY_HDR = (70, 90, 130)   # 曜日ヘッダー背景
COLOR_WEEKDAY_TEXT = (255, 255, 255)
COLOR_SAT_HDR = (100, 130, 200)     # 土曜ヘッダー
COLOR_SUN_HDR = (200, 80, 80)       # 日曜ヘッダー

COLOR_CELL_BG = (255, 255, 255)     # セル背景
COLOR_CELL_SAT = (235, 240, 255)    # 土曜セル
COLOR_CELL_SUN = (255, 235, 235)    # 日曜セル
COLOR_CELL_TODAY = (255, 250, 220)  # 今日セル
COLOR_CELL_BORDER = (200, 210, 225) # セル境界線
COLOR_DAY_NUM = (50, 50, 60)        # 日付数字
COLOR_DAY_SAT = (60, 80, 180)       # 土曜日付
COLOR_DAY_SUN = (180, 50, 50)       # 日曜日付
COLOR_DAY_TODAY = (200, 120, 0)     # 今日日付

# ルーム空き状況の色
COLOR_ROOM_AVAIL = (50, 170, 80)    # 空き（緑）
COLOR_ROOM_USED = (200, 60, 60)     # 使用中（赤）
COLOR_ROOM_AVAIL_BG = (220, 245, 225)
COLOR_ROOM_USED_BG = (250, 220, 220)

# セラピスト名の色
COLOR_CAST = (60, 80, 140)

# サイズ設定
CELL_W = 160       # セル幅
CELL_H = 120       # セル高さ
HEADER_H = 70      # タイトルヘッダー高さ
WEEKDAY_H = 36     # 曜日ヘッダー高さ
PADDING = 16       # 外側余白
COLS = 7           # 列数（月〜日）


def _load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    path = FONT_BOLD_PATH if bold else FONT_PATH
    if path is None:
        # 日本語フォントが見つからない場合はデフォルトフォントを使用
        return ImageFont.load_default()
    try:
        return ImageFont.truetype(path, size)
    except Exception:
        return ImageFont.load_default()


def _draw_rounded_rect(draw: ImageDraw.ImageDraw, xy, radius: int, fill, outline=None, width=1):
    """角丸矩形を描画"""
    x0, y0, x1, y1 = xy
    draw.rounded_rectangle([x0, y0, x1, y1], radius=radius, fill=fill, outline=outline, width=width)


def generate_calendar_image(monthly_data: dict) -> io.BytesIO:
    """
    get_monthly_shift() の戻り値からカレンダー画像を生成して BytesIO で返す。
    """
    year = monthly_data["year"]
    month = monthly_data["month"]
    room_map = monthly_data.get("room_map", {})
    days = monthly_data.get("days", {})
    all_room_ids = list(room_map.keys())

    # ルーム略称
    room_abbr = {}
    for rid, rname in room_map.items():
        abbr = rname.replace("room", "").replace("Room", "").strip()
        room_abbr[rid] = abbr

    # カレンダー配置を計算（月〜日の6週分グリッド）
    cal = calendar.monthcalendar(year, month)  # [[月,火,...,日], ...]
    weeks = len(cal)

    today = date_type.today()

    # 画像サイズ
    img_w = PADDING * 2 + CELL_W * COLS
    img_h = PADDING * 2 + HEADER_H + WEEKDAY_H + CELL_H * weeks

    img = Image.new("RGB", (img_w, img_h), COLOR_BG)
    draw = ImageDraw.Draw(img)

    # フォント
    font_title = _load_font(26, bold=True)
    font_weekday = _load_font(15, bold=True)
    font_day = _load_font(18, bold=True)
    font_room = _load_font(11, bold=False)
    font_cast = _load_font(12, bold=False)

    # ─── タイトルヘッダー ───
    draw.rectangle([0, 0, img_w, HEADER_H], fill=COLOR_HEADER)
    title_text = f"{year}年{month}月  シフト・ルーム空き状況"
    bbox = draw.textbbox((0, 0), title_text, font=font_title)
    tw = bbox[2] - bbox[0]
    draw.text(
        ((img_w - tw) // 2, (HEADER_H - (bbox[3] - bbox[1])) // 2),
        title_text, font=font_title, fill=COLOR_HEADER_TEXT
    )

    # ─── 曜日ヘッダー ───
    weekday_labels = ["月", "火", "水", "木", "金", "土", "日"]
    wy = HEADER_H
    for col, wd in enumerate(weekday_labels):
        x0 = PADDING + col * CELL_W
        x1 = x0 + CELL_W
        if wd == "土":
            bg = COLOR_SAT_HDR
        elif wd == "日":
            bg = COLOR_SUN_HDR
        else:
            bg = COLOR_WEEKDAY_HDR
        draw.rectangle([x0, wy, x1, wy + WEEKDAY_H], fill=bg)
        bbox = draw.textbbox((0, 0), wd, font=font_weekday)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        draw.text(
            (x0 + (CELL_W - tw) // 2, wy + (WEEKDAY_H - th) // 2),
            wd, font=font_weekday, fill=COLOR_WEEKDAY_TEXT
        )

    # ─── セル描画 ───
    for week_idx, week in enumerate(cal):
        for col, day_num in enumerate(week):
            x0 = PADDING + col * CELL_W
            y0 = HEADER_H + WEEKDAY_H + week_idx * CELL_H
            x1 = x0 + CELL_W
            y1 = y0 + CELL_H

            if day_num == 0:
                # 当月外（空白セル）
                draw.rectangle([x0, y0, x1, y1], fill=(230, 232, 238), outline=COLOR_CELL_BORDER, width=1)
                continue

            day_str = f"{year}-{month:02d}-{day_num:02d}"
            day_info = days.get(day_str, {"weekday": weekday_labels[col], "shifts": [], "rooms_used": []})
            shifts = day_info.get("shifts", [])
            rooms_used = set(day_info.get("rooms_used", []))

            # セル背景色
            is_today = (year == today.year and month == today.month and day_num == today.day)
            if is_today:
                cell_bg = COLOR_CELL_TODAY
            elif col == 5:  # 土曜
                cell_bg = COLOR_CELL_SAT
            elif col == 6:  # 日曜
                cell_bg = COLOR_CELL_SUN
            else:
                cell_bg = COLOR_CELL_BG

            draw.rectangle([x0, y0, x1, y1], fill=cell_bg, outline=COLOR_CELL_BORDER, width=1)

            # 今日マーカー（左上の角丸バッジ）
            if is_today:
                draw.ellipse([x0 + 4, y0 + 4, x0 + 20, y0 + 20], fill=COLOR_DAY_TODAY)

            # 日付数字
            day_text = str(day_num)
            if col == 5:
                day_color = COLOR_DAY_SAT
            elif col == 6:
                day_color = COLOR_DAY_SUN
            else:
                day_color = COLOR_DAY_NUM
            bbox = draw.textbbox((0, 0), day_text, font=font_day)
            tw = bbox[2] - bbox[0]
            draw.text((x0 + CELL_W - tw - 6, y0 + 4), day_text, font=font_day, fill=day_color)

            # ルーム空き状況バッジ
            room_y = y0 + 28
            room_x = x0 + 4
            for rid in all_room_ids:
                abbr = room_abbr.get(rid, rid)
                is_used = rid in rooms_used
                badge_color = COLOR_ROOM_USED if is_used else COLOR_ROOM_AVAIL
                badge_bg = COLOR_ROOM_USED_BG if is_used else COLOR_ROOM_AVAIL_BG
                mark = "×" if is_used else "○"
                badge_text = f"{mark}{abbr}"
                bbox = draw.textbbox((0, 0), badge_text, font=font_room)
                bw = bbox[2] - bbox[0] + 6
                bh = bbox[3] - bbox[1] + 4
                if room_x + bw > x1 - 2:
                    room_x = x0 + 4
                    room_y += bh + 2
                _draw_rounded_rect(draw, [room_x, room_y, room_x + bw, room_y + bh], radius=3, fill=badge_bg, outline=badge_color, width=1)
                draw.text((room_x + 3, room_y + 2), badge_text, font=font_room, fill=badge_color)
                room_x += bw + 3

            # セラピスト名（シフトあり）
            if shifts:
                cast_y = y0 + CELL_H - 4
                for s in shifts:
                    abbr = room_abbr.get(s["room_id"], s["room_id"])
                    cast_text = f"{s['name']}({abbr})"
                    bbox = draw.textbbox((0, 0), cast_text, font=font_cast)
                    th = bbox[3] - bbox[1]
                    cast_y -= th + 2
                    draw.text((x0 + 4, cast_y), cast_text, font=font_cast, fill=COLOR_CAST)

    # ─── ルーム凡例 ───
    # 画像下部に凡例を追加
    legend_h = 36
    new_img = Image.new("RGB", (img_w, img_h + legend_h), COLOR_BG)
    new_img.paste(img, (0, 0))
    draw2 = ImageDraw.Draw(new_img)
    draw2.rectangle([0, img_h, img_w, img_h + legend_h], fill=COLOR_HEADER)

    font_legend = _load_font(13, bold=False)
    legend_parts = []
    for rid, rname in room_map.items():
        abbr = room_abbr.get(rid, rid)
        legend_parts.append(f"○{abbr}=空き  ×{abbr}=使用中")
    legend_text = "  |  ".join(legend_parts)
    bbox = draw2.textbbox((0, 0), legend_text, font=font_legend)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    draw2.text(
        ((img_w - tw) // 2, img_h + (legend_h - th) // 2),
        legend_text, font=font_legend, fill=COLOR_HEADER_TEXT
    )

    # BytesIOに保存
    buf = io.BytesIO()
    new_img.save(buf, format="PNG", optimize=True)
    buf.seek(0)
    return buf

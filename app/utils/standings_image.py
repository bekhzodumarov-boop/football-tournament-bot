"""
Генерация PNG-картинки турнирной таблицы (Pillow).
Показывает: групповой этап (таблица) + плей-офф (сетка матчей).
"""
from __future__ import annotations
import io
from PIL import Image, ImageDraw, ImageFont

# ─── Цвета ─────────────────────────────────────────────────────────────────
BG          = (18, 18, 30)        # фон
CARD        = (28, 28, 44)        # карточка секции
HEADER_BG   = (40, 100, 180)      # шапка таблицы
GOLD        = (255, 200,  50)
SILVER      = (192, 192, 192)
BRONZE      = (180, 100,  30)
WHITE       = (255, 255, 255)
GRAY        = (160, 160, 180)
GREEN       = ( 60, 180,  80)
RED_C       = (220,  60,  60)
DRAW_C      = (200, 160,  50)
DIVIDER     = ( 50,  50,  70)

EMOJI_COLOR_MAP = {
    "🔴": (220,  60,  60),
    "🔵": ( 60, 100, 220),
    "🟢": ( 60, 180,  80),
    "🟡": (220, 200,  50),
    "🟠": (220, 130,  50),
    "⚪": (210, 210, 210),
    "⚫": (100, 100, 100),
    "🟤": (150,  90,  50),
    "🟣": (150,  60, 200),
    "🔶": (220, 140,  50),
    "🔷": ( 60, 130, 220),
    "🔸": (230, 160,  80),
    "🔹": ( 80, 150, 230),
}


def _team_color(emoji: str) -> tuple[int, int, int]:
    for e, c in EMOJI_COLOR_MAP.items():
        if e in emoji:
            return c
    return (120, 120, 150)


def _load_font(size: int, bold: bool = False):
    """Попытка загрузить системный шрифт, fallback на дефолт Pillow."""
    candidates = [
        "C:/Windows/Fonts/segoeui.ttf",
        "C:/Windows/Fonts/arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    ]
    if bold:
        candidates = [
            "C:/Windows/Fonts/segoeuib.ttf",
            "C:/Windows/Fonts/arialbd.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        ] + candidates
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except (IOError, OSError):
            pass
    return ImageFont.load_default()


def generate_standings_image(
    game_day_name: str,
    game_day_date: str,
    standings: list[dict],          # [{name, emoji, W, D, L, GF, GA, Pts, GP}]
    playoff_matches: list[dict],    # [{stage, home, away, score_h, score_a, finished}]
    top_scorers: list[tuple],       # [(name, count), ...]
) -> bytes:
    """Генерирует PNG и возвращает bytes."""

    W = 820
    PAD = 24
    ROW_H = 44
    SECTION_GAP = 18

    # ── Шрифты ─────────────────────────────────────────────────────────────
    fnt_title  = _load_font(26, bold=True)
    fnt_sub    = _load_font(18)
    fnt_hdr    = _load_font(16, bold=True)
    fnt_row    = _load_font(18)
    fnt_bold   = _load_font(18, bold=True)
    fnt_small  = _load_font(15)

    # ── Предварительно считаем высоту ──────────────────────────────────────
    section_heights = []
    # заголовок
    section_heights.append(70)
    # таблица группового этапа
    if standings:
        section_heights.append(SECTION_GAP + ROW_H + 2 + len(standings) * ROW_H)
    # плей-офф
    if playoff_matches:
        section_heights.append(SECTION_GAP + 30 + len(playoff_matches) * ROW_H)
    # бомбардиры
    if top_scorers:
        section_heights.append(SECTION_GAP + 30 + len(top_scorers[:5]) * 30)
    # отступ снизу
    section_heights.append(PAD)

    H = sum(section_heights) + PAD * 2
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)

    y = PAD

    # ── Заголовок ──────────────────────────────────────────────────────────
    d.text((W // 2, y + 4), "🏆 " + game_day_name, font=fnt_title, fill=GOLD, anchor="mt")
    y += 34
    d.text((W // 2, y), game_day_date, font=fnt_sub, fill=GRAY, anchor="mt")
    y += 36

    # ── Групповой этап ─────────────────────────────────────────────────────
    if standings:
        y += SECTION_GAP
        d.rounded_rectangle([PAD, y, W - PAD, y + ROW_H], radius=8, fill=HEADER_BG)
        cols = [
            (PAD + 8,  "№"),
            (PAD + 44, "Команда"),
            (W - 260,  "И"),
            (W - 220,  "В"),
            (W - 180,  "Н"),
            (W - 140,  "П"),
            (W - 100,  "ГЗ"),
            (W - 60,   "ГП"),
            (W - PAD - 8, "О"),
        ]
        for cx, lbl in cols:
            anchor = "lt" if lbl == "Команда" else ("rt" if cx == W - PAD - 8 else "mt")
            d.text((cx, y + ROW_H // 2), lbl, font=fnt_hdr, fill=WHITE, anchor=anchor)
        y += ROW_H

        place_colors = {1: GOLD, 2: SILVER, 3: BRONZE}
        for i, s in enumerate(standings, 1):
            row_bg = (35, 35, 55) if i % 2 == 0 else CARD
            d.rounded_rectangle([PAD, y, W - PAD, y + ROW_H - 2], radius=6, fill=row_bg)
            tc = _team_color(s.get("emoji", ""))
            d.rounded_rectangle([PAD, y, PAD + 5, y + ROW_H - 2], radius=3, fill=tc)
            place_clr = place_colors.get(i, WHITE)
            d.text((PAD + 8, y + ROW_H // 2), str(i), font=fnt_bold, fill=place_clr, anchor="lm")
            name_short = s["name"][:16]
            d.text((PAD + 44, y + ROW_H // 2), name_short, font=fnt_row, fill=WHITE, anchor="lm")
            vals = [s["GP"], s["W"], s["D"], s["L"], s["GF"], s["GA"]]
            xs   = [W - 260, W - 220, W - 180, W - 140, W - 100, W - 60]
            for cx, v in zip(xs, vals):
                d.text((cx, y + ROW_H // 2), str(v), font=fnt_row, fill=GRAY, anchor="mm")
            pts_clr = GREEN if i == 1 else (GOLD if i <= 2 else WHITE)
            d.text((W - PAD - 8, y + ROW_H // 2), str(s["Pts"]), font=fnt_bold, fill=pts_clr, anchor="rm")
            y += ROW_H

    # ── Плей-офф ───────────────────────────────────────────────────────────
    if playoff_matches:
        y += SECTION_GAP
        d.text((PAD + 8, y + 6), "Плей-офф", font=fnt_hdr, fill=GOLD)
        y += 30
        stage_ru = {
            "semifinal":   "Полуфинал",
            "third_place": "За 3-е место",
            "final":       "Финал",
        }
        for m in playoff_matches:
            row_bg = CARD
            d.rounded_rectangle([PAD, y, W - PAD, y + ROW_H - 2], radius=6, fill=row_bg)
            label = stage_ru.get(m["stage"], m["stage"])
            d.text((PAD + 14, y + ROW_H // 2), label, font=fnt_small, fill=GRAY, anchor="lm")
            score_str = f"{m['score_h']}:{m['score_a']}"
            center_x = W // 2
            if m["finished"]:
                if m["score_h"] > m["score_a"]:
                    home_clr, away_clr = GREEN, RED_C
                elif m["score_h"] < m["score_a"]:
                    home_clr, away_clr = RED_C, GREEN
                else:
                    home_clr = away_clr = DRAW_C
            else:
                home_clr = away_clr = GRAY
            d.text((center_x - 10, y + ROW_H // 2), m["home"], font=fnt_bold, fill=home_clr, anchor="rm")
            d.text((center_x, y + ROW_H // 2), score_str, font=fnt_bold, fill=WHITE, anchor="mm")
            d.text((center_x + 10, y + ROW_H // 2), m["away"], font=fnt_bold, fill=away_clr, anchor="lm")
            y += ROW_H

    # ── Бомбардиры ─────────────────────────────────────────────────────────
    if top_scorers:
        y += SECTION_GAP
        d.text((PAD + 8, y + 4), "⚽ Лучшие бомбардиры", font=fnt_hdr, fill=WHITE)
        y += 30
        medals_clr = [GOLD, SILVER, BRONZE, WHITE, WHITE]
        for i, (name, cnt) in enumerate(top_scorers[:5]):
            clr = medals_clr[i]
            text = f"{i+1}. {name} — {cnt} гол{'а' if 2<=cnt<=4 else ('ов' if cnt>=5 else '')}"
            d.text((PAD + 14, y + 8), text, font=fnt_row, fill=clr)
            y += 30

    # ── Нижняя подпись ─────────────────────────────────────────────────────
    d.text((W // 2, H - 14), "@football_manager_uz_bot", font=fnt_small, fill=GRAY, anchor="mb")

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    buf.seek(0)
    return buf.read()

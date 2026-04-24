"""
Генерация PNG турнирной таблицы (Pillow).
Секции: групповой этап, плей-офф, бомбардиры.
Без эмодзи — только текст и цвет, корректно рендерится с DejaVu на Linux.
"""
from __future__ import annotations
import io
from PIL import Image, ImageDraw, ImageFont

# ── Цвета ──────────────────────────────────────────────────────────────────
BG          = (13,  17,  28)
CARD        = (22,  28,  45)
CARD_ALT    = (18,  24,  38)
HEADER_BG   = (30,  80, 160)
ACCENT      = (50, 120, 220)
SECTION_HDR = (25,  35,  58)
GOLD        = (255, 195,  40)
SILVER      = (185, 195, 210)
BRONZE      = (190, 120,  50)
WHITE       = (240, 245, 255)
GRAY        = (130, 145, 170)
GREEN       = ( 55, 190,  90)
RED_C       = (210,  65,  65)
DRAW_C      = (200, 165,  50)
DIVIDER     = ( 35,  45,  65)

EMOJI_COLOR_MAP = {
    "🔴": (210,  60,  60),
    "🔵": ( 55, 110, 220),
    "🟢": ( 55, 185,  85),
    "🟡": (215, 185,  40),
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
        if e in (emoji or ""):
            return c
    return (100, 110, 140)


def _load_font(size: int, bold: bool = False):
    candidates = []
    if bold:
        candidates = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
            "C:/Windows/Fonts/segoeuib.ttf",
            "C:/Windows/Fonts/arialbd.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        ]
    else:
        candidates = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
            "C:/Windows/Fonts/segoeui.ttf",
            "C:/Windows/Fonts/arial.ttf",
        ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except (IOError, OSError):
            pass
    return ImageFont.load_default()


def _section_header(d: ImageDraw.Draw, y: int, w: int, pad: int,
                    text: str, fnt) -> int:
    """Рисует заголовок секции, возвращает новый y."""
    d.rounded_rectangle([pad, y, w - pad, y + 36], radius=8, fill=SECTION_HDR)
    d.rounded_rectangle([pad, y, pad + 4, y + 36], radius=2, fill=ACCENT)
    d.text((pad + 16, y + 18), text, font=fnt, fill=GOLD, anchor="lm")
    return y + 36


def generate_standings_image(
    game_day_name: str,
    game_day_date: str,
    standings: list[dict],        # [{name, emoji, W, D, L, GF, GA, Pts, GP}]
    playoff_matches: list[dict],  # [{stage, home, away, score_h, score_a, finished}]
    top_scorers: list[tuple],     # [(name, count), ...]
) -> bytes:
    """Генерирует PNG и возвращает bytes."""

    W   = 1000
    PAD = 28
    ROW = 52
    GAP = 20

    fnt_title = _load_font(34, bold=True)
    fnt_sub   = _load_font(19)
    fnt_hdr   = _load_font(17, bold=True)
    fnt_row   = _load_font(20)
    fnt_bold  = _load_font(20, bold=True)
    fnt_win   = _load_font(23, bold=True)   # T-036: победитель плей-офф
    fnt_small = _load_font(17)
    fnt_sec   = _load_font(16, bold=True)

    # ── Вычисляем высоту ──────────────────────────────────────────────────
    H = PAD + 88  # заголовок
    if standings:
        H += GAP + 40 + ROW + len(standings) * ROW
    if playoff_matches:
        H += GAP + 40 + len(playoff_matches) * ROW
    if top_scorers:
        H += GAP + 40 + len(top_scorers[:5]) * 36
    H += PAD + 34  # подпись снизу

    img = Image.new("RGB", (W, H), BG)
    d   = ImageDraw.Draw(img)

    # Тонкая акцентная линия сверху
    for i in range(3):
        d.line([(0, i), (W, i)], fill=ACCENT)

    y = PAD + 8

    # ── Заголовок ─────────────────────────────────────────────────────────
    d.text((W // 2, y), game_day_name, font=fnt_title, fill=GOLD, anchor="mt")
    y += 42
    d.text((W // 2, y), game_day_date, font=fnt_sub, fill=GRAY, anchor="mt")
    y += 38

    # ── Групповой этап ────────────────────────────────────────────────────
    if standings:
        y += GAP
        y = _section_header(d, y, W, PAD, "ГРУППОВОЙ ЭТАП", fnt_sec)
        y += 4

        # Шапка таблицы
        d.rounded_rectangle([PAD, y, W - PAD, y + ROW], radius=8, fill=HEADER_BG)
        cols_x = [PAD+10, PAD+52, W-340, W-290, W-240, W-190, W-140, W-88, W-PAD-8]
        cols_l = ["№",  "Команда", "И", "В", "Н", "П", "ГЗ", "ГП", "О"]
        for cx, lbl in zip(cols_x, cols_l):
            anc = "lm" if lbl in ("№", "Команда") else ("rm" if lbl == "О" else "mm")
            d.text((cx, y + ROW // 2), lbl, font=fnt_hdr, fill=WHITE, anchor=anc)
        y += ROW

        place_clr = {1: GOLD, 2: SILVER, 3: BRONZE}
        for i, s in enumerate(standings, 1):
            bg = CARD if i % 2 else CARD_ALT
            d.rounded_rectangle([PAD, y, W - PAD, y + ROW - 2], radius=6, fill=bg)
            tc = _team_color(s.get("emoji", ""))
            # Цветная полоска слева
            d.rounded_rectangle([PAD, y + 4, PAD + 5, y + ROW - 6], radius=3, fill=tc)
            # Место
            pclr = place_clr.get(i, GRAY)
            d.text((PAD + 10, y + ROW // 2), str(i), font=fnt_bold, fill=pclr, anchor="lm")
            # Цветной кружок
            cx0, cy0 = PAD + 38, y + ROW // 2
            d.ellipse([cx0-10, cy0-10, cx0+10, cy0+10], fill=tc)
            # Название команды
            name_short = s["name"][:18]
            d.text((PAD + 56, y + ROW // 2), name_short, font=fnt_row, fill=WHITE, anchor="lm")
            # Статистика
            vals = [s["GP"], s["W"], s["D"], s["L"], s["GF"], s["GA"]]
            xs   = [W-340, W-290, W-240, W-190, W-140, W-88]
            for cx, v in zip(xs, vals):
                d.text((cx, y + ROW // 2), str(v), font=fnt_row, fill=GRAY, anchor="mm")
            # Очки
            pts_clr = GOLD if i == 1 else (SILVER if i == 2 else WHITE)
            d.text((W - PAD - 8, y + ROW // 2), str(s["Pts"]), font=fnt_bold, fill=pts_clr, anchor="rm")
            y += ROW

    # ── Плей-офф ─────────────────────────────────────────────────────────
    if playoff_matches:
        y += GAP
        y = _section_header(d, y, W, PAD, "ПЛЕЙ-ОФФ", fnt_sec)
        y += 4

        stage_ru = {
            "semifinal":   "Полуфинал",
            "third_place": "За 3-е место",
            "final":       "Финал",
        }
        for m in playoff_matches:
            d.rounded_rectangle([PAD, y, W - PAD, y + ROW - 2], radius=6, fill=CARD)
            label = stage_ru.get(m["stage"], m["stage"])
            d.text((PAD + 14, y + ROW // 2), label, font=fnt_small, fill=GRAY, anchor="lm")

            cx = W // 2
            finished = m.get("finished", False)
            sh, sa = m["score_h"], m["score_a"]

            # T-036: цвет по эмодзи команды, победитель — bold+крупный, проигравший — тусклый
            home_clr = _team_color(m.get("home_emoji", ""))
            away_clr = _team_color(m.get("away_emoji", ""))

            def _dim(c: tuple) -> tuple:
                return (int(c[0]*0.55), int(c[1]*0.55), int(c[2]*0.55))

            if finished:
                if sh > sa:
                    hc, ac = home_clr, _dim(away_clr)
                    hf, af = fnt_win, fnt_small
                elif sh < sa:
                    hc, ac = _dim(home_clr), away_clr
                    hf, af = fnt_small, fnt_win
                else:  # ничья
                    hc, ac = home_clr, away_clr
                    hf = af = fnt_bold
            else:
                hc = ac = GRAY
                hf = af = fnt_bold

            home = m["home"][:14]
            away = m["away"][:14]
            score = f"  {sh} : {sa}  "
            d.text((cx - 80, y + ROW // 2), home,  font=hf,       fill=hc,    anchor="rm")
            d.text((cx,      y + ROW // 2), score, font=fnt_bold,  fill=WHITE, anchor="mm")
            d.text((cx + 80, y + ROW // 2), away,  font=af,        fill=ac,    anchor="lm")
            y += ROW

    # ── Бомбардиры ───────────────────────────────────────────────────────
    if top_scorers:
        y += GAP
        y = _section_header(d, y, W, PAD, "БОМБАРДИРЫ", fnt_sec)
        y += 6

        medals_txt = ["1.", "2.", "3.", "4.", "5."]
        medals_clr = [GOLD, SILVER, BRONZE, WHITE, WHITE]

        for i, (name, cnt) in enumerate(top_scorers[:5]):
            bg = CARD if i % 2 == 0 else CARD_ALT
            d.rounded_rectangle([PAD, y, W - PAD, y + 34], radius=6, fill=bg)
            clr = medals_clr[i]
            d.text((PAD + 14, y + 17), medals_txt[i], font=fnt_bold, fill=clr, anchor="lm")
            d.text((PAD + 52, y + 17), name,          font=fnt_row,  fill=WHITE, anchor="lm")
            suffix = "гол" if cnt == 1 else ("гола" if 2 <= cnt <= 4 else "голов")
            d.text((W - PAD - 12, y + 17), f"{cnt} {suffix}", font=fnt_bold, fill=clr, anchor="rm")
            y += 34

    # ── Подпись ──────────────────────────────────────────────────────────
    y += 14
    d.line([(PAD, y), (W - PAD, y)], fill=DIVIDER, width=1)
    y += 12
    d.text((W // 2, y + 8), "@football_manager_uz_bot", font=fnt_small, fill=GRAY, anchor="mt")

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    buf.seek(0)
    return buf.read()

"""
Экспорт статистики турнира в Google Sheets.

Требует переменных окружения:
  GOOGLE_CREDENTIALS_JSON  — JSON сервисного аккаунта (строкой)
  GOOGLE_SHEET_ID          — ID таблицы из URL: .../spreadsheets/d/<ID>/...

Листы в таблице:
  📊 Таблица     — итоговые очки команд
  ⚽ Матчи       — все сыгранные матчи
  👥 Игроки      — статистика каждого игрока
"""
import json
from datetime import datetime

import gspread
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database.models import (
    GameDay, GameDayStatus, Match, MatchStatus, Team,
    Goal, GoalType, Card, CardType, Player, Attendance, AttendanceResponse,
)


def _get_client() -> gspread.Client:
    """Создать gspread-клиент из JSON в env var."""
    creds_dict = json.loads(settings.GOOGLE_CREDENTIALS_JSON)
    return gspread.service_account_from_dict(creds_dict)


async def export_to_sheets(session: AsyncSession) -> str:
    """
    Экспортирует данные в Google Sheets.
    Возвращает URL таблицы.
    """
    gc = _get_client()
    sh = gc.open_by_key(settings.GOOGLE_SHEET_ID)

    # ── Загрузить все данные ────────────────────────────────────────────────

    # Игровые дни
    gd_result = await session.execute(
        select(GameDay).order_by(GameDay.scheduled_at.desc())
    )
    game_days = gd_result.scalars().all()
    latest_gd = game_days[0] if game_days else None

    # Матчи (только завершённые)
    matches_result = await session.execute(
        select(Match)
        .options(
            selectinload(Match.team_home),
            selectinload(Match.team_away),
            selectinload(Match.goals).selectinload(Goal.player),
            selectinload(Match.cards).selectinload(Card.player),
        )
        .where(Match.status == MatchStatus.FINISHED)
        .order_by(Match.finished_at)
    )
    matches = matches_result.scalars().all()

    # Игроки
    players_result = await session.execute(
        select(Player).order_by(Player.rating.desc())
    )
    players = players_result.scalars().all()

    # Голы для статистики игроков
    goals_result = await session.execute(
        select(Goal).options(selectinload(Goal.player))
    )
    goals = goals_result.scalars().all()
    goals_by_player: dict[int, int] = {}
    for g in goals:
        if g.goal_type == GoalType.GOAL:
            goals_by_player[g.player_id] = goals_by_player.get(g.player_id, 0) + 1

    # Карточки
    cards_result = await session.execute(select(Card))
    cards = cards_result.scalars().all()
    yellow_by_player: dict[int, int] = {}
    red_by_player: dict[int, int] = {}
    for c in cards:
        if c.card_type == CardType.YELLOW:
            yellow_by_player[c.player_id] = yellow_by_player.get(c.player_id, 0) + 1
        else:
            red_by_player[c.player_id] = red_by_player.get(c.player_id, 0) + 1

    updated_at = datetime.now().strftime("%d.%m.%Y %H:%M")

    # ── Лист 1: Таблица ────────────────────────────────────────────────────
    _update_sheet(sh, "📊 Таблица", _build_standings(matches, updated_at))

    # ── Лист 2: Матчи ──────────────────────────────────────────────────────
    _update_sheet(sh, "⚽ Матчи", _build_matches(matches, updated_at))

    # ── Лист 3: Игроки ─────────────────────────────────────────────────────
    _update_sheet(sh, "👥 Игроки",
                  _build_players(players, goals_by_player,
                                 yellow_by_player, red_by_player, updated_at))

    return f"https://docs.google.com/spreadsheets/d/{settings.GOOGLE_SHEET_ID}"


def _update_sheet(sh: gspread.Spreadsheet, title: str, rows: list[list]):
    """Создать лист если нет, очистить и записать данные."""
    try:
        ws = sh.worksheet(title)
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title=title, rows=200, cols=20)
    ws.clear()
    if rows:
        ws.update(rows, "A1")
        # Жирный заголовок
        ws.format("1:1", {"textFormat": {"bold": True},
                          "backgroundColor": {"red": 0.2, "green": 0.2, "blue": 0.2}})


def _build_standings(matches: list, updated_at: str) -> list[list]:
    stats: dict[int, dict] = {}
    for m in matches:
        for team, gf, ga in [
            (m.team_home, m.score_home, m.score_away),
            (m.team_away, m.score_away, m.score_home),
        ]:
            if team.id not in stats:
                stats[team.id] = {
                    "name": team.name, "gp": 0,
                    "w": 0, "d": 0, "l": 0, "gf": 0, "ga": 0,
                }
            s = stats[team.id]
            s["gp"] += 1; s["gf"] += gf; s["ga"] += ga
            if gf > ga: s["w"] += 1
            elif gf == ga: s["d"] += 1
            else: s["l"] += 1

    for s in stats.values():
        s["pts"] = s["w"] * 3 + s["d"]

    table = sorted(stats.values(), key=lambda x: (-x["pts"], -(x["gf"] - x["ga"])))

    rows = [[f"Обновлено: {updated_at}"]]
    rows.append([])
    rows.append(["#", "Команда", "И", "В", "Н", "П", "ГЗ", "ГП", "Разница", "Очки"])
    for i, s in enumerate(table, 1):
        rows.append([
            i, s["name"], s["gp"], s["w"], s["d"], s["l"],
            s["gf"], s["ga"], s["gf"] - s["ga"], s["pts"],
        ])
    return rows


def _build_matches(matches: list, updated_at: str) -> list[list]:
    rows = [[f"Обновлено: {updated_at}"]]
    rows.append([])
    rows.append(["Дата", "Команда 1", "Счёт", "Команда 2", "Голы", "Карточки"])
    for m in matches:
        date = m.finished_at.strftime("%d.%m.%Y %H:%M") if m.finished_at else "—"
        goals_str = ", ".join(
            f"{g.player.name}" + (" (авт.)" if g.goal_type == GoalType.OWN_GOAL else "")
            for g in sorted(m.goals, key=lambda x: x.scored_at)
        )
        cards_str = ", ".join(
            ("🟡" if c.card_type == CardType.YELLOW else "🔴") + c.player.name
            for c in sorted(m.cards, key=lambda x: x.issued_at)
        )
        rows.append([
            date,
            m.team_home.name,
            f"{m.score_home}:{m.score_away}",
            m.team_away.name,
            goals_str or "—",
            cards_str or "—",
        ])
    return rows


def _build_players(players, goals_by_player, yellow_by_player,
                   red_by_player, updated_at: str) -> list[list]:
    from app.database.models import POSITION_LABELS
    rows = [[f"Обновлено: {updated_at}"]]
    rows.append([])
    rows.append(["#", "Имя", "Позиция", "Рейтинг", "Игр", "Голы", "ЖК", "КК", "Надёжность %"])
    for i, p in enumerate(players, 1):
        pos = POSITION_LABELS.get(p.position, p.position)
        rows.append([
            i, p.name, pos, round(p.rating, 1),
            p.games_played,
            goals_by_player.get(p.id, 0),
            yellow_by_player.get(p.id, 0),
            red_by_player.get(p.id, 0),
            round(p.reliability_pct, 0),
        ])
    return rows

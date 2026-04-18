"""
Хендлеры для роли Разработчик бота.
Команда /dev — глобальная аналитика использования бота.
Доступна только пользователям из DEVELOPER_IDS (или ADMIN_IDS).
"""
import logging
from datetime import date, timedelta

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy import func, select, distinct
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database.models import (
    League, Player, PlayerStatus, GameDay, GameDayStatus,
    Match, MatchStatus, UserActivity, PlayerLeague,
)

logger = logging.getLogger(__name__)
router = Router()


@router.message(Command("dev"))
async def cmd_dev(message: Message, session: AsyncSession):
    """Глобальная аналитика бота для разработчика."""
    if not settings.is_developer(message.from_user.id):
        await message.answer("⛔ Нет доступа.")
        return

    today = date.today()
    week_ago = today - timedelta(days=7)
    month_ago = today - timedelta(days=30)

    # ── DAU / WAU / MAU ──────────────────────────────
    dau_res = await session.execute(
        select(func.count(distinct(UserActivity.telegram_id)))
        .where(UserActivity.activity_date == today)
    )
    dau = dau_res.scalar() or 0

    wau_res = await session.execute(
        select(func.count(distinct(UserActivity.telegram_id)))
        .where(UserActivity.activity_date >= week_ago)
    )
    wau = wau_res.scalar() or 0

    mau_res = await session.execute(
        select(func.count(distinct(UserActivity.telegram_id)))
        .where(UserActivity.activity_date >= month_ago)
    )
    mau = mau_res.scalar() or 0

    # ── Лиги ─────────────────────────────────────────
    leagues_total = (await session.execute(
        select(func.count()).select_from(League)
    )).scalar() or 0

    leagues_active = (await session.execute(
        select(func.count()).select_from(League).where(League.is_active == True)
    )).scalar() or 0

    # ── Игроки ───────────────────────────────────────
    players_total = (await session.execute(
        select(func.count()).select_from(Player)
    )).scalar() or 0

    players_active = (await session.execute(
        select(func.count()).select_from(Player)
        .where(Player.status == PlayerStatus.ACTIVE)
    )).scalar() or 0

    # Новые игроки за сегодня / неделю / месяц
    from sqlalchemy import cast, Date as SADate
    new_today = (await session.execute(
        select(func.count()).select_from(Player)
        .where(cast(Player.created_at, SADate) == today)
    )).scalar() or 0

    new_week = (await session.execute(
        select(func.count()).select_from(Player)
        .where(cast(Player.created_at, SADate) >= week_ago)
    )).scalar() or 0

    new_month = (await session.execute(
        select(func.count()).select_from(Player)
        .where(cast(Player.created_at, SADate) >= month_ago)
    )).scalar() or 0

    # ── Игровые дни ──────────────────────────────────
    gd_total = (await session.execute(
        select(func.count()).select_from(GameDay)
    )).scalar() or 0

    gd_finished = (await session.execute(
        select(func.count()).select_from(GameDay)
        .where(GameDay.status == GameDayStatus.FINISHED)
    )).scalar() or 0

    gd_active = (await session.execute(
        select(func.count()).select_from(GameDay)
        .where(GameDay.status.in_([GameDayStatus.ANNOUNCED, GameDayStatus.IN_PROGRESS]))
    )).scalar() or 0

    # ── Матчи ────────────────────────────────────────
    matches_total = (await session.execute(
        select(func.count()).select_from(Match)
    )).scalar() or 0

    matches_finished = (await session.execute(
        select(func.count()).select_from(Match)
        .where(Match.status == MatchStatus.FINISHED)
    )).scalar() or 0

    # ── Топ лиги по игрокам (через PlayerLeague — точный подсчёт) ──────────────────────────
    top_leagues_res = await session.execute(
        select(League.name, func.count(PlayerLeague.player_id).label("cnt"))
        .join(PlayerLeague, PlayerLeague.league_id == League.id, isouter=True)
        .group_by(League.id, League.name)
        .order_by(func.count(PlayerLeague.player_id).desc())
        .limit(5)
    )
    top_leagues = top_leagues_res.all()

    # ── Формируем сообщение ───────────────────────────
    top_lines = "\n".join(
        f"  {i+1}. {row.name} — {row.cnt} игр."
        for i, row in enumerate(top_leagues)
    )

    text = (
        "🤖 <b>Dev Dashboard — Football Bot</b>\n"
        f"📅 Дата: {today.strftime('%d.%m.%Y')}\n\n"

        "📊 <b>Активность пользователей</b>\n"
        f"  DAU (сегодня): <b>{dau}</b>\n"
        f"  WAU (7 дней): <b>{wau}</b>\n"
        f"  MAU (30 дней): <b>{mau}</b>\n\n"

        "🏆 <b>Лиги</b>\n"
        f"  Всего: <b>{leagues_total}</b>  |  Активных: <b>{leagues_active}</b>\n\n"

        "👥 <b>Игроки</b>\n"
        f"  Всего: <b>{players_total}</b>  |  Активных: <b>{players_active}</b>\n"
        f"  Новые: сегодня <b>{new_today}</b> / неделя <b>{new_week}</b> / месяц <b>{new_month}</b>\n\n"

        "📅 <b>Игровые дни</b>\n"
        f"  Всего: <b>{gd_total}</b>  |  Завершено: <b>{gd_finished}</b>  |  Активных: <b>{gd_active}</b>\n\n"

        "⚽ <b>Матчи</b>\n"
        f"  Всего: <b>{matches_total}</b>  |  Сыграно: <b>{matches_finished}</b>\n\n"

        "🥇 <b>Топ лиг по игрокам</b>\n"
        f"{top_lines if top_lines else '  — нет данных —'}"
    )

    await message.answer(text, parse_mode="HTML")

"""
Хендлеры для Telegram-группы лиги.
Бот отвечает на команды только в GROUP_CHAT_ID.
"""
import logging
from datetime import datetime, timedelta

from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database.models import (
    GameDay, GameDayStatus, Attendance, AttendanceResponse,
    Player, PlayerLeague,
)
from app.keyboards.game_day import join_game_kb

logger = logging.getLogger(__name__)

router = Router()


def _is_league_group(chat_id: int) -> bool:
    if not settings.GROUP_CHAT_ID:
        return False
    try:
        return chat_id == int(settings.GROUP_CHAT_ID)
    except ValueError:
        return False


async def _next_game_for_group(session: AsyncSession) -> GameDay | None:
    """Ближайшая анонсированная игра (любой лиги)."""
    cutoff = datetime.now() - timedelta(hours=6)
    res = await session.execute(
        select(GameDay)
        .options(selectinload(GameDay.attendances))
        .where(GameDay.status.in_([
            GameDayStatus.ANNOUNCED,
            GameDayStatus.CLOSED,
            GameDayStatus.IN_PROGRESS,
        ]))
        .where(GameDay.scheduled_at >= cutoff)
        .order_by(GameDay.scheduled_at)
        .limit(1)
    )
    return res.scalar_one_or_none()


def _group_game_text(gd: GameDay) -> str:
    registered = sum(1 for a in gd.attendances if a.response == AttendanceResponse.YES)
    waitlist = sum(1 for a in gd.attendances if a.response == AttendanceResponse.WAITLIST)
    free = max(0, gd.player_limit - registered)

    status_line = ""
    if gd.status == GameDayStatus.CLOSED:
        status_line = "\n🔒 <b>Запись закрыта</b>"
    elif free == 0:
        status_line = f"\n⏳ Свободных мест нет — в резерве: {waitlist} чел."
    else:
        status_line = f"\n✅ Свободных мест: {free}"

    return (
        f"⚽ <b>{gd.display_name}</b>\n\n"
        f"📅 {gd.scheduled_at.strftime('%d.%m.%Y %H:%M')}\n"
        f"📍 {gd.location}\n"
        f"👥 Записались: {registered}/{gd.player_limit}"
        + status_line
        + "\n\n👇 Записаться через бот:"
    )


@router.message(Command("start", "game", "игра", "games"))
async def group_cmd_game(message: Message, session: AsyncSession):
    if not _is_league_group(message.chat.id):
        return

    gd = await _next_game_for_group(session)
    if not gd:
        await message.reply("Ближайших игр нет. Следи за анонсами! ⚽")
        return

    can_join = gd.status == GameDayStatus.ANNOUNCED and gd.registration_open
    await message.reply(
        _group_game_text(gd),
        reply_markup=join_game_kb(gd.id, can_join, "ru", webapp_url=settings.WEBAPP_URL),
        parse_mode="HTML",
    )


@router.message(Command("players", "состав", "список"))
async def group_cmd_players(message: Message, session: AsyncSession):
    if not _is_league_group(message.chat.id):
        return

    gd = await _next_game_for_group(session)
    if not gd:
        await message.reply("Ближайших игр нет.")
        return

    yes_atts = [a for a in gd.attendances if a.response == AttendanceResponse.YES]
    wait_atts = [a for a in gd.attendances if a.response == AttendanceResponse.WAITLIST]

    res = await session.execute(
        select(Player)
        .where(Player.id.in_([a.player_id for a in yes_atts]))
    )
    players_map = {p.id: p for p in res.scalars().all()}

    lines = [f"👥 <b>Состав — {gd.display_name}</b>\n"]
    for i, a in enumerate(yes_atts, 1):
        p = players_map.get(a.player_id)
        name = p.name if p else "—"
        lines.append(f"  {i}. {name}")

    if wait_atts:
        lines.append(f"\n⏳ <b>Резерв ({len(wait_atts)} чел.)</b>")

    await message.reply("\n".join(lines), parse_mode="HTML")

"""
Автоматические напоминания об игре.
  - за 24 часа: всем записавшимся (YES)
  - за 2 часа:  всем записавшимся (YES) + не ответившим (NO_RESPONSE)
"""
from datetime import datetime, timedelta

from aiogram import Bot
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.database.engine import AsyncSessionFactory
from app.database.models import GameDay, GameDayStatus, Attendance, AttendanceResponse
from app.keyboards.game_day import join_game_kb
from app.scheduler import scheduler

_bot: Bot | None = None


def set_bot(bot: Bot) -> None:
    global _bot
    _bot = bot


async def _send_reminder(game_day_id: int, hours_before: int) -> None:
    """Рассылка напоминания. Запускается APScheduler-ом."""
    if not _bot:
        return

    async with AsyncSessionFactory() as session:
        game_day = await session.get(GameDay, game_day_id)
        if not game_day or game_day.status == GameDayStatus.CANCELLED:
            return

        # Кого уведомлять: YES всегда; NO_RESPONSE только за 2ч
        target_responses = [AttendanceResponse.YES]
        if hours_before <= 2:
            target_responses.append(AttendanceResponse.NO_RESPONSE)

        result = await session.execute(
            select(Attendance)
            .options(selectinload(Attendance.player))
            .where(
                Attendance.game_day_id == game_day_id,
                Attendance.response.in_(target_responses),
            )
        )
        attendances = result.scalars().all()

        date_str = game_day.scheduled_at.strftime("%d.%m.%Y")
        time_str = game_day.scheduled_at.strftime("%H:%M")

        if hours_before >= 24:
            text = (
                f"⏰ <b>Напоминание — завтра игра!</b>\n\n"
                f"📅 {date_str} в {time_str}\n"
                f"📍 {game_day.location}\n"
                f"💰 Взнос: {game_day.cost_per_player} сум.\n\n"
                "Ты записан. Не забудь прийти! ⚽"
            )
        else:
            text = (
                f"🔔 <b>Через 2 часа игра!</b>\n\n"
                f"🕐 {time_str}, 📍 {game_day.location}\n\n"
                "Не опаздывай! ⚽"
            )

        sent = 0
        for att in attendances:
            try:
                if att.response == AttendanceResponse.NO_RESPONSE:
                    # Незаписавшимся показать кнопку записи
                    await _bot.send_message(
                        att.player.telegram_id,
                        f"⏰ <b>Через 2 часа игра!</b>\n\n"
                        f"📅 {date_str} в {time_str}, {game_day.location}\n\n"
                        "Ты ещё не подтвердил участие. Идёшь?",
                        reply_markup=join_game_kb(game_day.id, game_day.is_open),
                    )
                else:
                    await _bot.send_message(att.player.telegram_id, text)
                sent += 1
            except Exception:
                pass


def schedule_reminders(game_day: GameDay) -> None:
    """Запланировать напоминания за 24ч и 2ч до игры."""
    now = datetime.now()
    gd_id = game_day.id

    reminder_24h = game_day.scheduled_at - timedelta(hours=24)
    reminder_2h = game_day.scheduled_at - timedelta(hours=2)

    if reminder_24h > now:
        scheduler.add_job(
            _send_reminder,
            trigger="date",
            run_date=reminder_24h,
            args=[gd_id, 24],
            id=f"reminder_{gd_id}_24h",
            replace_existing=True,
        )

    if reminder_2h > now:
        scheduler.add_job(
            _send_reminder,
            trigger="date",
            run_date=reminder_2h,
            args=[gd_id, 2],
            id=f"reminder_{gd_id}_2h",
            replace_existing=True,
        )


async def reschedule_all_reminders() -> None:
    """
    При старте бота — восстановить напоминания для всех предстоящих игровых дней.
    APScheduler не сохраняет jobs между рестартами (MemoryJobStore).
    """
    now = datetime.now()
    async with AsyncSessionFactory() as session:
        result = await session.execute(
            select(GameDay).where(
                GameDay.status.in_([GameDayStatus.ANNOUNCED, GameDayStatus.CLOSED]),
                GameDay.scheduled_at > now,
            )
        )
        game_days = result.scalars().all()
        for gd in game_days:
            schedule_reminders(gd)

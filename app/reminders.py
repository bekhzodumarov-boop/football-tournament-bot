"""
Автоматические напоминания об игре.
  - за 9 часов:  всем записавшимся (YES) — «сегодня игра»
  - за 2 часа:   подтвердившим (confirmed_final=True) — простое «через 2ч»
                 неподтвердившим (confirmed_final=False) — «через 2ч + подтверди»
  - накануне в 20:00: напоминание с кнопками подтверждения (YES)
  - в день игры в 12:00: напоминание с кнопками подтверждения (YES)
"""
import asyncio
from datetime import datetime, timedelta

from aiogram import Bot
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.database.engine import AsyncSessionFactory
from app.database.models import GameDay, GameDayStatus, Attendance, AttendanceResponse, BroadcastLog
from app.keyboards.game_day import join_game_kb, confirm_attendance_kb
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

        date_str = game_day.scheduled_at.strftime("%d.%m.%Y")
        time_str = game_day.scheduled_at.strftime("%H:%M")

        result = await session.execute(
            select(Attendance)
            .options(selectinload(Attendance.player))
            .where(
                Attendance.game_day_id == game_day_id,
                Attendance.response == AttendanceResponse.YES,
            )
        )
        attendances = result.scalars().all()

        if hours_before >= 9:
            # За 9ч — простое напоминание всем записавшимся
            text = (
                f"⏰ <b>Сегодня игра!</b>\n\n"
                f"🕐 {time_str}  📍 {game_day.location}\n"
                f"💰 Взнос: {game_day.cost_per_player} сум.\n\n"
                "Ты записан. До встречи на поле! ⚽"
            )
            for att in attendances:
                try:
                    await _bot.send_message(att.player.telegram_id, text)
                    await asyncio.sleep(0.05)
                except Exception:
                    pass
        else:
            # За 2ч — разные сообщения в зависимости от подтверждения
            for att in attendances:
                try:
                    if att.confirmed_final:
                        # Уже подтвердил — просто напоминание
                        msg = (
                            f"🔔 <b>Через 2 часа игра!</b>\n\n"
                            f"🕐 {time_str}  📍 {game_day.location}\n\n"
                            "Не опаздывай! ⚽"
                        )
                        await _bot.send_message(att.player.telegram_id, msg)
                    else:
                        # Не подтвердил — напоминание + просьба подтвердить
                        lang = getattr(att.player, 'language', None) or 'ru'
                        msg = (
                            f"🔔 <b>Через 2 часа игра!</b>\n\n"
                            f"🕐 {time_str}  📍 {game_day.location}\n\n"
                            "Ты ещё не подтвердил участие.\n"
                            "Пожалуйста, подтверди — придёшь?"
                        )
                        await _bot.send_message(
                            att.player.telegram_id,
                            msg,
                            reply_markup=confirm_attendance_kb(game_day_id, lang),
                        )
                    await asyncio.sleep(0.05)
                except Exception:
                    pass


async def _send_confirm_reminder(game_day_id: int, reminder_type: str) -> None:
    """
    Рассылка напоминания с кнопками подтверждения.
    reminder_type: "before" (накануне 20:00) или "today" (в день игры 12:00).
    Запускается APScheduler-ом или вручную из админки.
    """
    if not _bot:
        return

    async with AsyncSessionFactory() as session:
        game_day = await session.get(
            GameDay, game_day_id,
            options=[selectinload(GameDay.attendances)]
        )
        if not game_day or game_day.status == GameDayStatus.CANCELLED:
            return

        query = (
            select(Attendance)
            .options(selectinload(Attendance.player))
            .where(
                Attendance.game_day_id == game_day_id,
                Attendance.response == AttendanceResponse.YES,
            )
        )
        # В день игры — только тем, кто НЕ подтвердил участие после напоминания накануне
        if reminder_type == "today":
            query = query.where(Attendance.confirmed_final == False)
        result = await session.execute(query)
        attendances = result.scalars().all()

        date_str = game_day.scheduled_at.strftime("%d.%m.%Y")
        time_str = game_day.scheduled_at.strftime("%H:%M")
        registered = sum(
            1 for a in game_day.attendances
            if a.response == AttendanceResponse.YES
        )

        from app.locales.texts import t

        sent = 0
        for att in attendances:
            try:
                lang = getattr(att.player, 'language', None) or 'ru'
                if reminder_type == "before":
                    text = t(
                        'remind_before', lang,
                        date=date_str, time=time_str,
                        location=game_day.location,
                        cost=game_day.cost_per_player,
                        registered=registered,
                        limit=game_day.player_limit,
                    )
                else:
                    text = t(
                        'remind_today', lang,
                        time=time_str,
                        location=game_day.location,
                        cost=game_day.cost_per_player,
                    )
                await _bot.send_message(
                    att.player.telegram_id,
                    text,
                    reply_markup=confirm_attendance_kb(game_day_id, lang),
                    parse_mode="HTML",
                )
                sent += 1
                await asyncio.sleep(0.05)
            except Exception:
                pass

        # Записать в BroadcastLog
        label = "за день до игры" if reminder_type == "before" else "в день игры"
        session.add(BroadcastLog(
            league_id=game_day.league_id,
            game_day_id=game_day_id,
            message_type=f"remind_{reminder_type}",
            message_preview=f"Напоминание {label} — {game_day.display_name}",
            recipients_count=len(attendances),
            sent_count=sent,
        ))
        await session.commit()


def schedule_reminders(game_day: GameDay) -> None:
    """Запланировать напоминания за 9ч, 2ч, накануне 20:00 и в день игры 12:00."""
    now = datetime.now()
    gd_id = game_day.id
    game_dt = game_day.scheduled_at  # naive Tashkent local time

    # --- напоминание за 9ч: всем записавшимся ---
    reminder_9h = game_dt - timedelta(hours=9)
    # --- напоминание за 2ч: с проверкой подтверждения ---
    reminder_2h = game_dt - timedelta(hours=2)

    if reminder_9h > now:
        scheduler.add_job(
            _send_reminder,
            trigger="date",
            run_date=reminder_9h,
            args=[gd_id, 9],
            id=f"reminder_{gd_id}_9h",
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

    # --- новые напоминания с кнопками подтверждения ---
    # накануне в 20:00
    day_before_20 = game_dt.replace(hour=20, minute=0, second=0, microsecond=0) - timedelta(days=1)
    # в день игры в 12:00
    game_day_12 = game_dt.replace(hour=12, minute=0, second=0, microsecond=0)

    if day_before_20 > now:
        scheduler.add_job(
            _send_confirm_reminder,
            trigger="date",
            run_date=day_before_20,
            args=[gd_id, "before"],
            id=f"remind_before_{gd_id}",
            replace_existing=True,
        )

    if game_day_12 > now:
        scheduler.add_job(
            _send_confirm_reminder,
            trigger="date",
            run_date=game_day_12,
            args=[gd_id, "today"],
            id=f"remind_today_{gd_id}",
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

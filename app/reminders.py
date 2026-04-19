"""
Автоматические напоминания об игре.
  - за 24 часа: всем записавшимся (YES)
  - за 2 часа:  всем записавшимся (YES) + не ответившим (NO_RESPONSE)
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
    """Запланировать напоминания за 24ч, 2ч, накануне 20:00 и в день игры 12:00."""
    now = datetime.now()
    gd_id = game_day.id
    game_dt = game_day.scheduled_at  # naive Tashkent local time

    # --- старые напоминания: за 24ч и 2ч (без кнопок подтверждения) ---
    reminder_24h = game_dt - timedelta(hours=24)
    reminder_2h = game_dt - timedelta(hours=2)

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

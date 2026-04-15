from aiogram import Router, F, Bot
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database.models import (
    GameDay, GameDayStatus, Attendance, AttendanceResponse,
    Player, Payment
)
from app.keyboards.game_day import game_day_action_kb, join_game_kb

router = Router()


def admin_only(func):
    """Декоратор: только для Админа"""
    async def wrapper(call: CallbackQuery, *args, **kwargs):
        if not settings.is_admin(call.from_user.id):
            await call.answer("⛔ Нет доступа", show_alert=True)
            return
        return await func(call, *args, **kwargs)
    wrapper.__name__ = func.__name__
    return wrapper


# ---------- Список игроков игрового дня ----------

@router.callback_query(F.data.startswith("gd_players:"))
async def gd_players(call: CallbackQuery, session: AsyncSession):
    if not settings.is_admin(call.from_user.id):
        await call.answer("⛔", show_alert=True)
        return
    await call.answer()

    game_day_id = int(call.data.split(":")[1])
    result = await session.execute(
        select(Attendance)
        .where(
            Attendance.game_day_id == game_day_id,
            Attendance.response == AttendanceResponse.YES
        )
    )
    attendances = result.scalars().all()

    if not attendances:
        await call.message.edit_text(
            "📭 Никто ещё не записался.",
            reply_markup=game_day_action_kb(game_day_id)
        )
        return

    lines = [f"👥 <b>Записались ({len(attendances)}):</b>\n"]
    for i, att in enumerate(attendances, 1):
        player = att.player
        from app.database.models import POSITION_LABELS
        pos = POSITION_LABELS.get(player.position, player.position)
        lines.append(
            f"{i}. <b>{player.name}</b> — {pos}, ⭐{player.rating:.1f}"
        )

    await call.message.edit_text(
        "\n".join(lines),
        reply_markup=game_day_action_kb(game_day_id)
    )


# ---------- Разослать анонс ----------

@router.callback_query(F.data.startswith("gd_announce:"))
async def gd_announce(call: CallbackQuery, session: AsyncSession, bot: Bot):
    if not settings.is_admin(call.from_user.id):
        await call.answer("⛔", show_alert=True)
        return
    await call.answer("Рассылаю анонс...", show_alert=False)

    game_day_id = int(call.data.split(":")[1])
    game_day = await session.get(GameDay, game_day_id)

    if not game_day:
        return

    players_result = await session.execute(
        select(Player).where(Player.status == "active")
    )
    players = players_result.scalars().all()

    spots_left = game_day.player_limit
    text = (
        f"⚽ <b>Анонс игры!</b>\n\n"
        f"📅 {game_day.scheduled_at.strftime('%d.%m.%Y %H:%M')}\n"
        f"📍 {game_day.location}\n"
        f"👥 Мест: {game_day.player_limit}\n"
        f"💰 Взнос: {game_day.cost_per_player} сум.\n\n"
        "Успей записаться! 👇"
    )

    sent = 0
    for player in players:
        try:
            await bot.send_message(
                player.telegram_id,
                text,
                reply_markup=join_game_kb(game_day.id, game_day.is_open)
            )
            sent += 1
        except Exception:
            pass

    await call.message.answer(f"✅ Анонс отправлен {sent} игрокам.")


# ---------- Закрыть запись ----------

@router.callback_query(F.data.startswith("gd_close:"))
async def gd_close(call: CallbackQuery, session: AsyncSession):
    if not settings.is_admin(call.from_user.id):
        await call.answer("⛔", show_alert=True)
        return
    await call.answer()

    game_day_id = int(call.data.split(":")[1])
    game_day = await session.get(GameDay, game_day_id)
    if game_day:
        game_day.status = GameDayStatus.CLOSED
        await session.commit()

    await call.message.edit_text(
        "🔒 Запись закрыта. Можно формировать команды.",
        reply_markup=game_day_action_kb(game_day_id)
    )


# ---------- Отметить оплату ----------

@router.callback_query(F.data.startswith("gd_payment:"))
async def gd_payment(call: CallbackQuery, session: AsyncSession):
    if not settings.is_admin(call.from_user.id):
        await call.answer("⛔", show_alert=True)
        return
    await call.answer()

    game_day_id = int(call.data.split(":")[1])
    game_day = await session.get(GameDay, game_day_id)

    result = await session.execute(
        select(Attendance).where(
            Attendance.game_day_id == game_day_id,
            Attendance.response == AttendanceResponse.YES
        )
    )
    attendances = result.scalars().all()

    if not attendances:
        await call.message.edit_text("Никто не записан.", reply_markup=game_day_action_kb(game_day_id))
        return

    builder = InlineKeyboardBuilder()
    for att in attendances:
        payment_result = await session.execute(
            select(Payment).where(
                Payment.game_day_id == game_day_id,
                Payment.player_id == att.player_id
            )
        )
        payment = payment_result.scalar_one_or_none()
        paid = payment and payment.paid
        emoji = "✅" if paid else "❌"
        builder.button(
            text=f"{emoji} {att.player.name}",
            callback_data=f"toggle_pay:{game_day_id}:{att.player_id}"
        )
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data=f"gd_manage:{game_day_id}"))

    await call.message.edit_text(
        f"💰 <b>Оплата — {game_day.scheduled_at.strftime('%d.%m.%Y')}</b>\n\n"
        "Нажми на игрока чтобы отметить оплату:",
        reply_markup=builder.as_markup()
    )


@router.callback_query(F.data.startswith("toggle_pay:"))
async def toggle_payment(call: CallbackQuery, session: AsyncSession):
    if not settings.is_admin(call.from_user.id):
        await call.answer("⛔", show_alert=True)
        return

    _, game_day_id, player_id = call.data.split(":")
    game_day_id, player_id = int(game_day_id), int(player_id)

    from datetime import datetime
    result = await session.execute(
        select(Payment).where(
            Payment.game_day_id == game_day_id,
            Payment.player_id == player_id
        )
    )
    payment = result.scalar_one_or_none()
    game_day = await session.get(GameDay, game_day_id)

    if payment:
        payment.paid = not payment.paid
        payment.paid_at = datetime.now() if payment.paid else None
    else:
        payment = Payment(
            game_day_id=game_day_id,
            player_id=player_id,
            amount=game_day.cost_per_player,
            paid=True,
            paid_at=datetime.now()
        )
        session.add(payment)

    await session.commit()
    await call.answer("✅ Статус оплаты обновлён")
    # Перезагрузить список
    await gd_payment(call, session)

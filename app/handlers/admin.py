from aiogram import Router, F, Bot
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database.models import (
    GameDay, GameDayStatus, Attendance, AttendanceResponse,
    Player, Payment, Team, TeamPlayer, Match, Goal, Card,
)
from app.keyboards.game_day import game_day_action_kb, join_game_kb, delete_confirm_kb

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


# ---------- Отменить игру ----------

@router.callback_query(F.data.startswith("gd_cancel:"))
async def gd_cancel_game(call: CallbackQuery, session: AsyncSession, bot: Bot):
    if not settings.is_admin(call.from_user.id):
        await call.answer("⛔", show_alert=True)
        return
    await call.answer()

    game_day_id = int(call.data.split(":")[1])
    game_day = await session.get(GameDay, game_day_id)
    if not game_day:
        await call.message.edit_text("❌ Игровой день не найден.")
        return

    game_day.status = GameDayStatus.CANCELLED
    await session.commit()

    # Уведомить записавшихся
    att_result = await session.execute(
        select(Attendance).where(
            Attendance.game_day_id == game_day_id,
            Attendance.response == AttendanceResponse.YES,
        )
    )
    attendances = att_result.scalars().all()

    cancel_text = (
        f"❌ <b>Игра отменена</b>\n\n"
        f"📅 {game_day.scheduled_at.strftime('%d.%m.%Y %H:%M')}\n"
        f"📍 {game_day.location}\n\n"
        "Игра отменена организатором. Извини за неудобство!"
    )

    notified = 0
    for att in attendances:
        try:
            await bot.send_message(att.player.telegram_id, cancel_text)
            notified += 1
        except Exception:
            pass

    await call.message.edit_text(
        f"❌ <b>Игра отменена.</b>\n\nУведомление отправлено {notified} игрокам.",
        reply_markup=game_day_action_kb(game_day_id)
    )


# ---------- Удалить игровой день (запрос подтверждения) ----------

@router.callback_query(F.data.startswith("gd_delete:"))
async def gd_delete_ask(call: CallbackQuery, session: AsyncSession):
    if not settings.is_admin(call.from_user.id):
        await call.answer("⛔", show_alert=True)
        return
    await call.answer()

    game_day_id = int(call.data.split(":")[1])
    game_day = await session.get(GameDay, game_day_id)
    if not game_day:
        await call.message.edit_text("❌ Игровой день не найден.")
        return

    await call.message.edit_text(
        f"🗑 <b>Удалить игровой день?</b>\n\n"
        f"📅 {game_day.scheduled_at.strftime('%d.%m.%Y %H:%M')}\n"
        f"📍 {game_day.location}\n\n"
        "⚠️ Это действие <b>нельзя отменить</b>. "
        "Все матчи, команды, записи и оплаты будут удалены.",
        reply_markup=delete_confirm_kb(game_day_id)
    )


# ---------- Удалить игровой день (исполнение) ----------

@router.callback_query(F.data.startswith("gd_delete_ok:"))
async def gd_delete_execute(call: CallbackQuery, session: AsyncSession):
    if not settings.is_admin(call.from_user.id):
        await call.answer("⛔", show_alert=True)
        return
    await call.answer("🗑 Удаляю...", show_alert=False)

    game_day_id = int(call.data.split(":")[1])

    from sqlalchemy import delete as sql_delete

    # Получить ID матчей этого игрового дня
    matches_result = await session.execute(
        select(Match.id).where(Match.game_day_id == game_day_id)
    )
    match_ids = [r[0] for r in matches_result.all()]

    # Получить ID команд этого игрового дня
    teams_result = await session.execute(
        select(Team.id).where(Team.game_day_id == game_day_id)
    )
    team_ids = [r[0] for r in teams_result.all()]

    # Каскадное удаление: Голы → Карточки → Матчи → TeamPlayers → Команды → Посещения → Оплаты → GameDay
    if match_ids:
        await session.execute(sql_delete(Goal).where(Goal.match_id.in_(match_ids)))
        await session.execute(sql_delete(Card).where(Card.match_id.in_(match_ids)))
        await session.execute(sql_delete(Match).where(Match.id.in_(match_ids)))

    if team_ids:
        await session.execute(sql_delete(TeamPlayer).where(TeamPlayer.team_id.in_(team_ids)))
        await session.execute(sql_delete(Team).where(Team.id.in_(team_ids)))

    await session.execute(sql_delete(Attendance).where(Attendance.game_day_id == game_day_id))
    await session.execute(sql_delete(Payment).where(Payment.game_day_id == game_day_id))

    game_day = await session.get(GameDay, game_day_id)
    if game_day:
        await session.delete(game_day)

    await session.commit()

    await call.message.edit_text(
        "🗑 <b>Игровой день удалён.</b>\n\n"
        "Все связанные данные (команды, матчи, записи, оплаты) удалены."
    )


# ══════════════════════════════════════════════════════
#  УПРАВЛЕНИЕ ИГРОКАМИ — назначение судей, статусы
# ══════════════════════════════════════════════════════

def _players_list_kb(players: list[Player]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for p in players:
        ref_mark = " 🦺" if p.is_referee else ""
        builder.row(InlineKeyboardButton(
            text=f"{p.name}{ref_mark}",
            callback_data=f"adm_player:{p.id}"
        ))
    builder.row(InlineKeyboardButton(text="🔙 Меню", callback_data="admin_back"))
    return builder.as_markup()


def _player_card_kb(player: Player) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if player.is_referee:
        builder.row(InlineKeyboardButton(
            text="❌ Снять роль судьи",
            callback_data=f"adm_toggle_ref:{player.id}"
        ))
    else:
        builder.row(InlineKeyboardButton(
            text="🦺 Назначить судьёй",
            callback_data=f"adm_toggle_ref:{player.id}"
        ))
    builder.row(
        InlineKeyboardButton(text="🚫 Заблокировать" if player.status.value == "active" else "✅ Разблокировать",
                             callback_data=f"adm_toggle_ban:{player.id}"),
    )
    builder.row(InlineKeyboardButton(text="🔙 К списку", callback_data="admin_players"))
    return builder.as_markup()


@router.callback_query(F.data == "admin_players")
async def adm_players_list(call: CallbackQuery, session: AsyncSession):
    if not settings.is_admin(call.from_user.id):
        await call.answer("⛔", show_alert=True)
        return
    await call.answer()

    result = await session.execute(select(Player).order_by(Player.name))
    players = result.scalars().all()

    if not players:
        await call.message.edit_text("👥 Игроков пока нет.")
        return

    referees = [p for p in players if p.is_referee]
    ref_names = ", ".join(p.name for p in referees) if referees else "нет"

    await call.message.edit_text(
        f"👥 <b>Игроки</b> ({len(players)} чел.)\n\n"
        f"🦺 Судьи: <b>{ref_names}</b>\n\n"
        "Нажми на игрока чтобы изменить роль:",
        reply_markup=_players_list_kb(players)
    )


@router.callback_query(F.data.startswith("adm_player:"))
async def adm_player_card(call: CallbackQuery, session: AsyncSession):
    if not settings.is_admin(call.from_user.id):
        await call.answer("⛔", show_alert=True)
        return
    await call.answer()

    player_id = int(call.data.split(":")[1])
    player = await session.get(Player, player_id)
    if not player:
        await call.message.edit_text("❌ Игрок не найден.")
        return

    from app.database.models import POSITION_LABELS
    pos = POSITION_LABELS.get(player.position, player.position)
    role = "🦺 Судья" if player.is_referee else "⚽ Игрок"
    status = "✅ Активен" if player.status.value == "active" else "🚫 Заблокирован"

    await call.message.edit_text(
        f"👤 <b>{player.name}</b>\n\n"
        f"Позиция: {pos}\n"
        f"Роль: {role}\n"
        f"Статус: {status}\n"
        f"⭐ Рейтинг: {player.rating:.1f}\n"
        f"⚽ Игр: {player.games_played}\n"
        f"💰 Баланс: {player.balance} сум.",
        reply_markup=_player_card_kb(player)
    )


@router.callback_query(F.data.startswith("adm_toggle_ref:"))
async def adm_toggle_referee(call: CallbackQuery, session: AsyncSession, bot: Bot):
    if not settings.is_admin(call.from_user.id):
        await call.answer("⛔", show_alert=True)
        return

    player_id = int(call.data.split(":")[1])
    player = await session.get(Player, player_id)
    if not player:
        await call.answer("❌ Игрок не найден", show_alert=True)
        return

    player.is_referee = not player.is_referee
    await session.commit()

    action = "назначен судьёй 🦺" if player.is_referee else "снят с роли судьи"
    await call.answer(f"{player.name} {action}", show_alert=True)

    # Уведомить самого игрока
    try:
        if player.is_referee:
            await bot.send_message(
                player.telegram_id,
                "🦺 <b>Тебе назначена роль судьи!</b>\n\n"
                "Теперь ты можешь использовать команду /referee "
                "для управления матчами."
            )
        else:
            await bot.send_message(
                player.telegram_id,
                "ℹ️ Роль судьи снята с твоего аккаунта."
            )
    except Exception:
        pass

    # Обновить карточку
    await adm_player_card(call, session)


@router.callback_query(F.data.startswith("adm_toggle_ban:"))
async def adm_toggle_ban(call: CallbackQuery, session: AsyncSession, bot: Bot):
    if not settings.is_admin(call.from_user.id):
        await call.answer("⛔", show_alert=True)
        return

    from app.database.models import PlayerStatus
    player_id = int(call.data.split(":")[1])
    player = await session.get(Player, player_id)
    if not player:
        await call.answer("❌ Игрок не найден", show_alert=True)
        return

    if player.status == PlayerStatus.ACTIVE:
        player.status = PlayerStatus.BANNED
        action = "заблокирован 🚫"
        msg = "🚫 Твой аккаунт заблокирован. Обратись к организатору."
    else:
        player.status = PlayerStatus.ACTIVE
        action = "разблокирован ✅"
        msg = "✅ Твой аккаунт разблокирован. Добро пожаловать обратно!"

    await session.commit()
    await call.answer(f"{player.name} {action}", show_alert=True)

    try:
        await bot.send_message(player.telegram_id, msg)
    except Exception:
        pass

    await adm_player_card(call, session)


@router.callback_query(F.data == "admin_back")
async def adm_back_to_menu(call: CallbackQuery):
    if not settings.is_admin(call.from_user.id):
        await call.answer("⛔", show_alert=True)
        return
    await call.answer()
    from app.keyboards.main_menu import admin_menu_kb
    await call.message.edit_text(
        "🔧 <b>Панель администратора</b>\n\nВыбери действие:",
        reply_markup=admin_menu_kb()
    )

import logging
import asyncio
from aiogram import Router, F, Bot
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import select, delete as sql_delete
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database.models import (
    GameDay, GameDayStatus, Attendance, AttendanceResponse,
    Player, Payment, Team, TeamPlayer, Match, Goal, Card,
    League, RatingVote, RatingRound,
)
from app.keyboards.game_day import game_day_action_kb, join_game_kb, delete_confirm_kb

logger = logging.getLogger(__name__)
router = Router()


class BroadcastFSM(StatesGroup):
    waiting_text = State()


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

    game_day = await session.get(GameDay, game_day_id)

    all_att_result = await session.execute(
        select(Attendance)
        .options(selectinload(Attendance.player))
        .where(
            Attendance.game_day_id == game_day_id,
            Attendance.response.in_([AttendanceResponse.YES, AttendanceResponse.WAITLIST])
        )
        .order_by(Attendance.responded_at)
    )
    all_att = all_att_result.scalars().all()

    attendances = [a for a in all_att if a.response == AttendanceResponse.YES]
    waitlist = [a for a in all_att if a.response == AttendanceResponse.WAITLIST]

    gd_name = game_day.display_name if game_day else f"#{game_day_id}"

    if not attendances and not waitlist:
        await call.message.edit_text(
            f"📋 <b>{gd_name}</b>\n\n📭 Никто ещё не записался.",
            reply_markup=game_day_action_kb(game_day_id)
        )
        return

    from app.database.models import POSITION_LABELS

    def _player_line(p):
        if p.username:
            return f' <a href="https://t.me/{p.username}">@{p.username}</a>'
        return f' <a href="tg://user?id={p.telegram_id}">💬</a>'

    limit = game_day.player_limit if game_day else "?"
    lines = [f"📋 <b>{gd_name}</b>\n👥 Записались ({len(attendances)}/{limit}):\n"]
    for i, att in enumerate(attendances, 1):
        p = att.player
        if not p:
            continue
        pos = POSITION_LABELS.get(p.position, p.position)
        lines.append(f"{i}. <b>{p.name}</b>{_player_line(p)} — {pos}, ⭐{p.rating:.1f}")

    if waitlist:
        lines.append(f"\n⏳ <b>Лист ожидания ({len(waitlist)}):</b>")
        for i, att in enumerate(waitlist, 1):
            p = att.player
            if not p:
                continue
            lines.append(f"{i}. {p.name}{_player_line(p)}")

    action_kb = game_day_action_kb(game_day_id)
    from aiogram.utils.keyboard import InlineKeyboardBuilder as IKB
    builder = IKB()
    builder.row(InlineKeyboardButton(
        text="❌ Убрать игрока из записи",
        callback_data=f"gd_kick_list:{game_day_id}"
    ))
    for row in action_kb.inline_keyboard:
        builder.row(*row)

    await call.message.edit_text(
        "\n".join(lines),
        parse_mode="HTML",
        reply_markup=builder.as_markup()
    )


# ---------- Убрать игрока из записи ----------

@router.callback_query(F.data.startswith("gd_kick_list:"))
async def gd_kick_list(call: CallbackQuery, session: AsyncSession):
    if not settings.is_admin(call.from_user.id):
        await call.answer("⛔", show_alert=True)
        return
    await call.answer()

    game_day_id = int(call.data.split(":")[1])
    game_day = await session.get(GameDay, game_day_id)

    result = await session.execute(
        select(Attendance)
        .options(selectinload(Attendance.player))
        .where(
            Attendance.game_day_id == game_day_id,
            Attendance.response == AttendanceResponse.YES
        )
    )
    attendances = result.scalars().all()

    if not attendances:
        await call.message.edit_text(
            "📭 Никто не записан — некого убирать.",
            reply_markup=game_day_action_kb(game_day_id)
        )
        return

    gd_name = game_day.display_name if game_day else f"#{game_day_id}"
    builder = InlineKeyboardBuilder()
    for att in attendances:
        p = att.player
        builder.row(InlineKeyboardButton(
            text=f"❌ {p.name}",
            callback_data=f"gd_kick_confirm:{game_day_id}:{p.id}"
        ))
    builder.row(InlineKeyboardButton(
        text="🔙 Назад",
        callback_data=f"gd_players:{game_day_id}"
    ))

    await call.message.edit_text(
        f"❌ <b>Убрать игрока из записи — {gd_name}</b>\n\n"
        "Выбери игрока которого нужно убрать:",
        reply_markup=builder.as_markup()
    )


@router.callback_query(F.data.startswith("gd_kick_confirm:"))
async def gd_kick_confirm_cb(call: CallbackQuery, session: AsyncSession):
    if not settings.is_admin(call.from_user.id):
        await call.answer("⛔", show_alert=True)
        return
    await call.answer()

    parts = call.data.split(":")
    game_day_id = int(parts[1])
    player_id = int(parts[2])

    player = await session.get(Player, player_id)
    if not player:
        await call.message.edit_text("❌ Игрок не найден.")
        return

    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="✅ Да, убрать",
            callback_data=f"gd_kick_ok:{game_day_id}:{player_id}"
        ),
        InlineKeyboardButton(
            text="❌ Отмена",
            callback_data=f"gd_kick_list:{game_day_id}"
        )
    )

    await call.message.edit_text(
        f"⚠️ <b>Убрать игрока из записи?</b>\n\n"
        f"👤 <b>{player.name}</b>\n\n"
        "Игрок будет переведён в статус «Не идёт».\n"
        "Следующий из листа ожидания получит уведомление.",
        reply_markup=builder.as_markup()
    )


@router.callback_query(F.data.startswith("gd_kick_ok:"))
async def gd_kick_execute(call: CallbackQuery, session: AsyncSession, bot: Bot):
    if not settings.is_admin(call.from_user.id):
        await call.answer("⛔", show_alert=True)
        return
    await call.answer("⏳ Убираю игрока...")

    parts = call.data.split(":")
    game_day_id = int(parts[1])
    player_id = int(parts[2])

    # Найти запись
    result = await session.execute(
        select(Attendance).where(
            Attendance.game_day_id == game_day_id,
            Attendance.player_id == player_id
        )
    )
    att = result.scalar_one_or_none()
    if not att:
        await call.message.edit_text("❌ Запись не найдена.", reply_markup=game_day_action_kb(game_day_id))
        return

    player = await session.get(Player, player_id)
    player_name = player.name if player else f"#{player_id}"

    from datetime import datetime
    att.response = AttendanceResponse.NO
    att.responded_at = datetime.now()
    await session.commit()

    # Уведомить игрока
    if player:
        game_day = await session.get(GameDay, game_day_id)
        try:
            lang = getattr(player, 'language', None) or 'ru'
            if lang == 'en':
                kick_text = (
                    f"ℹ️ <b>Registration cancelled</b>\n\n"
                    f"The organizer has removed you from the roster for "
                    f"<b>{game_day.display_name if game_day else '—'}</b>.\n\n"
                    "Contact the organizer if you have questions."
                )
            else:
                kick_text = (
                    f"ℹ️ <b>Запись отменена</b>\n\n"
                    f"Организатор убрал тебя из состава на "
                    f"<b>{game_day.display_name if game_day else '—'}</b>.\n\n"
                    "Если есть вопросы — напиши организатору."
                )
            await bot.send_message(player.telegram_id, kick_text)
        except Exception as e:
            logger.warning(f"Cannot notify kicked player {player_id}: {e}")

    # Уведомить первого из листа ожидания
    from app.handlers.game_day import _notify_first_waitlist
    await _notify_first_waitlist(session, game_day_id, bot)

    await call.message.edit_text(
        f"✅ <b>{player_name}</b> убран из записи.\n\n"
        "Следующий игрок из листа ожидания получил уведомление.",
        reply_markup=game_day_action_kb(game_day_id)
    )


# ---------- Разослать анонс (подтверждение) ----------

@router.callback_query(F.data.startswith("gd_announce:"))
async def gd_announce(call: CallbackQuery, session: AsyncSession):
    if not settings.is_admin(call.from_user.id):
        await call.answer("⛔", show_alert=True)
        return
    await call.answer()

    game_day_id = int(call.data.split(":")[1])
    game_day = await session.get(GameDay, game_day_id)
    if not game_day:
        return

    players_result = await session.execute(
        select(Player).where(Player.status == "active")
    )
    player_count = len(players_result.scalars().all())

    confirm_kb = InlineKeyboardBuilder()
    confirm_kb.row(
        InlineKeyboardButton(
            text=f"📢 Да, разослать {player_count} игрокам",
            callback_data=f"gd_announce_ok:{game_day_id}"
        )
    )
    confirm_kb.row(
        InlineKeyboardButton(text="❌ Отмена", callback_data=f"gd_players:{game_day_id}")
    )

    await call.message.edit_text(
        f"📢 <b>Разослать анонс?</b>\n\n"
        f"📅 {game_day.scheduled_at.strftime('%d.%m.%Y %H:%M')}\n"
        f"📍 {game_day.location}\n\n"
        f"Сообщение получат <b>{player_count}</b> активных игроков.",
        reply_markup=confirm_kb.as_markup()
    )


@router.callback_query(F.data.startswith("gd_announce_ok:"))
async def gd_announce_execute(call: CallbackQuery, session: AsyncSession, bot: Bot):
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
            await asyncio.sleep(0.05)
        except Exception as e:
            logger.warning(f"Cannot send announce to {player.telegram_id}: {e}")

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
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data=f"gd_players:{game_day_id}"))

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
            await asyncio.sleep(0.05)
        except Exception as e:
            logger.warning(f"Cannot send cancel notice to {att.player.telegram_id}: {e}")

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

    # Delete rating votes and rounds tied to this game day
    rating_rounds_res = await session.execute(
        select(RatingRound.id).where(RatingRound.game_day_id == game_day_id)
    )
    rating_round_ids = [r[0] for r in rating_rounds_res.all()]
    if rating_round_ids:
        await session.execute(sql_delete(RatingVote).where(RatingVote.round_id.in_(rating_round_ids)))
        await session.execute(sql_delete(RatingRound).where(RatingRound.id.in_(rating_round_ids)))

    await session.execute(sql_delete(Attendance).where(Attendance.game_day_id == game_day_id))
    await session.execute(sql_delete(Payment).where(Payment.game_day_id == game_day_id))

    game_day = await session.get(GameDay, game_day_id)
    if game_day:
        await session.delete(game_day)

    await session.commit()

    from app.keyboards.main_menu import admin_menu_kb
    await call.message.edit_text(
        "🗑 <b>Игровой день удалён.</b>\n\n"
        "Все связанные данные (команды, матчи, записи, оплаты) удалены.",
        reply_markup=admin_menu_kb(),
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
    builder.row(
        InlineKeyboardButton(text="🗑 Удалить профиль", callback_data=f"adm_delete_player:{player.id}"),
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
    except Exception as e:
        logger.warning(f"Cannot notify player {player.telegram_id} about referee role: {e}")

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
    except Exception as e:
        logger.warning(f"Cannot notify player {player.telegram_id} about ban status: {e}")

    await adm_player_card(call, session)


@router.callback_query(F.data.startswith("adm_delete_player:"))
async def adm_delete_player_confirm(call: CallbackQuery, session: AsyncSession):
    if not settings.is_admin(call.from_user.id):
        await call.answer("⛔", show_alert=True)
        return
    await call.answer()

    player_id = int(call.data.split(":")[1])
    player = await session.get(Player, player_id)
    if not player:
        await call.message.edit_text("❌ Игрок не найден.")
        return

    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="🗑 Да, удалить навсегда",
            callback_data=f"adm_delete_player_ok:{player_id}"
        )
    )
    builder.row(
        InlineKeyboardButton(text="↩️ Отмена", callback_data=f"adm_player:{player_id}")
    )

    await call.message.edit_text(
        f"⚠️ <b>Удалить профиль?</b>\n\n"
        f"👤 <b>{player.name}</b>\n"
        f"@{player.username or '—'}\n\n"
        "Это действие <b>нельзя отменить</b>. Будут удалены все данные игрока: "
        "посещения, оплаты, голы, карточки.",
        reply_markup=builder.as_markup()
    )


@router.callback_query(F.data.startswith("adm_delete_player_ok:"))
async def adm_delete_player_execute(call: CallbackQuery, session: AsyncSession):
    if not settings.is_admin(call.from_user.id):
        await call.answer("⛔", show_alert=True)
        return
    await call.answer()

    player_id = int(call.data.split(":")[1])
    player = await session.get(Player, player_id)
    if not player:
        await call.message.edit_text("❌ Игрок уже удалён или не найден.")
        return

    player_name = player.name

    # Каскадное удаление всех связанных данных
    await session.execute(sql_delete(RatingVote).where(RatingVote.voter_id == player_id))
    await session.execute(sql_delete(RatingVote).where(RatingVote.nominee_id == player_id))
    await session.execute(sql_delete(Goal).where(Goal.player_id == player_id))
    await session.execute(sql_delete(Card).where(Card.player_id == player_id))
    await session.execute(sql_delete(TeamPlayer).where(TeamPlayer.player_id == player_id))
    await session.execute(sql_delete(Payment).where(Payment.player_id == player_id))
    await session.execute(sql_delete(Attendance).where(Attendance.player_id == player_id))
    await session.delete(player)
    await session.commit()

    from app.keyboards.main_menu import admin_menu_kb
    await call.message.edit_text(
        f"✅ Профиль <b>{player_name}</b> удалён.\n\n"
        "Все связанные данные (посещения, оплаты, голы, карточки) также удалены.",
        reply_markup=admin_menu_kb()
    )


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


# ══════════════════════════════════════════════════════
#  РАССЫЛКА — Broadcast
# ══════════════════════════════════════════════════════

@router.callback_query(F.data == "admin_broadcast")
async def adm_broadcast_start(call: CallbackQuery, state: FSMContext):
    if not settings.is_admin(call.from_user.id):
        await call.answer("⛔", show_alert=True)
        return
    await call.answer()

    from app.keyboards.main_menu import admin_menu_kb
    cancel_kb = InlineKeyboardBuilder()
    cancel_kb.row(InlineKeyboardButton(text="❌ Отмена", callback_data="admin_back"))

    await state.set_state(BroadcastFSM.waiting_text)
    await call.message.edit_text(
        "📢 <b>Рассылка всем игрокам</b>\n\n"
        "Напиши текст сообщения. Поддерживается HTML-форматирование:\n"
        "<code>&lt;b&gt;жирный&lt;/b&gt;</code>, <code>&lt;i&gt;курсив&lt;/i&gt;</code>, "
        "<code>&lt;a href='...'&gt;ссылка&lt;/a&gt;</code>\n\n"
        "Отправь сообщение или нажми Отмена:",
        reply_markup=cancel_kb.as_markup(),
    )


@router.message(StateFilter(BroadcastFSM.waiting_text))
async def adm_broadcast_send(message: Message, state: FSMContext, session: AsyncSession, bot: Bot):
    if not settings.is_admin(message.from_user.id):
        return

    text = message.text or message.caption or ""
    if not text.strip():
        await message.answer("❌ Пустое сообщение. Попробуй снова или нажми Отмена.")
        return

    await state.clear()

    result = await session.execute(select(Player))
    players = result.scalars().all()

    sent = 0
    failed = 0
    for player in players:
        try:
            await bot.send_message(player.telegram_id, text)
            sent += 1
            await asyncio.sleep(0.05)
        except Exception as e:
            logger.warning(f"Broadcast failed for {player.telegram_id}: {e}")
            failed += 1

    from app.keyboards.main_menu import admin_menu_kb
    summary = (
        f"📢 <b>Рассылка завершена</b>\n\n"
        f"✅ Доставлено: <b>{sent}</b>\n"
        f"❌ Не доставлено: <b>{failed}</b>"
    )
    await message.answer(summary, reply_markup=admin_menu_kb())


# ══════════════════════════════════════════════════════
#  ОПЛАТА — обзор по всем активным игровым дням
# ══════════════════════════════════════════════════════

@router.callback_query(F.data == "admin_payments")
async def adm_payments_overview(call: CallbackQuery, session: AsyncSession):
    if not settings.is_admin(call.from_user.id):
        await call.answer("⛔", show_alert=True)
        return
    await call.answer()

    from app.keyboards.main_menu import admin_menu_kb
    from datetime import datetime

    # Берём игровые дни, которые не удалены (не CANCELLED) и не в далёком прошлом
    result = await session.execute(
        select(GameDay)
        .where(GameDay.status != GameDayStatus.CANCELLED)
        .order_by(GameDay.scheduled_at.desc())
        .limit(10)
    )
    game_days = result.scalars().all()

    if not game_days:
        await call.message.edit_text(
            "💳 Нет активных игровых дней.",
            reply_markup=admin_menu_kb(),
        )
        return

    builder = InlineKeyboardBuilder()
    for gd in game_days:
        # Считаем: записалось / оплатило
        att_result = await session.execute(
            select(Attendance).where(
                Attendance.game_day_id == gd.id,
                Attendance.response == AttendanceResponse.YES,
            )
        )
        attendances = att_result.scalars().all()
        total = len(attendances)

        pay_result = await session.execute(
            select(Payment).where(
                Payment.game_day_id == gd.id,
                Payment.paid == True,  # noqa: E712
            )
        )
        paid_count = len(pay_result.scalars().all())

        date_str = gd.scheduled_at.strftime("%d.%m")
        builder.row(InlineKeyboardButton(
            text=f"📅 {date_str} — {paid_count}/{total} оплатили",
            callback_data=f"gd_payment:{gd.id}",
        ))

    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back"))

    await call.message.edit_text(
        "💳 <b>Оплата по игровым дням</b>\n\n"
        "Нажми на игровой день чтобы отметить оплаты:",
        reply_markup=builder.as_markup(),
    )


# ══════════════════════════════════════════════════════
#  ЭКСПОРТ В GOOGLE SHEETS
# ══════════════════════════════════════════════════════

@router.callback_query(F.data == "admin_export_sheets")
async def adm_export_sheets(call: CallbackQuery, session: AsyncSession):
    if not settings.is_admin(call.from_user.id):
        await call.answer("⛔", show_alert=True)
        return
    await call.answer()

    from app.keyboards.main_menu import admin_menu_kb

    if not settings.GOOGLE_CREDENTIALS_JSON or not settings.GOOGLE_SHEET_ID:
        await call.message.edit_text(
            "⚙️ <b>Экспорт в Google Sheets не настроен</b>\n\n"
            "Чтобы включить экспорт:\n\n"
            "1. Зайди на <a href='https://console.cloud.google.com'>console.cloud.google.com</a>\n"
            "2. Создай проект → включи <b>Google Sheets API</b>\n"
            "3. Создай <b>Сервисный аккаунт</b> → скачай JSON-ключ\n"
            "4. В Railway добавь переменные:\n"
            "   <code>GOOGLE_CREDENTIALS_JSON</code> = содержимое JSON-файла\n"
            "   <code>GOOGLE_SHEET_ID</code> = ID из URL таблицы\n"
            "5. Создай Google-таблицу и открой доступ сервисному аккаунту\n\n"
            "<i>Email сервисного аккаунта указан в JSON в поле client_email</i>",
            reply_markup=admin_menu_kb(),
            disable_web_page_preview=True,
        )
        return

    await call.message.edit_text("⏳ Экспортирую данные в Google Sheets…")

    try:
        from app.google_sheets import export_to_sheets
        url = await export_to_sheets(session)
        await call.message.edit_text(
            f"✅ <b>Экспорт завершён!</b>\n\n"
            f"📊 Данные обновлены в таблице:\n{url}\n\n"
            "Листы: 📊 Таблица · ⚽ Матчи · 👥 Игроки",
            reply_markup=admin_menu_kb(),
        )
    except Exception as e:
        await call.message.edit_text(
            f"❌ <b>Ошибка экспорта:</b>\n<code>{e}</code>\n\n"
            "Проверь правильность GOOGLE_CREDENTIALS_JSON и GOOGLE_SHEET_ID.",
            reply_markup=admin_menu_kb(),
        )

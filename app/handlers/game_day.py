from datetime import datetime, timedelta
import logging
import asyncio
from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database.models import (
    GameDay, GameDayStatus, Attendance, AttendanceResponse,
    Player, MatchFormat, PlayerLeague, PlayerStatus,
)
from app.keyboards.game_day import join_game_kb, join_confirm_kb, game_day_action_kb
from app.data.reglament import REGLAMENT_AGREEMENT, REGLAMENT_AGREEMENT_EN
from app.reminders import schedule_reminders
from app.locales.texts import t, t_g

logger = logging.getLogger(__name__)
router = Router()


class CreateGameDayFSM(StatesGroup):
    waiting_date = State()
    waiting_location = State()
    waiting_limit = State()


# ── Cancel регистрируется ПЕРВЫМ — перехватывает раньше FSM-хендлеров ──

@router.message(Command("cancel"))
async def gameday_cancel(message: Message, state: FSMContext):
    current = await state.get_state()
    if current is None:
        return  # передать другим роутерам
    await state.clear()
    from app.keyboards.main_menu import admin_menu_kb
    await message.answer(
        "❌ Создание игрового дня отменено.",
        reply_markup=admin_menu_kb()
    )


# ---------- Показать ближайшую игру ----------

@router.callback_query(F.data == "next_game")
@router.message(Command("game"))
async def show_next_game(event, session: AsyncSession, player: Player | None):
    is_callback = isinstance(event, CallbackQuery)
    if is_callback:
        await event.answer()
        send = event.message.edit_text
    else:
        send = event.answer

    league_id = player.league_id if player else None

    query = (
        select(GameDay)
        .options(selectinload(GameDay.attendances))
        .where(GameDay.status.in_([GameDayStatus.ANNOUNCED, GameDayStatus.IN_PROGRESS]))
        .order_by(GameDay.scheduled_at)
        .limit(1)
    )
    if league_id is not None:
        query = query.where(GameDay.league_id == league_id)

    result = await session.execute(query)
    game_day = result.scalar_one_or_none()

    if not game_day:
        await send("📅 Ближайших игр пока нет. Следи за анонсами!")
        return

    registered = sum(1 for a in game_day.attendances if a.response == AttendanceResponse.YES)
    waitlist = sum(1 for a in game_day.attendances if a.response == AttendanceResponse.WAITLIST)
    spots_left = game_day.player_limit - registered

    player_status = ""
    if player:
        att_result = await session.execute(
            select(Attendance).where(
                Attendance.game_day_id == game_day.id,
                Attendance.player_id == player.id
            )
        )
        att = att_result.scalar_one_or_none()
        if att and att.response == AttendanceResponse.YES:
            _gender = getattr(player, 'gender', 'm') or 'm'
            _signed = "записана" if _gender == 'f' else "записан"
            player_status = f"\n\n✅ <b>Ты {_signed} на эту игру!</b>"
        elif att and att.response == AttendanceResponse.WAITLIST:
            waitlist_list = [
                a for a in game_day.attendances
                if a.response == AttendanceResponse.WAITLIST
            ]
            waitlist_list.sort(key=lambda a: a.responded_at or datetime.min)
            pos = next((i + 1 for i, a in enumerate(waitlist_list) if a.player_id == player.id), "?")
            player_status = f"\n\n📋 <b>Ты в листе ожидания (#{pos})</b>"
        elif att and att.response == AttendanceResponse.NO:
            player_status = "\n\n❌ Ты отказался от этой игры."

    name_line = f"🏆 <b>{game_day.display_name}</b>\n" if game_day.tournament_number else ""
    text = (
        f"{name_line}"
        f"⚽ <b>Ближайшая игра</b>\n\n"
        f"📅 {game_day.scheduled_at.strftime('%d.%m.%Y %H:%M')}\n"
        f"📍 {game_day.location}\n"
        f"👥 Записалось: <b>{registered}/{game_day.player_limit}</b> "
        + (f"(свободно: {spots_left})" if spots_left > 0 else "(<b>мест нет</b>)")
        + (f"\n📋 Лист ожидания: {waitlist} чел." if waitlist > 0 else "")
        + player_status
    )

    await send(text, reply_markup=join_game_kb(game_day.id, game_day.is_open))


# ---------- Предварительный экран — согласие с Регламентом ----------

@router.callback_query(F.data.startswith("join_pre:"))
async def join_pre(call: CallbackQuery, player: Player | None):
    await call.answer()
    game_day_id = int(call.data.split(":")[1])

    if not player:
        await call.message.answer("❌ Сначала зарегистрируйся: /register")
        return

    lang = getattr(player, 'language', None) or 'ru'
    agreement = REGLAMENT_AGREEMENT_EN if lang == 'en' else REGLAMENT_AGREEMENT
    await call.message.edit_text(
        f"⚽ <b>Регистрация на игру</b>\n\n"
        f"{agreement}",
        reply_markup=join_confirm_kb(game_day_id, lang)
    )


@router.callback_query(F.data.startswith("decline_pre:"))
async def decline_pre(call: CallbackQuery):
    await call.answer("Отменено")
    await call.message.delete()


@router.callback_query(F.data == "closed")
async def closed_registration(call: CallbackQuery):
    await call.answer("🔒 Запись закрыта. Следи за анонсами!", show_alert=True)


# ---------- Записаться ----------

@router.callback_query(F.data.startswith("join:"))
async def join_game(call: CallbackQuery, session: AsyncSession, player: Player | None):
    await call.answer()
    game_day_id = int(call.data.split(":")[1])

    if not player:
        await call.message.answer("❌ Сначала зарегистрируйся: /register")
        return

    game_day = await session.get(
        GameDay, game_day_id,
        options=[selectinload(GameDay.attendances)]
    )
    if not game_day:
        await call.message.answer("❌ Игровой день не найден.")
        return

    if player.balance < 0 and settings.DEBUG is False:
        await call.message.answer(
            f"⚠️ У тебя долг {abs(player.balance)} сум.\n"
            "Сначала погаси долг — свяжись с организатором."
        )
        return

    result = await session.execute(
        select(Attendance).where(
            Attendance.game_day_id == game_day_id,
            Attendance.player_id == player.id
        )
    )
    existing = result.scalar_one_or_none()

    if existing and existing.response == AttendanceResponse.YES:
        await call.answer("Ты уже записан!", show_alert=True)
        return

    registered = sum(1 for a in game_day.attendances if a.response == AttendanceResponse.YES)
    is_full = registered >= game_day.player_limit

    if is_full:
        # Уже в листе ожидания — не добавлять повторно
        if existing and existing.response == AttendanceResponse.WAITLIST:
            waitlist_list = [
                a for a in game_day.attendances
                if a.response == AttendanceResponse.WAITLIST
            ]
            waitlist_list.sort(key=lambda a: a.responded_at or datetime.min)
            pos = next(
                (i + 1 for i, a in enumerate(waitlist_list) if a.player_id == player.id), "?"
            )
            await call.answer(f"Ты уже в листе ожидания (#{pos})!", show_alert=True)
            return

        # Добавить в лист ожидания
        waitlist_count = sum(
            1 for a in game_day.attendances
            if a.response == AttendanceResponse.WAITLIST
        )
        my_position = waitlist_count + 1

        if existing:
            existing.response = AttendanceResponse.WAITLIST
            existing.responded_at = datetime.now()
        else:
            session.add(Attendance(
                game_day_id=game_day_id,
                player_id=player.id,
                response=AttendanceResponse.WAITLIST,
                responded_at=datetime.now()
            ))
        await session.commit()

        lang = getattr(player, 'language', None) or 'ru'
        gender = getattr(player, 'gender', 'm') or 'm'
        await call.message.edit_text(
            t_g('join_waitlist', lang, gender, position=my_position)
        )
        return

    if not game_day.is_open:
        await call.message.answer("❌ Запись закрыта.")
        return

    if existing:
        existing.response = AttendanceResponse.YES
        existing.responded_at = datetime.now()
    else:
        session.add(Attendance(
            game_day_id=game_day_id,
            player_id=player.id,
            response=AttendanceResponse.YES,
            responded_at=datetime.now()
        ))

    await session.commit()

    lang = getattr(player, 'language', None) or 'ru'
    gender = getattr(player, 'gender', 'm') or 'm'
    await call.message.edit_text(
        t_g('join_success', lang, gender,
            date=game_day.scheduled_at.strftime('%d.%m.%Y %H:%M'),
            location=game_day.location)
    )


# ---------- Отказ от игры ----------

@router.callback_query(F.data.startswith("decline:"))
async def decline_game(call: CallbackQuery, session: AsyncSession,
                       player: Player | None, bot: Bot):
    await call.answer()
    game_day_id = int(call.data.split(":")[1])

    if not player:
        return

    result = await session.execute(
        select(Attendance).where(
            Attendance.game_day_id == game_day_id,
            Attendance.player_id == player.id
        )
    )
    existing = result.scalar_one_or_none()
    was_confirmed = existing and existing.response == AttendanceResponse.YES

    if existing:
        existing.response = AttendanceResponse.NO
        existing.responded_at = datetime.now()
    else:
        session.add(Attendance(
            game_day_id=game_day_id,
            player_id=player.id,
            response=AttendanceResponse.NO,
            responded_at=datetime.now()
        ))

    await session.commit()
    lang = getattr(player, 'language', None) or 'ru'
    gender = getattr(player, 'gender', 'm') or 'm'
    await call.message.edit_text(t_g('join_declined', lang, gender))

    if was_confirmed:
        await _notify_first_waitlist(session, game_day_id, bot)


async def _notify_first_waitlist(session: AsyncSession, game_day_id: int, bot: Bot):
    result = await session.execute(
        select(Attendance)
        .options(selectinload(Attendance.player))
        .where(
            Attendance.game_day_id == game_day_id,
            Attendance.response == AttendanceResponse.WAITLIST,
        )
        .order_by(Attendance.responded_at)
        .limit(1)
    )
    first = result.scalar_one_or_none()
    if not first:
        return

    game_day = await session.get(GameDay, game_day_id)
    if not game_day:
        return

    try:
        lang = getattr(first.player, 'language', None) or 'ru'
        gender = getattr(first.player, 'gender', 'm') or 'm'
        await bot.send_message(
            first.player.telegram_id,
            t_g('waitlist_promoted', lang, gender,
                date=game_day.scheduled_at.strftime('%d.%m.%Y %H:%M'),
                location=game_day.location),
            reply_markup=join_game_kb(game_day_id, game_day.is_open, lang)
        )
    except Exception as e:
        logger.warning(f"Cannot notify waitlist player {first.player.telegram_id}: {e}")


# ---------- Создание игрового дня ----------

@router.callback_query(F.data == "admin_create_gameday")
async def admin_create_gameday_start(call: CallbackQuery, state: FSMContext):
    if not settings.is_admin(call.from_user.id):
        await call.answer("⛔ Нет доступа", show_alert=True)
        return
    await call.answer()
    from aiogram.types import InlineKeyboardButton
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    cancel_kb = InlineKeyboardBuilder()
    cancel_kb.row(InlineKeyboardButton(text="❌ Отмена", callback_data="admin_back"))
    await call.message.edit_text(
        "📅 <b>Создание игрового дня</b>\n\n"
        "Введи дату и время игры в формате:\n"
        "<code>ДД.ММ.ГГГГ ЧЧ:ММ</code>\n\n"
        "Например: <code>28.04.2026 19:00</code>",
        reply_markup=cancel_kb.as_markup()
    )
    await state.set_state(CreateGameDayFSM.waiting_date)


@router.message(CreateGameDayFSM.waiting_date)
async def create_gd_date(message: Message, state: FSMContext):
    try:
        dt = datetime.strptime(message.text.strip(), "%d.%m.%Y %H:%M")
    except ValueError:
        await message.answer("❌ Неверный формат. Попробуй: <code>25.04.2026 18:00</code>")
        return

    await state.update_data(scheduled_at=dt.isoformat())
    await message.answer(
        f"✅ Дата: <b>{dt.strftime('%d.%m.%Y %H:%M')}</b>\n\n"
        "Введи адрес площадки:\n<i>Отмена: /cancel</i>"
    )
    await state.set_state(CreateGameDayFSM.waiting_location)


@router.message(CreateGameDayFSM.waiting_location)
async def create_gd_location(message: Message, state: FSMContext):
    await state.update_data(location=message.text.strip())
    await message.answer(
        f"✅ Место: <b>{message.text.strip()}</b>\n\n"
        f"Сколько игроков можно принять?\n"
        f"<i>(по умолчанию {settings.DEFAULT_PLAYER_LIMIT}, нажми /skip)</i>"
    )
    await state.set_state(CreateGameDayFSM.waiting_limit)


@router.message(CreateGameDayFSM.waiting_limit)
async def create_gd_limit(message: Message, state: FSMContext,
                          session: AsyncSession, bot: Bot):
    if message.text.strip() == "/skip":
        limit = settings.DEFAULT_PLAYER_LIMIT
    else:
        try:
            limit = int(message.text.strip())
            if limit < 2 or limit > 100:
                raise ValueError
        except ValueError:
            await message.answer("❌ Введи число от 2 до 100:")
            return

    data = await state.get_data()
    scheduled_at = datetime.fromisoformat(data["scheduled_at"])
    deadline = scheduled_at - timedelta(hours=settings.REGISTRATION_DEADLINE_HOURS)

    # Получить league_id из профиля создающего
    player_result = await session.execute(
        select(Player).where(Player.telegram_id == message.from_user.id)
    )
    creator = player_result.scalar_one_or_none()
    league_id = creator.league_id if creator else None

    # Вычислить следующий порядковый номер турнира (минимальный свободный)
    tournament_number = await _next_tournament_number(session, league_id)

    game_day = GameDay(
        scheduled_at=scheduled_at,
        location=data["location"],
        player_limit=limit,
        cost_per_player=0,  # устанавливается после игры через "Финансовый итог"
        registration_deadline=deadline,
        status=GameDayStatus.ANNOUNCED,
        league_id=league_id,
        tournament_number=tournament_number,
    )
    session.add(game_day)
    await session.commit()
    await session.refresh(game_day)
    await state.clear()

    schedule_reminders(game_day)

    from app.keyboards.main_menu import admin_menu_kb
    await message.answer(
        f"✅ <b>{game_day.display_name} создан!</b>\n\n"
        f"📅 {game_day.scheduled_at.strftime('%d.%m.%Y %H:%M')}\n"
        f"📍 {game_day.location}\n"
        f"👥 Лимит: {game_day.player_limit} игроков\n"
        f"🔒 Запись закрывается: {deadline.strftime('%d.%m %H:%M')}\n\n"
        "Анонс автоматически разослан всем игрокам лиги 📢",
        reply_markup=game_day_action_kb(game_day.id)
    )

    # Авторассылка анонса всем игрокам лиги
    await _auto_announce(session, bot, game_day, league_id)


async def _next_tournament_number(session: AsyncSession, league_id) -> int:
    """Возвращает наименьший свободный номер турнира для лиги."""
    from sqlalchemy import select as sa_select
    from app.database.models import GameDayStatus as GDS

    query = sa_select(GameDay.tournament_number).where(
        GameDay.status != GDS.CANCELLED,
        GameDay.tournament_number.is_not(None),
    )
    if league_id is not None:
        query = query.where(GameDay.league_id == league_id)

    result = await session.execute(query)
    used = {row[0] for row in result.all() if row[0] is not None}

    n = 1
    while n in used:
        n += 1
    return n


# ---------- Подтверждение участия (кнопки из напоминаний) ----------

@router.callback_query(F.data.startswith("confirm_yes:"))
async def confirm_attendance_yes(call: CallbackQuery, session: AsyncSession, player: Player | None):
    await call.answer()
    if not player:
        return

    game_day_id = int(call.data.split(":")[1])
    result = await session.execute(
        select(Attendance).where(
            Attendance.game_day_id == game_day_id,
            Attendance.player_id == player.id,
        )
    )
    att = result.scalar_one_or_none()

    if att and att.response == AttendanceResponse.YES:
        att.confirmed_final = True
        await session.commit()

    lang = getattr(player, 'language', None) or 'ru'
    await call.message.edit_text(t('confirm_yes_response', lang), parse_mode="HTML")


@router.callback_query(F.data.startswith("confirm_no:"))
async def confirm_attendance_no(call: CallbackQuery, session: AsyncSession,
                                player: Player | None, bot: Bot):
    await call.answer()
    if not player:
        return

    game_day_id = int(call.data.split(":")[1])
    result = await session.execute(
        select(Attendance).where(
            Attendance.game_day_id == game_day_id,
            Attendance.player_id == player.id,
        )
    )
    att = result.scalar_one_or_none()

    was_yes = att and att.response == AttendanceResponse.YES
    if att:
        att.response = AttendanceResponse.NO
        att.confirmed_final = False
        att.responded_at = datetime.now()
        await session.commit()

    lang = getattr(player, 'language', None) or 'ru'
    await call.message.edit_text(t('confirm_no_response', lang), parse_mode="HTML")

    if was_yes:
        await _notify_first_waitlist(session, game_day_id, bot)


async def _auto_announce(session: AsyncSession, bot: Bot,
                         game_day: GameDay, league_id) -> None:
    """Авторассылка анонса всем активным игрокам лиги через PlayerLeague."""
    if league_id is not None:
        result = await session.execute(
            select(Player)
            .join(PlayerLeague, PlayerLeague.player_id == Player.id)
            .where(
                PlayerLeague.league_id == league_id,
                Player.status == PlayerStatus.ACTIVE,
            )
        )
    else:
        result = await session.execute(
            select(Player).where(Player.status == PlayerStatus.ACTIVE)
        )
    players = result.scalars().all()

    text = (
        f"⚽ <b>Анонс игры — {game_day.display_name}!</b>\n\n"
        f"📅 {game_day.scheduled_at.strftime('%d.%m.%Y %H:%M')}\n"
        f"📍 {game_day.location}\n"
        f"👥 Мест: {game_day.player_limit}\n\n"
        "Успей записаться! 👇"
    )

    for p in players:
        try:
            await bot.send_message(
                p.telegram_id,
                text,
                reply_markup=join_game_kb(game_day.id, game_day.is_open)
            )
            await asyncio.sleep(0.05)
        except Exception as e:
            logger.warning(f"Cannot send announce to {p.telegram_id}: {e}")

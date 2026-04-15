from datetime import datetime, timedelta
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database.models import (
    GameDay, GameDayStatus, Attendance, AttendanceResponse,
    Player, MatchFormat
)
from app.keyboards.game_day import join_game_kb, game_day_action_kb

router = Router()


class CreateGameDayFSM(StatesGroup):
    waiting_date = State()
    waiting_location = State()
    waiting_limit = State()
    waiting_cost = State()
    waiting_format = State()


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

    result = await session.execute(
        select(GameDay)
        .where(GameDay.status.in_([GameDayStatus.ANNOUNCED, GameDayStatus.IN_PROGRESS]))
        .order_by(GameDay.scheduled_at)
        .limit(1)
    )
    game_day = result.scalar_one_or_none()

    if not game_day:
        await send("📅 Ближайших игр пока нет. Следи за анонсами!")
        return

    registered = sum(1 for a in game_day.attendances if a.response == AttendanceResponse.YES)
    spots_left = game_day.player_limit - registered

    # Статус игрока относительно этой игры
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
            player_status = "\n\n✅ <b>Ты записан на эту игру!</b>"
        elif att and att.response == AttendanceResponse.NO:
            player_status = "\n\n❌ Ты отказался от этой игры."

    text = (
        f"⚽ <b>Ближайшая игра</b>\n\n"
        f"📅 {game_day.scheduled_at.strftime('%d.%m.%Y %H:%M')}\n"
        f"📍 {game_day.location}\n"
        f"👥 Мест: <b>{registered}/{game_day.player_limit}</b> "
        + (f"(свободно: {spots_left})" if spots_left > 0 else "(<b>мест нет</b>)")
        + f"\n💰 Взнос: {game_day.cost_per_player} руб."
        + player_status
    )

    await send(text, reply_markup=join_game_kb(game_day.id, game_day.is_open))


# ---------- Записаться ----------

@router.callback_query(F.data.startswith("join:"))
async def join_game(call: CallbackQuery, session: AsyncSession, player: Player | None):
    await call.answer()
    game_day_id = int(call.data.split(":")[1])

    if not player:
        await call.message.answer("❌ Сначала зарегистрируйся: /register")
        return

    game_day = await session.get(GameDay, game_day_id)
    if not game_day or not game_day.is_open:
        await call.message.answer("❌ Запись закрыта или мест нет.")
        return

    # Проверить долг
    if player.balance < 0 and settings.DEBUG is False:
        await call.message.answer(
            f"⚠️ У тебя долг {abs(player.balance)} руб.\n"
            "Сначала погаси долг — свяжись с организатором."
        )
        return

    # Проверить не записан ли уже
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

    if existing:
        existing.response = AttendanceResponse.YES
        existing.responded_at = datetime.now()
    else:
        att = Attendance(
            game_day_id=game_day_id,
            player_id=player.id,
            response=AttendanceResponse.YES,
            responded_at=datetime.now()
        )
        session.add(att)

    await session.commit()

    registered = sum(1 for a in game_day.attendances if a.response == AttendanceResponse.YES) + 1
    await call.message.edit_text(
        f"✅ <b>Ты записан!</b>\n\n"
        f"📅 {game_day.scheduled_at.strftime('%d.%m.%Y %H:%M')}\n"
        f"📍 {game_day.location}\n"
        f"👥 Записано: {registered}/{game_day.player_limit}\n\n"
        "До встречи на поле! ⚽"
    )


# ---------- Отказ от игры ----------

@router.callback_query(F.data.startswith("decline:"))
async def decline_game(call: CallbackQuery, session: AsyncSession, player: Player | None):
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

    if existing:
        existing.response = AttendanceResponse.NO
        existing.responded_at = datetime.now()
    else:
        att = Attendance(
            game_day_id=game_day_id,
            player_id=player.id,
            response=AttendanceResponse.NO,
            responded_at=datetime.now()
        )
        session.add(att)

    await session.commit()
    await call.message.edit_text("❌ Понял, ты не придёшь. Увидимся в следующий раз!")


# ---------- Админ: создание игрового дня ----------

@router.callback_query(F.data == "admin_create_gameday")
async def admin_create_gameday_start(call: CallbackQuery, state: FSMContext):
    if not settings.is_admin(call.from_user.id):
        await call.answer("⛔ Нет доступа", show_alert=True)
        return
    await call.answer()
    await call.message.edit_text(
        "📅 <b>Создание игрового дня</b>\n\n"
        "Введи дату и время игры в формате:\n"
        "<code>ДД.ММ.ГГГГ ЧЧ:ММ</code>\n\n"
        "Например: <code>28.04.2026 19:00</code>\n\n"
        "<i>Отмена: /cancel</i>"
    )
    await state.set_state(CreateGameDayFSM.waiting_date)


@router.message(CreateGameDayFSM.waiting_date)
async def create_gd_date(message: Message, state: FSMContext):
    try:
        dt = datetime.strptime(message.text.strip(), "%d.%m.%Y %H:%M")
    except ValueError:
        await message.answer("❌ Неверный формат. Попробуй: <code>25.04.2026 18:00</code>")
        return

    await state.update_data(scheduled_at=dt.isoformat())  # строка, не datetime (JSON)
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
async def create_gd_limit(message: Message, state: FSMContext):
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

    await state.update_data(player_limit=limit)
    await message.answer(
        f"✅ Лимит: <b>{limit} игроков</b>\n\n"
        "Взнос с игрока (в рублях)? Введи 0 если бесплатно:"
    )
    await state.set_state(CreateGameDayFSM.waiting_cost)


@router.message(CreateGameDayFSM.waiting_cost)
async def create_gd_cost(message: Message, state: FSMContext, session: AsyncSession):
    try:
        cost = int(message.text.strip())
        if cost < 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ Введи целое число (0 или больше):")
        return

    data = await state.get_data()
    scheduled_at = datetime.fromisoformat(data["scheduled_at"])  # обратно в datetime
    deadline = scheduled_at - timedelta(hours=settings.REGISTRATION_DEADLINE_HOURS)

    game_day = GameDay(
        scheduled_at=scheduled_at,
        location=data["location"],
        player_limit=data["player_limit"],
        cost_per_player=cost,
        registration_deadline=deadline,
        status=GameDayStatus.ANNOUNCED,
    )
    session.add(game_day)
    await session.commit()
    await session.refresh(game_day)
    await state.clear()

    await message.answer(
        f"✅ <b>Игровой день создан!</b>\n\n"
        f"📅 {game_day.scheduled_at.strftime('%d.%m.%Y %H:%M')}\n"
        f"📍 {game_day.location}\n"
        f"👥 Лимит: {game_day.player_limit} игроков\n"
        f"💰 Взнос: {game_day.cost_per_player} руб.\n"
        f"🔒 Запись закрывается: {deadline.strftime('%d.%m %H:%M')}\n\n"
        "Теперь разошли анонс игрокам:",
        reply_markup=game_day_action_kb(game_day.id)
    )

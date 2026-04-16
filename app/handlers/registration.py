from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Player, Position, League
from app.keyboards.registration import position_kb, self_rating_kb
from app.keyboards.main_menu import main_menu_kb

router = Router()


class RegistrationFSM(StatesGroup):
    waiting_name = State()
    waiting_position = State()
    waiting_self_rating = State()
    waiting_photo = State()


@router.message(Command("register"))
async def cmd_register(message: Message, player: Player | None, state: FSMContext):
    if player is not None:
        await message.answer(
            f"✅ Ты уже зарегистрирован как <b>{player.name}</b>.\n"
            "Используй /start для главного меню."
        )
        return

    await message.answer(
        "📝 <b>Регистрация игрока</b>\n\n"
        "Шаг 1/4: Как тебя зовут?\n"
        "<i>Напиши своё имя (например: Алексей Иванов)</i>"
    )
    await state.set_state(RegistrationFSM.waiting_name)


@router.message(RegistrationFSM.waiting_name)
async def reg_name(message: Message, state: FSMContext):
    name = message.text.strip() if message.text else ""
    if len(name) < 2 or len(name) > 50:
        await message.answer("❌ Имя должно быть от 2 до 50 символов. Попробуй ещё раз:")
        return

    await state.update_data(name=name)
    await message.answer(
        f"👍 Отлично, <b>{name}</b>!\n\n"
        "Шаг 2/4: Выбери свою позицию на поле:",
        reply_markup=position_kb()
    )
    await state.set_state(RegistrationFSM.waiting_position)


@router.callback_query(RegistrationFSM.waiting_position, F.data.startswith("pos:"))
async def reg_position(call: CallbackQuery, state: FSMContext):
    position_value = call.data.split(":")[1]
    await state.update_data(position=position_value)
    await call.answer()

    from app.database.models import POSITION_LABELS
    pos_label = POSITION_LABELS.get(Position(position_value), position_value)

    await call.message.edit_text(
        f"✅ Позиция: {pos_label}\n\n"
        "Шаг 3/4: Оцени свой уровень игры от 1 до 10\n"
        "<i>1 = только начинаю, 10 = профессиональный уровень</i>\n\n"
        "Будь честен — это поможет сформировать сбалансированные команды:",
        reply_markup=self_rating_kb()
    )
    await state.set_state(RegistrationFSM.waiting_self_rating)


@router.callback_query(RegistrationFSM.waiting_self_rating, F.data.startswith("selfrating:"))
async def reg_self_rating(call: CallbackQuery, state: FSMContext):
    self_rating = int(call.data.split(":")[1])
    await state.update_data(self_rating=self_rating)
    await call.answer()

    await call.message.edit_text(
        f"✅ Оценка: <b>{self_rating}/10</b>\n\n"
        "Шаг 4/4: Пришли своё фото 📸\n\n"
        "<i>Это фото будет отображаться в твоём профиле.\n"
        "Если не хочешь — напиши /skip</i>"
    )
    await state.set_state(RegistrationFSM.waiting_photo)


@router.message(RegistrationFSM.waiting_photo, F.photo)
async def reg_photo(message: Message, state: FSMContext, session: AsyncSession):
    # Берём самое большое фото (последнее в массиве)
    photo_file_id = message.photo[-1].file_id
    await _finish_registration(message, state, session, photo_file_id)


@router.message(RegistrationFSM.waiting_photo, F.text == "/skip")
async def reg_photo_skip(message: Message, state: FSMContext, session: AsyncSession):
    await _finish_registration(message, state, session, photo_file_id=None)


@router.message(RegistrationFSM.waiting_photo)
async def reg_photo_wrong(message: Message):
    await message.answer(
        "📸 Пожалуйста, пришли <b>фотографию</b> или напиши /skip чтобы пропустить."
    )


async def _finish_registration(message: Message, state: FSMContext,
                                session: AsyncSession, photo_file_id: str | None):
    data = await state.get_data()
    pending_invite_code = data.get("pending_invite_code")

    # Определить лигу по инвайт-коду (если пришёл по ссылке)
    league_id = None
    if pending_invite_code:
        league_res = await session.execute(
            select(League).where(
                League.invite_code == pending_invite_code,
                League.is_active == True,
            )
        )
        league = league_res.scalar_one_or_none()
        if league:
            league_id = league.id

    # Если инвайт-кода нет, привязать к дефолтной лиге (первая по id)
    if league_id is None:
        default_res = await session.execute(
            select(League).order_by(League.id).limit(1)
        )
        default_league = default_res.scalar_one_or_none()
        if default_league:
            league_id = default_league.id

    new_player = Player(
        telegram_id=message.from_user.id,
        username=message.from_user.username,
        name=data["name"],
        position=Position(data["position"]),
        self_rating=data["self_rating"],
        rating=round(data["self_rating"] * 0.85, 1),
        rating_provisional=True,
        photo_file_id=photo_file_id,
        league_id=league_id,
    )
    session.add(new_player)
    await session.commit()
    await state.clear()

    from app.database.models import POSITION_LABELS
    pos_label = POSITION_LABELS.get(new_player.position, new_player.position)
    photo_line = "📸 Фото: добавлено ✅" if photo_file_id else "📸 Фото: не добавлено"

    text = (
        f"🎉 <b>Добро пожаловать в команду!</b>\n\n"
        f"👤 Имя: <b>{new_player.name}</b>\n"
        f"📍 Позиция: {pos_label}\n"
        f"⭐ Стартовый рейтинг: <b>{new_player.rating:.1f}</b> <i>(провизорный)</i>\n"
        f"{photo_line}\n\n"
        "Рейтинг уточнится после того как другие игроки тебя оценят."
    )

    if photo_file_id:
        await message.answer_photo(
            photo=photo_file_id,
            caption=text,
            reply_markup=main_menu_kb()
        )
    else:
        await message.answer(text, reply_markup=main_menu_kb())

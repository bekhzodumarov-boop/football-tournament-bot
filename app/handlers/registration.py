from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Player, Position, League, POSITION_LABELS
from app.keyboards.registration import position_kb, self_rating_kb
from app.keyboards.main_menu import main_menu_kb, language_kb
from app.locales.texts import t

router = Router()


class RegistrationFSM(StatesGroup):
    waiting_name = State()
    waiting_position = State()
    waiting_self_rating = State()
    waiting_phone = State()
    waiting_photo = State()


class EditProfileFSM(StatesGroup):
    choosing = State()
    waiting_name = State()
    waiting_position = State()
    waiting_phone = State()
    waiting_photo = State()


# ── Cancel работает в любом FSM-состоянии (регистрируется ПЕРВЫМ) ──

@router.message(Command("cancel"))
async def reg_cancel(message: Message, state: FSMContext):
    current = await state.get_state()
    if current is None:
        await message.answer("Нечего отменять.")
        return
    await state.clear()
    await message.answer(
        "❌ Действие отменено.\n\n"
        "Используй /start для главного меню."
    )


# ══════════════════════════════════════════════════════
#  РЕГИСТРАЦИЯ
# ══════════════════════════════════════════════════════

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
        "Шаг 1/5: Как тебя зовут?\n"
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
        "Шаг 2/5: Выбери свою позицию на поле:",
        reply_markup=position_kb()
    )
    await state.set_state(RegistrationFSM.waiting_position)


@router.callback_query(RegistrationFSM.waiting_position, F.data.startswith("pos:"))
async def reg_position(call: CallbackQuery, state: FSMContext):
    position_value = call.data.split(":")[1]
    await state.update_data(position=position_value)
    await call.answer()

    pos_label = POSITION_LABELS.get(Position(position_value), position_value)

    await call.message.edit_text(
        f"✅ Позиция: {pos_label}\n\n"
        "Шаг 3/5: Оцени свой уровень игры от 1 до 10\n"
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

    skip_kb = InlineKeyboardBuilder()
    skip_kb.row(InlineKeyboardButton(text="⏭ Пропустить", callback_data="reg_skip_phone"))

    await call.message.edit_text(
        f"✅ Оценка: <b>{self_rating}/10</b>\n\n"
        "Шаг 4/5: Напиши свой <b>номер телефона</b> 📱\n\n"
        "<i>Например: +998901234567\n"
        "Если не хочешь — нажми Пропустить</i>",
        reply_markup=skip_kb.as_markup()
    )
    await state.set_state(RegistrationFSM.waiting_phone)


@router.callback_query(RegistrationFSM.waiting_phone, F.data == "reg_skip_phone")
async def reg_skip_phone(call: CallbackQuery, state: FSMContext):
    await call.answer()
    await state.update_data(phone=None)
    await call.message.edit_text(
        "Шаг 5/5: Пришли своё фото 📸\n\n"
        "<i>Это фото будет отображаться в твоём профиле.\n"
        "Если не хочешь — напиши /skip</i>"
    )
    await state.set_state(RegistrationFSM.waiting_photo)


@router.message(RegistrationFSM.waiting_phone)
async def reg_phone(message: Message, state: FSMContext):
    phone = message.text.strip() if message.text else ""
    # Минимальная валидация
    cleaned = phone.replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
    if len(cleaned) < 7 or len(cleaned) > 20:
        await message.answer(
            "❌ Введи корректный номер телефона (от 7 до 20 символов).\n"
            "Или напиши /cancel чтобы отменить регистрацию."
        )
        return

    await state.update_data(phone=phone)
    await message.answer(
        f"✅ Телефон: <b>{phone}</b>\n\n"
        "Шаг 5/5: Пришли своё фото 📸\n\n"
        "<i>Это фото будет отображаться в твоём профиле.\n"
        "Если не хочешь — напиши /skip</i>"
    )
    await state.set_state(RegistrationFSM.waiting_photo)


@router.message(RegistrationFSM.waiting_photo, F.photo)
async def reg_photo(message: Message, state: FSMContext, session: AsyncSession):
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
        phone=data.get("phone"),
        league_id=league_id,
    )
    session.add(new_player)
    await session.commit()
    await state.clear()

    pos_label = POSITION_LABELS.get(new_player.position, new_player.position)
    photo_line = "📸 Фото: добавлено ✅" if photo_file_id else "📸 Фото: не добавлено"
    phone_line = f"📱 Телефон: {new_player.phone}" if new_player.phone else ""

    text = (
        f"🎉 <b>Добро пожаловать в команду!</b>\n\n"
        f"👤 Имя: <b>{new_player.name}</b>\n"
        f"📍 Позиция: {pos_label}\n"
        f"⭐ Стартовый рейтинг: <b>{new_player.rating:.1f}</b> <i>(провизорный)</i>\n"
        f"{photo_line}\n"
        + (f"{phone_line}\n" if phone_line else "")
        + "\nРейтинг уточнится после того как другие игроки тебя оценят."
    )

    if photo_file_id:
        await message.answer_photo(photo=photo_file_id, caption=text, reply_markup=main_menu_kb())
    else:
        await message.answer(text, reply_markup=main_menu_kb())


# ══════════════════════════════════════════════════════
#  РЕДАКТИРОВАНИЕ ПРОФИЛЯ
# ══════════════════════════════════════════════════════

def _edit_profile_menu_kb() -> object:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="✏️ Имя", callback_data="ep_name"))
    builder.row(
        InlineKeyboardButton(text="📍 Позиция", callback_data="ep_position"),
        InlineKeyboardButton(text="📱 Телефон", callback_data="ep_phone"),
    )
    builder.row(InlineKeyboardButton(text="📸 Фото", callback_data="ep_photo"))
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="main_menu"))
    return builder.as_markup()


@router.message(Command("edit_profile"))
@router.callback_query(F.data == "edit_profile")
async def cmd_edit_profile(event, player: Player | None, state: FSMContext):
    is_cb = isinstance(event, CallbackQuery)
    if is_cb:
        await event.answer()
        send = event.message.edit_text
    else:
        send = event.answer

    if not player:
        await send("❌ Сначала зарегистрируйся: /register")
        return

    await state.set_state(EditProfileFSM.choosing)
    pos_label = POSITION_LABELS.get(player.position, player.position)
    username_line = f"@{player.username}" if player.username else "—"

    await send(
        f"✏️ <b>Редактирование профиля</b>\n\n"
        f"👤 Имя: <b>{player.name}</b>\n"
        f"📍 Позиция: {pos_label}\n"
        f"📱 Телефон: {player.phone or '—'}\n"
        f"📸 Фото: {'есть' if player.photo_file_id else 'нет'}\n"
        f"🔗 Telegram: {username_line} <i>(нельзя изменить)</i>\n\n"
        "Что хочешь изменить?",
        reply_markup=_edit_profile_menu_kb()
    )


# -- Изменить имя --

@router.callback_query(EditProfileFSM.choosing, F.data == "ep_name")
async def ep_name_start(call: CallbackQuery, state: FSMContext):
    await call.answer()
    await state.set_state(EditProfileFSM.waiting_name)
    cancel_kb = InlineKeyboardBuilder()
    cancel_kb.row(InlineKeyboardButton(text="❌ Отмена", callback_data="edit_profile"))
    await call.message.edit_text(
        "✏️ Введи новое имя:", reply_markup=cancel_kb.as_markup()
    )


@router.message(EditProfileFSM.waiting_name)
async def ep_name_save(message: Message, state: FSMContext, session: AsyncSession,
                       player: Player | None):
    name = message.text.strip() if message.text else ""
    if len(name) < 2 or len(name) > 50:
        await message.answer("❌ Имя должно быть от 2 до 50 символов:")
        return
    if player:
        player.name = name
        await session.commit()
    await state.set_state(EditProfileFSM.choosing)
    await message.answer(
        f"✅ Имя изменено на <b>{name}</b>.",
        reply_markup=_edit_profile_menu_kb()
    )


# -- Изменить позицию --

@router.callback_query(EditProfileFSM.choosing, F.data == "ep_position")
async def ep_position_start(call: CallbackQuery, state: FSMContext):
    await call.answer()
    await state.set_state(EditProfileFSM.waiting_position)
    await call.message.edit_text(
        "📍 Выбери новую позицию:", reply_markup=position_kb()
    )


@router.callback_query(EditProfileFSM.waiting_position, F.data.startswith("pos:"))
async def ep_position_save(call: CallbackQuery, state: FSMContext, session: AsyncSession,
                           player: Player | None):
    await call.answer()
    position_value = call.data.split(":")[1]
    if player:
        player.position = Position(position_value)
        await session.commit()
    await state.set_state(EditProfileFSM.choosing)
    pos_label = POSITION_LABELS.get(Position(position_value), position_value)
    await call.message.edit_text(
        f"✅ Позиция изменена на <b>{pos_label}</b>.",
        reply_markup=_edit_profile_menu_kb()
    )


# -- Изменить телефон --

@router.callback_query(EditProfileFSM.choosing, F.data == "ep_phone")
async def ep_phone_start(call: CallbackQuery, state: FSMContext, player: Player | None):
    await call.answer()
    await state.set_state(EditProfileFSM.waiting_phone)
    cancel_kb = InlineKeyboardBuilder()
    if player and player.phone:
        cancel_kb.row(InlineKeyboardButton(text="🗑 Удалить номер", callback_data="ep_phone_clear"))
    cancel_kb.row(InlineKeyboardButton(text="❌ Отмена", callback_data="edit_profile"))
    await call.message.edit_text(
        f"📱 Введи новый номер телефона:\n\n"
        f"<i>Сейчас: {player.phone if player and player.phone else '—'}</i>",
        reply_markup=cancel_kb.as_markup()
    )


@router.callback_query(EditProfileFSM.waiting_phone, F.data == "ep_phone_clear")
async def ep_phone_clear(call: CallbackQuery, state: FSMContext, session: AsyncSession,
                         player: Player | None):
    await call.answer()
    if player:
        player.phone = None
        await session.commit()
    await state.set_state(EditProfileFSM.choosing)
    await call.message.edit_text("✅ Номер телефона удалён.", reply_markup=_edit_profile_menu_kb())


@router.message(EditProfileFSM.waiting_phone)
async def ep_phone_save(message: Message, state: FSMContext, session: AsyncSession,
                        player: Player | None):
    phone = message.text.strip() if message.text else ""
    cleaned = phone.replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
    if len(cleaned) < 7 or len(cleaned) > 20:
        await message.answer("❌ Введи корректный номер (7-20 символов):")
        return
    if player:
        player.phone = phone
        await session.commit()
    await state.set_state(EditProfileFSM.choosing)
    await message.answer(
        f"✅ Телефон обновлён: <b>{phone}</b>.",
        reply_markup=_edit_profile_menu_kb()
    )


# -- Изменить фото --

@router.callback_query(EditProfileFSM.choosing, F.data == "ep_photo")
async def ep_photo_start(call: CallbackQuery, state: FSMContext):
    await call.answer()
    await state.set_state(EditProfileFSM.waiting_photo)
    cancel_kb = InlineKeyboardBuilder()
    cancel_kb.row(InlineKeyboardButton(text="❌ Отмена", callback_data="edit_profile"))
    await call.message.edit_text(
        "📸 Пришли новое фото или напиши /skip чтобы убрать текущее:",
        reply_markup=cancel_kb.as_markup()
    )


@router.message(EditProfileFSM.waiting_photo, F.photo)
async def ep_photo_save(message: Message, state: FSMContext, session: AsyncSession,
                        player: Player | None):
    photo_file_id = message.photo[-1].file_id
    if player:
        player.photo_file_id = photo_file_id
        await session.commit()
    await state.set_state(EditProfileFSM.choosing)
    await message.answer_photo(
        photo=photo_file_id,
        caption="✅ Фото обновлено!",
        reply_markup=_edit_profile_menu_kb()
    )


@router.message(EditProfileFSM.waiting_photo, F.text == "/skip")
async def ep_photo_remove(message: Message, state: FSMContext, session: AsyncSession,
                          player: Player | None):
    if player:
        player.photo_file_id = None
        await session.commit()
    await state.set_state(EditProfileFSM.choosing)
    await message.answer("✅ Фото удалено.", reply_markup=_edit_profile_menu_kb())


@router.message(EditProfileFSM.waiting_photo)
async def ep_photo_wrong(message: Message):
    await message.answer("📸 Пришли фото или напиши /skip")

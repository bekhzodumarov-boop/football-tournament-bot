"""
Дополнительные хендлеры Admin:
  - Активные игры
  - Прошедшие игры
  - Финансовый итог
  - Моя лига
  - /create_league команда
"""
from aiogram import Router, F, Bot
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database.models import (
    GameDay, GameDayStatus, Attendance, AttendanceResponse,
    Player, Match, League,
)
from app.database.models import _gen_invite_code

router = Router()


class FinancialSummaryFSM(StatesGroup):
    waiting_expenses = State()
    waiting_players_count = State()
    waiting_confirm = State()


class CreateLeagueFSM(StatesGroup):
    waiting_name = State()
    waiting_city = State()


# ══════════════════════════════════════════════════════
#  АКТИВНЫЕ ИГРЫ
# ══════════════════════════════════════════════════════

@router.callback_query(F.data == "admin_active_games")
async def adm_active_games(call: CallbackQuery, session: AsyncSession):
    if not settings.is_admin(call.from_user.id):
        await call.answer("⛔", show_alert=True)
        return
    await call.answer()

    from app.keyboards.main_menu import admin_menu_kb

    p_res = await session.execute(
        select(Player).where(Player.telegram_id == call.from_user.id)
    )
    admin_player = p_res.scalar_one_or_none()
    league_id = admin_player.league_id if admin_player else None

    query = (
        select(GameDay)
        .options(selectinload(GameDay.attendances))
        .where(GameDay.status.in_([
            GameDayStatus.ANNOUNCED,
            GameDayStatus.CLOSED,
            GameDayStatus.IN_PROGRESS,
        ]))
        .order_by(GameDay.scheduled_at)
    )
    if league_id is not None:
        query = query.where(GameDay.league_id == league_id)

    result = await session.execute(query)
    game_days = result.scalars().all()

    if not game_days:
        await call.message.edit_text(
            "📋 Нет активных игровых дней.",
            reply_markup=admin_menu_kb()
        )
        return

    builder = InlineKeyboardBuilder()
    for gd in game_days:
        registered = sum(1 for a in gd.attendances if a.response == AttendanceResponse.YES)
        waitlist = sum(1 for a in gd.attendances if a.response == AttendanceResponse.WAITLIST)
        wl_str = f" | ⏳{waitlist}" if waitlist > 0 else ""
        status_emoji = {"announced": "🟢", "closed": "🔴", "in_progress": "⚡"}.get(
            gd.status.value, "❓")
        builder.row(InlineKeyboardButton(
            text=f"{status_emoji} {gd.display_name} — {gd.scheduled_at.strftime('%d.%m')} | 👥{registered}/{gd.player_limit}{wl_str}",
            callback_data=f"gd_players:{gd.id}"
        ))
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back"))

    await call.message.edit_text(
        "📋 <b>Активные игровые дни</b>\n\n"
        "🟢 Открыта запись  ⚡ В процессе  🔴 Запись закрыта",
        reply_markup=builder.as_markup()
    )


# ══════════════════════════════════════════════════════
#  ПРОШЕДШИЕ ИГРЫ
# ══════════════════════════════════════════════════════

@router.callback_query(F.data == "admin_past_games")
async def adm_past_games(call: CallbackQuery, session: AsyncSession):
    if not settings.is_admin(call.from_user.id):
        await call.answer("⛔", show_alert=True)
        return
    await call.answer()

    from app.keyboards.main_menu import admin_menu_kb

    p_res = await session.execute(
        select(Player).where(Player.telegram_id == call.from_user.id)
    )
    admin_player = p_res.scalar_one_or_none()
    league_id = admin_player.league_id if admin_player else None

    query = (
        select(GameDay)
        .options(
            selectinload(GameDay.attendances),
            selectinload(GameDay.matches),
        )
        .where(GameDay.status.in_([GameDayStatus.FINISHED, GameDayStatus.CANCELLED]))
        .order_by(GameDay.scheduled_at.desc())
        .limit(20)
    )
    if league_id is not None:
        query = query.where(GameDay.league_id == league_id)

    result = await session.execute(query)
    game_days = result.scalars().all()

    if not game_days:
        await call.message.edit_text(
            "📁 Нет завершённых игровых дней.",
            reply_markup=admin_menu_kb()
        )
        return

    builder = InlineKeyboardBuilder()
    for gd in game_days:
        registered = sum(1 for a in gd.attendances if a.response == AttendanceResponse.YES)
        matches_count = len(gd.matches)
        status_emoji = "✅" if gd.status == GameDayStatus.FINISHED else "❌"
        builder.row(InlineKeyboardButton(
            text=f"{status_emoji} {gd.display_name} — {gd.scheduled_at.strftime('%d.%m.%Y')} | 👥{registered} | ⚽{matches_count}",
            callback_data=f"adm_past_detail:{gd.id}"
        ))
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back"))

    await call.message.edit_text(
        "📁 <b>Прошедшие игровые дни</b> (последние 20)",
        reply_markup=builder.as_markup()
    )


@router.callback_query(F.data.startswith("adm_past_detail:"))
async def adm_past_detail(call: CallbackQuery, session: AsyncSession):
    if not settings.is_admin(call.from_user.id):
        await call.answer("⛔", show_alert=True)
        return
    await call.answer()

    game_day_id = int(call.data.split(":")[1])
    game_day = await session.get(
        GameDay, game_day_id,
        options=[
            selectinload(GameDay.attendances).selectinload(Attendance.player),
            selectinload(GameDay.matches).selectinload(Match.team_home),
            selectinload(GameDay.matches).selectinload(Match.team_away),
        ]
    )
    if not game_day:
        await call.message.edit_text("❌ Игровой день не найден.")
        return

    attendees = [a for a in game_day.attendances if a.response == AttendanceResponse.YES]
    finished_matches = [m for m in game_day.matches if m.status.value == "finished"]

    lines = [
        f"📁 <b>{game_day.display_name}</b>",
        f"📅 {game_day.scheduled_at.strftime('%d.%m.%Y %H:%M')}",
        f"📍 {game_day.location}",
        f"👥 Игроков пришло: {len(attendees)}",
    ]
    if game_day.cost_per_player > 0:
        lines.append(f"💰 Взнос: {game_day.cost_per_player:,} сум.")
    lines.append("")

    if finished_matches:
        lines.append("⚽ <b>Результаты матчей:</b>")
        for m in finished_matches:
            lines.append(f"  {m.team_home.name} {m.score_home}:{m.score_away} {m.team_away.name}")
        lines.append("")

    if attendees:
        lines.append("👥 <b>Участники:</b>")
        for a in attendees[:15]:
            lines.append(f"  • {a.player.name}")
        if len(attendees) > 15:
            lines.append(f"  ...и ещё {len(attendees) - 15} чел.")

    builder = InlineKeyboardBuilder()
    if game_day.cost_per_player == 0 and game_day.status == GameDayStatus.FINISHED:
        builder.row(InlineKeyboardButton(
            text="💸 Рассчитать финансовый итог",
            callback_data=f"gd_finance:{game_day_id}"
        ))
    builder.row(InlineKeyboardButton(text="🔙 К списку", callback_data="admin_past_games"))

    await call.message.edit_text(
        "\n".join(lines),
        reply_markup=builder.as_markup()
    )


# ══════════════════════════════════════════════════════
#  ФИНАНСОВЫЙ ИТОГ
# ══════════════════════════════════════════════════════

@router.callback_query(F.data.startswith("gd_finance:"))
async def gd_finance_start(call: CallbackQuery, state: FSMContext, session: AsyncSession):
    if not settings.is_admin(call.from_user.id):
        await call.answer("⛔", show_alert=True)
        return
    await call.answer()

    game_day_id = int(call.data.split(":")[1])
    game_day = await session.get(
        GameDay, game_day_id,
        options=[selectinload(GameDay.attendances)]
    )
    if not game_day:
        return

    attended = sum(1 for a in game_day.attendances if a.response == AttendanceResponse.YES)
    await state.update_data(game_day_id=game_day_id, attended=attended)
    await state.set_state(FinancialSummaryFSM.waiting_expenses)

    cancel_kb = InlineKeyboardBuilder()
    cancel_kb.row(InlineKeyboardButton(text="❌ Отмена", callback_data="admin_back"))

    await call.message.edit_text(
        f"💸 <b>Финансовый итог — {game_day.display_name}</b>\n\n"
        f"📅 {game_day.scheduled_at.strftime('%d.%m.%Y')}\n"
        f"👥 Записалось: {attended} игроков\n\n"
        "Введи <b>общую сумму расходов</b> за эту игру (аренда + прочее) в сумах:",
        reply_markup=cancel_kb.as_markup()
    )


@router.message(StateFilter(FinancialSummaryFSM.waiting_expenses))
async def gd_finance_expenses(message: Message, state: FSMContext):
    if not settings.is_admin(message.from_user.id):
        return
    try:
        expenses = int(message.text.strip().replace(" ", "").replace(",", ""))
        if expenses < 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ Введи целое число (сумма в сумах):")
        return

    data = await state.get_data()
    attended = data.get("attended", 0)
    await state.update_data(expenses=expenses)
    await state.set_state(FinancialSummaryFSM.waiting_players_count)

    cancel_kb = InlineKeyboardBuilder()
    cancel_kb.row(InlineKeyboardButton(
        text=f"✅ Использовать {attended} (по записи)",
        callback_data=f"fin_use_attended:{attended}"
    ))
    cancel_kb.row(InlineKeyboardButton(text="❌ Отмена", callback_data="admin_back"))

    await message.answer(
        f"✅ Расходы: <b>{expenses:,} сум.</b>\n\n"
        f"Сколько игроков <b>фактически пришло</b>?\n"
        f"<i>По записи: {attended} чел. — нажми кнопку или введи число вручную.</i>",
        reply_markup=cancel_kb.as_markup()
    )


@router.callback_query(F.data.startswith("fin_use_attended:"))
async def gd_finance_use_attended(call: CallbackQuery, state: FSMContext, session: AsyncSession):
    await call.answer()
    count = int(call.data.split(":")[1])
    await _compute_finance(call.message, state, session, count, edit=True)


@router.message(StateFilter(FinancialSummaryFSM.waiting_players_count))
async def gd_finance_player_count(message: Message, state: FSMContext, session: AsyncSession):
    if not settings.is_admin(message.from_user.id):
        return
    try:
        count = int(message.text.strip())
        if count <= 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ Введи число игроков (больше 0):")
        return
    await _compute_finance(message, state, session, count, edit=False)


async def _compute_finance(msg, state: FSMContext, session: AsyncSession,
                            count: int, edit: bool):
    data = await state.get_data()
    expenses = data["expenses"]
    game_day_id = data["game_day_id"]
    cost_per = expenses // count if count > 0 else 0

    await state.update_data(cost_per=cost_per, count=count)
    await state.set_state(FinancialSummaryFSM.waiting_confirm)

    game_day = await session.get(GameDay, game_day_id)

    confirm_kb = InlineKeyboardBuilder()
    confirm_kb.row(
        InlineKeyboardButton(
            text=f"✅ Подтвердить {cost_per:,} сум.",
            callback_data="fin_confirm"
        ),
        InlineKeyboardButton(text="✏️ Другая сумма", callback_data="fin_edit"),
    )
    confirm_kb.row(InlineKeyboardButton(text="❌ Отмена", callback_data="admin_back"))

    text = (
        f"💸 <b>Финансовый итог — {game_day.display_name}</b>\n\n"
        f"📊 Расходы: <b>{expenses:,} сум.</b>\n"
        f"👥 Пришло: <b>{count} чел.</b>\n"
        f"━━━━━━━━━━━━━━\n"
        f"💰 Взнос на человека: <b>{cost_per:,} сум.</b>\n\n"
        "Подтвердить или ввести другую сумму?"
    )

    if edit:
        await msg.edit_text(text, reply_markup=confirm_kb.as_markup())
    else:
        await msg.answer(text, reply_markup=confirm_kb.as_markup())


@router.callback_query(F.data == "fin_edit")
async def gd_finance_edit(call: CallbackQuery, state: FSMContext):
    await call.answer()
    await state.set_state(FinancialSummaryFSM.waiting_confirm)
    cancel_kb = InlineKeyboardBuilder()
    cancel_kb.row(InlineKeyboardButton(text="❌ Отмена", callback_data="admin_back"))
    await call.message.edit_text(
        "✏️ Введи итоговую сумму взноса на одного игрока (в сумах):",
        reply_markup=cancel_kb.as_markup()
    )


@router.message(StateFilter(FinancialSummaryFSM.waiting_confirm))
async def gd_finance_manual_cost(message: Message, state: FSMContext,
                                  session: AsyncSession, bot: Bot):
    if not settings.is_admin(message.from_user.id):
        return
    try:
        cost_per = int(message.text.strip().replace(" ", "").replace(",", ""))
        if cost_per < 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ Введи целое число:")
        return
    await state.update_data(cost_per=cost_per)
    await _broadcast_finance(message, state, session, bot)


@router.callback_query(F.data == "fin_confirm")
async def gd_finance_confirm(call: CallbackQuery, state: FSMContext,
                              session: AsyncSession, bot: Bot):
    await call.answer()
    await _broadcast_finance(call.message, state, session, bot)


async def _broadcast_finance(msg, state: FSMContext, session: AsyncSession, bot: Bot):
    data = await state.get_data()
    await state.clear()

    game_day_id = data["game_day_id"]
    cost_per = data["cost_per"]

    game_day = await session.get(
        GameDay, game_day_id,
        options=[selectinload(GameDay.attendances).selectinload(Attendance.player)]
    )
    if not game_day:
        return

    game_day.cost_per_player = cost_per
    await session.commit()

    attendees = [a for a in game_day.attendances if a.response == AttendanceResponse.YES]
    text = (
        f"💰 <b>Взнос за {game_day.display_name}</b>\n\n"
        f"📅 {game_day.scheduled_at.strftime('%d.%m.%Y')}\n"
        f"📍 {game_day.location}\n\n"
        f"💵 Сумма к оплате: <b>{cost_per:,} сум.</b>\n\n"
        "Пожалуйста, оплати взнос организатору. Спасибо! 🙏"
    )

    sent = 0
    for att in attendees:
        try:
            await bot.send_message(att.player.telegram_id, text)
            sent += 1
        except Exception:
            pass

    from app.keyboards.main_menu import admin_menu_kb
    await msg.answer(
        f"✅ <b>Финансовый итог отправлен!</b>\n\n"
        f"💰 Взнос: {cost_per:,} сум.\n"
        f"📨 Уведомлено: {sent} игроков",
        reply_markup=admin_menu_kb()
    )


# ══════════════════════════════════════════════════════
#  МОЯ ЛИГА — просмотр и инвайт
# ══════════════════════════════════════════════════════

@router.callback_query(F.data == "admin_league_info")
async def adm_league_info(call: CallbackQuery, session: AsyncSession):
    if not settings.is_admin(call.from_user.id):
        await call.answer("⛔", show_alert=True)
        return
    await call.answer()

    from app.keyboards.main_menu import admin_menu_kb
    from app.config import settings as cfg

    p_res = await session.execute(
        select(Player).where(Player.telegram_id == call.from_user.id)
    )
    admin_player = p_res.scalar_one_or_none()

    if not admin_player or not admin_player.league_id:
        builder = InlineKeyboardBuilder()
        builder.row(InlineKeyboardButton(
            text="➕ Создать лигу", callback_data="cmd_create_league"
        ))
        builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back"))
        await call.message.edit_text(
            "⚠️ Ты не привязан ни к одной лиге.\n\n"
            "Создай лигу для своей группы и поделись инвайт-ссылкой с участниками:",
            reply_markup=builder.as_markup()
        )
        return

    league = await session.get(League, admin_player.league_id)
    if not league:
        await call.message.edit_text("❌ Лига не найдена.", reply_markup=admin_menu_kb())
        return

    players_res = await session.execute(
        select(Player).where(
            Player.league_id == league.id,
            Player.status == "active"
        )
    )
    players = players_res.scalars().all()

    # Получить username бота из settings если есть, иначе дефолт
    bot_username = getattr(cfg, "BOT_USERNAME", "football_manager_2026_bot")
    invite_link = f"https://t.me/{bot_username}?start=join_{league.invite_code}"

    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🔗 Поделиться ссылкой", url=invite_link))
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back"))

    await call.message.edit_text(
        f"🌐 <b>Моя лига</b>\n\n"
        f"🏆 <b>{league.name}</b>\n"
        f"📍 {league.city or '—'}\n"
        f"🔑 Инвайт-код: <code>{league.invite_code}</code>\n"
        f"👥 Активных игроков: {len(players)}\n\n"
        f"🔗 Ссылка для приглашения:\n<code>{invite_link}</code>\n\n"
        "Поделись этой ссылкой — новые участники автоматически попадут в твою лигу.",
        reply_markup=builder.as_markup()
    )


@router.callback_query(F.data == "cmd_create_league")
@router.message(Command("create_league"))
async def create_league_start(event, state: FSMContext):
    is_cb = isinstance(event, CallbackQuery)
    if is_cb:
        if not settings.is_admin(event.from_user.id):
            await event.answer("⛔", show_alert=True)
            return
        await event.answer()
        send = event.message.edit_text
    else:
        if not settings.is_admin(event.from_user.id):
            return
        send = event.answer

    await state.set_state(CreateLeagueFSM.waiting_name)
    cancel_kb = InlineKeyboardBuilder()
    cancel_kb.row(InlineKeyboardButton(text="❌ Отмена", callback_data="admin_back"))
    await send(
        "🌐 <b>Создание лиги</b>\n\n"
        "Введи название лиги (например: <i>Ташкент FC</i>):",
        reply_markup=cancel_kb.as_markup()
    )


@router.message(StateFilter(CreateLeagueFSM.waiting_name))
async def create_league_name(message: Message, state: FSMContext):
    if not settings.is_admin(message.from_user.id):
        return
    name = message.text.strip()
    if not name:
        await message.answer("❌ Введи название:")
        return
    await state.update_data(name=name)
    await state.set_state(CreateLeagueFSM.waiting_city)

    skip_kb = InlineKeyboardBuilder()
    skip_kb.row(InlineKeyboardButton(text="⏭ Пропустить", callback_data="league_skip_city"))
    await message.answer(
        f"✅ Название: <b>{name}</b>\n\nВведи город (или пропусти):",
        reply_markup=skip_kb.as_markup()
    )


@router.callback_query(F.data == "league_skip_city")
async def create_league_skip_city(call: CallbackQuery, state: FSMContext, session: AsyncSession):
    await call.answer()
    await _finish_create_league(call.message, state, session, call.from_user.id, city=None)


@router.message(StateFilter(CreateLeagueFSM.waiting_city))
async def create_league_city(message: Message, state: FSMContext, session: AsyncSession):
    if not settings.is_admin(message.from_user.id):
        return
    city = message.text.strip() or None
    await _finish_create_league(message, state, session, message.from_user.id, city=city)


async def _finish_create_league(msg, state: FSMContext, session: AsyncSession,
                                 admin_tg_id: int, city):
    data = await state.get_data()
    await state.clear()

    # Сгенерировать уникальный код
    code = _gen_invite_code()
    while True:
        existing = await session.execute(
            select(League).where(League.invite_code == code)
        )
        if not existing.scalar_one_or_none():
            break
        code = _gen_invite_code()

    league = League(
        name=data["name"],
        invite_code=code,
        admin_telegram_id=admin_tg_id,
        city=city,
    )
    session.add(league)
    await session.flush()

    # Привязать создателя к лиге
    p_res = await session.execute(
        select(Player).where(Player.telegram_id == admin_tg_id)
    )
    creator = p_res.scalar_one_or_none()
    if creator:
        creator.league_id = league.id

    await session.commit()

    bot_username = getattr(settings, "BOT_USERNAME", "football_manager_2026_bot")
    invite_link = f"https://t.me/{bot_username}?start=join_{league.invite_code}"

    from app.keyboards.main_menu import admin_menu_kb
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🔗 Поделиться ссылкой", url=invite_link))
    builder.row(InlineKeyboardButton(text="🔙 Меню", callback_data="admin_back"))

    await msg.answer(
        f"✅ <b>Лига создана!</b>\n\n"
        f"🏆 {league.name}\n"
        f"🔑 Инвайт-код: <code>{league.invite_code}</code>\n\n"
        f"🔗 Ссылка для приглашения:\n<code>{invite_link}</code>\n\n"
        "Поделись этой ссылкой с игроками — они попадут в твою лигу автоматически.",
        reply_markup=builder.as_markup()
    )

"""
Дополнительные хендлеры Admin:
  - Активные игры
  - Прошедшие игры
  - Финансовый итог
  - Моя лига
  - /create_league команда
"""
from urllib.parse import quote

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
    Player, PlayerStatus, Match, League, RatingRound, RatingVote,
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


class EditLeagueFSM(StatesGroup):
    waiting_name = State()
    waiting_city = State()


class RatingVoteFSM(StatesGroup):
    voting = State()


class AutoTeamsFSM(StatesGroup):
    waiting_num_teams = State()


def _invite_share_url(invite_link: str, league_name: str) -> str:
    """Telegram share URL — открывает выбор контактов/групп."""
    text = f"Присоединяйся к лиге «{league_name}»! Нажми ссылку чтобы вступить:"
    return f"https://t.me/share/url?url={quote(invite_link)}&text={quote(text)}"


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
            text="💸 Финансовый итог",
            callback_data=f"gd_finance:{game_day_id}"
        ))
    builder.row(InlineKeyboardButton(
        text="🗑 Удалить игру",
        callback_data=f"gd_delete:{game_day_id}"
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
    share_url = _invite_share_url(invite_link, league.name)

    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="📤 Поделиться ссылкой", url=share_url))
    builder.row(InlineKeyboardButton(text="✏️ Редактировать лигу", callback_data=f"edit_league:{league.id}"))
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back"))

    await call.message.edit_text(
        f"🌐 <b>Моя лига</b>\n\n"
        f"🏆 <b>{league.name}</b>\n"
        f"📍 {league.city or '—'}\n"
        f"🔑 Инвайт-код: <code>{league.invite_code}</code>\n"
        f"👥 Активных игроков: {len(players)}\n\n"
        f"🔗 Ссылка для приглашения:\n<code>{invite_link}</code>\n\n"
        "Нажми «Поделиться» — откроется выбор контактов и групп Telegram.",
        reply_markup=builder.as_markup()
    )


@router.callback_query(F.data == "cmd_create_league")
@router.message(Command("create_league"))
async def create_league_start(event, state: FSMContext):
    """Любой зарегистрированный пользователь может создать лигу."""
    is_cb = isinstance(event, CallbackQuery)
    if is_cb:
        await event.answer()
        send = event.message.edit_text
    else:
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
    share_url = _invite_share_url(invite_link, league.name)

    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="📤 Поделиться ссылкой", url=share_url))
    builder.row(InlineKeyboardButton(text="🔙 Меню", callback_data="admin_back"))

    await msg.answer(
        f"✅ <b>Лига создана!</b>\n\n"
        f"🏆 {league.name}\n"
        f"🔑 Инвайт-код: <code>{league.invite_code}</code>\n\n"
        f"🔗 Ссылка для приглашения:\n<code>{invite_link}</code>\n\n"
        "Нажми «Поделиться» — откроется выбор контактов и групп в Telegram.",
        reply_markup=builder.as_markup()
    )


# ══════════════════════════════════════════════════════
#  РЕДАКТИРОВАНИЕ ЛИГИ
# ══════════════════════════════════════════════════════

@router.callback_query(F.data.startswith("edit_league:"))
async def edit_league_menu(call: CallbackQuery, session: AsyncSession):
    await call.answer()
    league_id = int(call.data.split(":")[1])
    league = await session.get(League, league_id)
    if not league:
        await call.message.edit_text("❌ Лига не найдена.")
        return

    # Проверить, что это тот же пользователь или суперадмин
    if league.admin_telegram_id != call.from_user.id and not settings.is_admin(call.from_user.id):
        await call.answer("⛔ Нет доступа", show_alert=True)
        return

    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(
        text="✏️ Изменить название",
        callback_data=f"edit_league_name:{league_id}"
    ))
    builder.row(InlineKeyboardButton(
        text="📍 Изменить город/страну",
        callback_data=f"edit_league_city:{league_id}"
    ))
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="admin_league_info"))

    await call.message.edit_text(
        f"✏️ <b>Редактировать лигу</b>\n\n"
        f"🏆 Текущее название: <b>{league.name}</b>\n"
        f"📍 Город: <b>{league.city or '—'}</b>\n\n"
        "Что хочешь изменить?",
        reply_markup=builder.as_markup()
    )


@router.callback_query(F.data.startswith("edit_league_name:"))
async def edit_league_name_start(call: CallbackQuery, state: FSMContext, session: AsyncSession):
    await call.answer()
    league_id = int(call.data.split(":")[1])
    league = await session.get(League, league_id)
    if not league:
        return
    if league.admin_telegram_id != call.from_user.id and not settings.is_admin(call.from_user.id):
        await call.answer("⛔", show_alert=True)
        return

    await state.set_state(EditLeagueFSM.waiting_name)
    await state.update_data(edit_league_id=league_id)

    cancel_kb = InlineKeyboardBuilder()
    cancel_kb.row(InlineKeyboardButton(text="❌ Отмена", callback_data=f"edit_league:{league_id}"))
    await call.message.edit_text(
        f"✏️ Введи новое название лиги:\n\n<i>Сейчас: {league.name}</i>",
        reply_markup=cancel_kb.as_markup()
    )


@router.message(StateFilter(EditLeagueFSM.waiting_name))
async def edit_league_name_save(message: Message, state: FSMContext, session: AsyncSession):
    data = await state.get_data()
    league_id = data["edit_league_id"]
    name = message.text.strip()
    if not name:
        await message.answer("❌ Название не может быть пустым.")
        return

    league = await session.get(League, league_id)
    if league:
        league.name = name
        await session.commit()

    await state.clear()
    from app.keyboards.main_menu import admin_menu_kb
    await message.answer(
        f"✅ Название лиги изменено на <b>{name}</b>.",
        reply_markup=admin_menu_kb()
    )


@router.callback_query(F.data.startswith("edit_league_city:"))
async def edit_league_city_start(call: CallbackQuery, state: FSMContext, session: AsyncSession):
    await call.answer()
    league_id = int(call.data.split(":")[1])
    league = await session.get(League, league_id)
    if not league:
        return
    if league.admin_telegram_id != call.from_user.id and not settings.is_admin(call.from_user.id):
        await call.answer("⛔", show_alert=True)
        return

    await state.set_state(EditLeagueFSM.waiting_city)
    await state.update_data(edit_league_id=league_id)

    cancel_kb = InlineKeyboardBuilder()
    cancel_kb.row(InlineKeyboardButton(text="🗑 Убрать город", callback_data=f"edit_league_city_clear:{league_id}"))
    cancel_kb.row(InlineKeyboardButton(text="❌ Отмена", callback_data=f"edit_league:{league_id}"))
    await call.message.edit_text(
        f"📍 Введи город и страну:\n\n<i>Сейчас: {league.city or '—'}</i>\n\n"
        "<i>Например: Ташкент, Узбекистан</i>",
        reply_markup=cancel_kb.as_markup()
    )


@router.callback_query(F.data.startswith("edit_league_city_clear:"))
async def edit_league_city_clear(call: CallbackQuery, state: FSMContext, session: AsyncSession):
    await call.answer()
    league_id = int(call.data.split(":")[1])
    await state.clear()
    league = await session.get(League, league_id)
    if league:
        league.city = None
        await session.commit()
    from app.keyboards.main_menu import admin_menu_kb
    await call.message.edit_text("✅ Город удалён.", reply_markup=admin_menu_kb())


@router.message(StateFilter(EditLeagueFSM.waiting_city))
async def edit_league_city_save(message: Message, state: FSMContext, session: AsyncSession):
    data = await state.get_data()
    league_id = data["edit_league_id"]
    city = message.text.strip() or None

    league = await session.get(League, league_id)
    if league:
        league.city = city
        await session.commit()

    await state.clear()
    from app.keyboards.main_menu import admin_menu_kb
    await message.answer(
        f"✅ Город обновлён: <b>{city or '—'}</b>.",
        reply_markup=admin_menu_kb()
    )


# ══════════════════════════════════════════════════════
#  РЕЙТИНГ-ГОЛОСОВАНИЕ
# ══════════════════════════════════════════════════════

@router.callback_query(F.data == "admin_rating_round")
async def adm_rating_round_start(call: CallbackQuery, session: AsyncSession, bot: Bot):
    if not settings.is_admin(call.from_user.id):
        await call.answer("⛔", show_alert=True)
        return
    await call.answer()

    from app.keyboards.main_menu import admin_menu_kb
    from datetime import datetime

    # Получить лигу администратора
    p_res = await session.execute(
        select(Player).where(Player.telegram_id == call.from_user.id)
    )
    admin_player = p_res.scalar_one_or_none()
    league_id = admin_player.league_id if admin_player else None

    # Проверить — нет ли уже активного раунда
    active_res = await session.execute(
        select(RatingRound).where(RatingRound.status == "active")
    )
    existing = active_res.scalar_one_or_none()
    if existing:
        builder = InlineKeyboardBuilder()
        builder.row(InlineKeyboardButton(
            text="🔒 Закрыть раунд и применить",
            callback_data=f"rating_round_close:{existing.id}"
        ))
        builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back"))
        await call.message.edit_text(
            f"⭐ <b>Раунд голосования уже активен</b>\n\n"
            f"Начат: {existing.started_at.strftime('%d.%m.%Y %H:%M')}\n\n"
            "Дождись голосования от игроков или закрой раунд вручную:",
            reply_markup=builder.as_markup()
        )
        return

    # Создать новый раунд
    round_ = RatingRound(triggered_by=f"admin:{call.from_user.id}", status="active")
    session.add(round_)
    await session.flush()

    # Разослать всем активным игрокам лиги
    query = select(Player).where(Player.status == PlayerStatus.ACTIVE)
    if league_id:
        query = query.where(Player.league_id == league_id)
    players_res = await session.execute(query)
    players = players_res.scalars().all()

    await session.commit()

    vote_kb = InlineKeyboardBuilder()
    vote_kb.row(InlineKeyboardButton(
        text="⭐ Оценить игроков",
        callback_data=f"rv_start:{round_.id}"
    ))

    sent = 0
    for p in players:
        try:
            await bot.send_message(
                p.telegram_id,
                f"⭐ <b>Рейтинг-голосование!</b>\n\n"
                f"Оцени других игроков лиги от 1 до 10.\n"
                f"Твои оценки влияют на рейтинг участников.\n\n"
                "<i>Займёт 1-2 минуты</i>",
                reply_markup=vote_kb.as_markup()
            )
            sent += 1
        except Exception:
            pass

    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(
        text="🔒 Закрыть раунд и применить",
        callback_data=f"rating_round_close:{round_.id}"
    ))
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back"))

    await call.message.edit_text(
        f"⭐ <b>Раунд голосования начат!</b>\n\n"
        f"📨 Уведомлено: {sent} игроков\n\n"
        "Когда все проголосуют — нажми «Закрыть» для применения результатов.",
        reply_markup=builder.as_markup()
    )


@router.callback_query(F.data.startswith("rv_start:"))
async def rv_start_voting(call: CallbackQuery, state: FSMContext, session: AsyncSession):
    """Игрок начинает голосование."""
    await call.answer()
    round_id = int(call.data.split(":")[1])

    # Проверить, что раунд ещё активен
    round_ = await session.get(RatingRound, round_id)
    if not round_ or round_.status != "active":
        await call.message.edit_text("❌ Раунд голосования завершён.")
        return

    # Получить список других игроков в лиге
    p_res = await session.execute(
        select(Player).where(Player.telegram_id == call.from_user.id)
    )
    voter = p_res.scalar_one_or_none()
    if not voter:
        await call.answer("❌ Ты не зарегистрирован.", show_alert=True)
        return

    # Если раунд привязан к игровому дню — оцениваем только участников этой игры
    if round_.game_day_id:
        att_res = await session.execute(
            select(Attendance)
            .options(selectinload(Attendance.player))
            .where(
                Attendance.game_day_id == round_.game_day_id,
                Attendance.response == AttendanceResponse.YES,
            )
        )
        nominees = [
            att.player for att in att_res.scalars().all()
            if att.player and att.player.id != voter.id
        ]
        nominees.sort(key=lambda p: p.name)
    else:
        nominees_query = select(Player).where(
            Player.status == PlayerStatus.ACTIVE,
            Player.id != voter.id,
        )
        if voter.league_id:
            nominees_query = nominees_query.where(Player.league_id == voter.league_id)
        nominees_res = await session.execute(nominees_query.order_by(Player.name))
        nominees = nominees_res.scalars().all()

    if not nominees:
        await call.message.edit_text("Нет других игроков для оценки.")
        return

    # Сохранить список в FSM
    await state.set_state(RatingVoteFSM.voting)
    await state.update_data(
        round_id=round_id,
        nominees=[{"id": p.id, "name": p.name} for p in nominees],
        current_idx=0,
        scores={},
    )

    # Показать первого
    await _show_vote_nominee(call.message, await state.get_data(), edit=True)


async def _show_vote_nominee(msg, data: dict, edit: bool = False):
    nominees = data["nominees"]
    idx = data["current_idx"]
    total = len(nominees)
    nominee = nominees[idx]
    scores = data.get("scores", {})

    builder = InlineKeyboardBuilder()
    current_score = scores.get(str(nominee["id"]))
    for n in range(1, 11):
        mark = " ✅" if current_score == n else ""
        builder.button(
            text=f"{n}{mark}",
            callback_data=f"rv_score:{data['round_id']}:{nominee['id']}:{n}"
        )
    builder.adjust(5)

    # Навигация
    nav_row = []
    if idx > 0:
        nav_row.append(InlineKeyboardButton(text="◀️ Назад", callback_data="rv_prev"))
    if idx < total - 1:
        nav_row.append(InlineKeyboardButton(text="▶️ Далее", callback_data="rv_next"))
    if nav_row:
        builder.row(*nav_row)

    already_scored = str(nominee["id"]) in scores
    if idx == total - 1 and already_scored:
        builder.row(InlineKeyboardButton(text="✅ Отправить голоса", callback_data="rv_submit"))
    elif all(str(n["id"]) in scores for n in nominees):
        builder.row(InlineKeyboardButton(text="✅ Отправить голоса", callback_data="rv_submit"))

    current_display = str(scores[str(nominee["id"])]) if str(nominee["id"]) in scores else "<i>не выбрана</i>"
    text = (
        f"⭐ <b>Голосование</b> — {idx + 1}/{total}\n\n"
        f"👤 <b>{nominee['name']}</b>\n\n"
        f"Твоя оценка: <b>{current_display}</b>\n\n"
        f"<i>Оцени от 1 (слабо) до 10 (отлично)</i>"
    )

    if edit:
        await msg.edit_text(text, reply_markup=builder.as_markup())
    else:
        await msg.answer(text, reply_markup=builder.as_markup())


@router.callback_query(F.data.startswith("rv_score:"), StateFilter(RatingVoteFSM.voting))
async def rv_record_score(call: CallbackQuery, state: FSMContext):
    await call.answer()
    parts = call.data.split(":")
    round_id, nominee_id, score = int(parts[1]), str(parts[2]), int(parts[3])

    data = await state.get_data()
    scores = dict(data.get("scores", {}))
    scores[nominee_id] = score
    await state.update_data(scores=scores)

    # Автоматически перейти к следующему
    nominees = data["nominees"]
    idx = data["current_idx"]
    if idx < len(nominees) - 1:
        await state.update_data(current_idx=idx + 1)

    await _show_vote_nominee(call.message, {**data, "scores": scores,
                                            "current_idx": min(idx + 1, len(nominees) - 1)}, edit=True)


@router.callback_query(F.data == "rv_prev", StateFilter(RatingVoteFSM.voting))
async def rv_prev(call: CallbackQuery, state: FSMContext):
    await call.answer()
    data = await state.get_data()
    idx = max(0, data["current_idx"] - 1)
    await state.update_data(current_idx=idx)
    await _show_vote_nominee(call.message, {**data, "current_idx": idx}, edit=True)


@router.callback_query(F.data == "rv_next", StateFilter(RatingVoteFSM.voting))
async def rv_next(call: CallbackQuery, state: FSMContext):
    await call.answer()
    data = await state.get_data()
    nominees = data["nominees"]
    idx = min(len(nominees) - 1, data["current_idx"] + 1)
    await state.update_data(current_idx=idx)
    await _show_vote_nominee(call.message, {**data, "current_idx": idx}, edit=True)


@router.callback_query(F.data == "rv_submit", StateFilter(RatingVoteFSM.voting))
async def rv_submit(call: CallbackQuery, state: FSMContext, session: AsyncSession):
    await call.answer()
    data = await state.get_data()
    await state.clear()

    round_id = data["round_id"]
    scores = data.get("scores", {})

    # Получить voter_id
    p_res = await session.execute(
        select(Player).where(Player.telegram_id == call.from_user.id)
    )
    voter = p_res.scalar_one_or_none()
    if not voter:
        return

    # Сохранить/обновить голоса (upsert через delete + insert)
    from sqlalchemy import delete as sql_delete
    await session.execute(
        sql_delete(RatingVote).where(
            RatingVote.round_id == round_id,
            RatingVote.voter_id == voter.id,
        )
    )

    for nominee_id_str, score in scores.items():
        session.add(RatingVote(
            round_id=round_id,
            voter_id=voter.id,
            nominee_id=int(nominee_id_str),
            score=score,
        ))

    await session.commit()

    total_voted = len(scores)
    await call.message.edit_text(
        f"✅ <b>Голоса отправлены!</b>\n\n"
        f"Ты оценил {total_voted} игроков.\n"
        "Спасибо! Результаты будут применены после завершения раунда. 🙏"
    )


@router.callback_query(F.data.startswith("rating_round_close:"))
async def rating_round_close(call: CallbackQuery, session: AsyncSession):
    if not settings.is_admin(call.from_user.id):
        await call.answer("⛔", show_alert=True)
        return
    await call.answer()

    from datetime import datetime
    from sqlalchemy import func as sqlfunc
    from app.keyboards.main_menu import admin_menu_kb

    round_id = int(call.data.split(":")[1])
    round_ = await session.get(RatingRound, round_id,
                               options=[selectinload(RatingRound.votes)])
    if not round_:
        return

    # Подсчитать средний рейтинг по каждому игроку
    # Группировка вручную: nominee_id → list of scores
    votes_map: dict[int, list[int]] = {}
    for v in round_.votes:
        votes_map.setdefault(v.nominee_id, []).append(v.score)

    updated = 0
    for nominee_id, vote_scores in votes_map.items():
        player = await session.get(Player, nominee_id)
        if not player:
            continue
        avg_vote = sum(vote_scores) / len(vote_scores)  # 1-10 scale
        new_component = avg_vote
        # Смешать: 60% старый рейтинг + 40% новый из голосования
        player.rating = round(player.rating * 0.6 + new_component * 0.4, 1)
        player.rating_provisional = False
        updated += 1

    round_.status = "finished"
    round_.finished_at = datetime.now()
    await session.commit()

    await call.message.edit_text(
        f"✅ <b>Раунд голосования завершён!</b>\n\n"
        f"📊 Обновлено рейтингов: <b>{updated}</b>\n"
        f"📨 Голосов получено: <b>{len(round_.votes)}</b>\n\n"
        "Новые рейтинги применены к игрокам.",
        reply_markup=admin_menu_kb()
    )


# ══════════════════════════════════════════════════════
#  ОПРОС РЕЙТИНГОВ ДЛЯ ИГРОВОГО ДНЯ
# ══════════════════════════════════════════════════════

@router.callback_query(F.data.startswith("gd_rating_poll:"))
async def gd_rating_poll_start(call: CallbackQuery, session: AsyncSession, bot: Bot):
    if not settings.is_admin(call.from_user.id):
        await call.answer("⛔", show_alert=True)
        return
    await call.answer()

    from datetime import datetime

    game_day_id = int(call.data.split(":")[1])
    game_day = await session.get(GameDay, game_day_id)
    if not game_day:
        return

    # Проверить — нет ли уже активного раунда для этого игрового дня
    existing_res = await session.execute(
        select(RatingRound).where(
            RatingRound.game_day_id == game_day_id,
            RatingRound.status == "active",
        )
    )
    existing = existing_res.scalar_one_or_none()
    if existing:
        builder = InlineKeyboardBuilder()
        builder.row(InlineKeyboardButton(
            text="🔒 Завершить и применить рейтинги",
            callback_data=f"gd_rating_close:{existing.id}:{game_day_id}"
        ))
        builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data=f"gd_players:{game_day_id}"))
        await call.message.edit_text(
            f"📊 <b>Опрос рейтингов уже активен</b>\n\n"
            f"Игровой день: <b>{game_day.display_name}</b>\n"
            f"Начат: {existing.started_at.strftime('%d.%m.%Y %H:%M')}\n\n"
            "Дождись ответов от игроков или завершите раунд вручную:",
            reply_markup=builder.as_markup()
        )
        return

    # Получить зарегистрированных игроков
    att_res = await session.execute(
        select(Attendance)
        .options(selectinload(Attendance.player))
        .where(
            Attendance.game_day_id == game_day_id,
            Attendance.response == AttendanceResponse.YES,
        )
    )
    attendances = att_res.scalars().all()
    players = [att.player for att in attendances if att.player]

    if len(players) < 2:
        await call.answer("❌ Нужно минимум 2 зарегистрированных игрока.", show_alert=True)
        return

    # Создать раунд привязанный к игровому дню
    round_ = RatingRound(
        triggered_by=f"game_day:{game_day_id}",
        game_day_id=game_day_id,
        status="active",
    )
    session.add(round_)
    await session.flush()
    await session.commit()

    # Разослать каждому участнику приглашение
    vote_kb = InlineKeyboardBuilder()
    vote_kb.row(InlineKeyboardButton(
        text="⭐ Оценить игроков",
        callback_data=f"rv_start:{round_.id}"
    ))

    sent = 0
    for p in players:
        try:
            await bot.send_message(
                p.telegram_id,
                f"⭐ <b>Оцени игроков!</b>\n\n"
                f"Перед делением на команды ({game_day.display_name}) "
                f"оцени участников от 1 до 10.\n\n"
                f"Это займёт 1–2 минуты и поможет сделать команды сбалансированнее.",
                reply_markup=vote_kb.as_markup()
            )
            sent += 1
        except Exception:
            pass

    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(
        text="🔒 Завершить и применить рейтинги",
        callback_data=f"gd_rating_close:{round_.id}:{game_day_id}"
    ))
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data=f"gd_players:{game_day_id}"))

    await call.message.edit_text(
        f"📊 <b>Опрос запущен!</b>\n\n"
        f"Игровой день: <b>{game_day.display_name}</b>\n"
        f"📨 Уведомлено: <b>{sent}</b> из {len(players)} игроков\n\n"
        "Когда все проголосуют — нажми «Завершить» для применения рейтингов.",
        reply_markup=builder.as_markup()
    )


@router.callback_query(F.data.startswith("gd_rating_close:"))
async def gd_rating_close(call: CallbackQuery, session: AsyncSession):
    if not settings.is_admin(call.from_user.id):
        await call.answer("⛔", show_alert=True)
        return
    await call.answer()

    from datetime import datetime

    parts = call.data.split(":")
    round_id = int(parts[1])
    game_day_id = int(parts[2])

    round_ = await session.get(RatingRound, round_id,
                               options=[selectinload(RatingRound.votes)])
    if not round_:
        return

    # Подсчитать средний рейтинг — шкала 1-10
    votes_map: dict[int, list[int]] = {}
    for v in round_.votes:
        votes_map.setdefault(v.nominee_id, []).append(v.score)

    updated = 0
    for nominee_id, vote_scores in votes_map.items():
        player = await session.get(Player, nominee_id)
        if not player:
            continue
        avg_vote = sum(vote_scores) / len(vote_scores)  # 1-10
        # Смешать: 60% старый рейтинг + 40% новый из голосования
        player.rating = round(player.rating * 0.6 + avg_vote * 0.4, 1)
        player.rating_provisional = False
        updated += 1

    round_.status = "finished"
    round_.finished_at = datetime.now()
    await session.commit()

    from app.keyboards.game_day import game_day_action_kb
    await call.message.edit_text(
        f"✅ <b>Опрос завершён!</b>\n\n"
        f"📊 Обновлено рейтингов: <b>{updated}</b>\n"
        f"📨 Голосов получено: <b>{len(round_.votes)}</b>\n\n"
        "Рейтинги обновлены. Теперь можно создать команды 🎲",
        reply_markup=game_day_action_kb(game_day_id)
    )


# ══════════════════════════════════════════════════════
#  АВТО-КОМАНДЫ (балансировка по рейтингу + позиции)
# ══════════════════════════════════════════════════════

TEAM_COLORS = ["🔴", "🔵", "🟡", "🟢", "🟠", "🟣", "⚪", "⚫"]
TEAM_NAMES  = ["A",   "B",   "C",   "D",   "E",   "F",   "G",   "H"]


@router.callback_query(F.data.startswith("gd_auto_teams:"))
async def auto_teams_start(call: CallbackQuery, session: AsyncSession):
    if not settings.is_admin(call.from_user.id):
        await call.answer("⛔", show_alert=True)
        return
    await call.answer()

    game_day_id = int(call.data.split(":")[1])

    # Проверяем, что есть зарегистрированные игроки
    result = await session.execute(
        select(Attendance)
        .options(selectinload(Attendance.player))
        .where(
            Attendance.game_day_id == game_day_id,
            Attendance.response == AttendanceResponse.YES
        )
    )
    attendances = result.scalars().all()

    if len(attendances) < 2:
        await call.answer("❌ Нужно минимум 2 игрока для создания команд.", show_alert=True)
        return

    from app.database.models import Team as TeamModel, TeamPlayer as TeamPlayerModel
    from sqlalchemy import delete as sql_delete

    # Если уже есть команды — предупредить и предложить пересоздать
    existing = await session.execute(
        select(TeamModel).where(TeamModel.game_day_id == game_day_id)
    )
    has_teams = existing.scalars().first() is not None

    builder = InlineKeyboardBuilder()
    for n in [2, 3, 4]:
        builder.button(
            text=f"{n} команды",
            callback_data=f"auto_teams_count:{game_day_id}:{n}"
        )
    builder.adjust(3)
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data=f"gd_players:{game_day_id}"))

    players_count = len(attendances)
    warn = ""
    if has_teams:
        warn = "\n\n⚠️ <b>Внимание:</b> старые команды будут удалены и пересозданы."

    await call.message.edit_text(
        f"🎲 <b>Создание команд</b>\n\n"
        f"Игроков: <b>{players_count}</b>\n"
        f"Выбери количество команд:{warn}",
        reply_markup=builder.as_markup()
    )


@router.callback_query(F.data.startswith("auto_teams_count:"))
async def auto_teams_execute(call: CallbackQuery, session: AsyncSession, bot: Bot):
    if not settings.is_admin(call.from_user.id):
        await call.answer("⛔", show_alert=True)
        return

    from app.database.models import (
        Team as TeamModel, TeamPlayer as TeamPlayerModel, Position
    )
    from app.database.models import POSITION_LABELS
    from sqlalchemy import delete as sql_delete
    from app.keyboards.game_day import game_day_action_kb

    parts = call.data.split(":")
    game_day_id = int(parts[1])
    num_teams = int(parts[2])

    # Загрузить зарегистрированных игроков
    result = await session.execute(
        select(Attendance)
        .options(selectinload(Attendance.player))
        .where(
            Attendance.game_day_id == game_day_id,
            Attendance.response == AttendanceResponse.YES
        )
    )
    attendances = result.scalars().all()
    players: list[Player] = [att.player for att in attendances if att.player is not None]

    if len(players) < num_teams:
        await call.answer(
            f"❌ Недостаточно игроков: {len(players)} записано, нужно минимум {num_teams}.",
            show_alert=True
        )
        return

    await call.answer("⏳ Создаю команды...")

    try:
        # Удалить старые команды (если были)
        old_teams_result = await session.execute(
            select(TeamModel).where(TeamModel.game_day_id == game_day_id)
        )
        old_teams = old_teams_result.scalars().all()
        for old_team in old_teams:
            await session.execute(
                sql_delete(TeamPlayerModel).where(TeamPlayerModel.team_id == old_team.id)
            )
            await session.delete(old_team)
        await session.flush()

        # ── Алгоритм балансировки ──────────────────────────────────────
        # 1. Разделить вратарей и полевых
        goalkeepers = sorted(
            [p for p in players if p.position == Position.GK],
            key=lambda p: p.rating, reverse=True
        )
        field_players = sorted(
            [p for p in players if p.position != Position.GK],
            key=lambda p: p.rating, reverse=True
        )

        # 2. Создать команды
        teams: list[TeamModel] = []
        for i in range(num_teams):
            team = TeamModel(
                game_day_id=game_day_id,
                name=TEAM_NAMES[i],
                color_emoji=TEAM_COLORS[i],
            )
            session.add(team)
            teams.append(team)
        await session.flush()

        # 3. Вратари — по одному на команду, лишние — в полевые
        team_players_buckets: list[list[Player]] = [[] for _ in range(num_teams)]
        gk_warnings: list[str] = []

        for i, gk in enumerate(goalkeepers):
            if i < num_teams:
                team_players_buckets[i].append(gk)
            else:
                field_players.append(gk)
                field_players.sort(key=lambda p: p.rating, reverse=True)

        if len(goalkeepers) < num_teams:
            missing = num_teams - len(goalkeepers)
            gk_warnings.append(f"⚠️ Не хватает {missing} вратар{'я' if missing == 1 else 'ей'}!")

        # 4. Snake draft полевых по рейтингу: 0,1,...,n-1,n-1,...,1,0,...
        direction = 1
        idx = 0
        for player in field_players:
            team_players_buckets[idx].append(player)
            next_idx = idx + direction
            if next_idx >= num_teams:
                direction = -1
                idx = num_teams - 1
            elif next_idx < 0:
                direction = 1
                idx = 0
            else:
                idx = next_idx

        # 5. Сохранить TeamPlayer записи
        for i, team in enumerate(teams):
            for player in team_players_buckets[i]:
                session.add(TeamPlayerModel(team_id=team.id, player_id=player.id))

        await session.commit()

        # ── Рассылка каждому игроку ────────────────────────────────────
        game_day = await session.get(GameDay, game_day_id)
        gd_name = game_day.display_name if game_day else f"#{game_day_id}"

        sent = 0
        for i, team in enumerate(teams):
            bucket = team_players_buckets[i]
            teammates = [p for p in bucket]

            for player in bucket:
                other_names = [p.name for p in teammates if p.id != player.id]
                if other_names:
                    teammates_text = ", ".join(other_names)
                else:
                    teammates_text = "пока никого нет"

                try:
                    await bot.send_message(
                        player.telegram_id,
                        f"⚽ <b>Команды на игру {gd_name} сформированы!</b>\n\n"
                        f"Мы провели рандомную разбивку на команды с балансировкой по рейтингу и позициям.\n\n"
                        f"Ты сегодня играешь в команде <b>{team.color_emoji} {team.name}</b>.\n\n"
                        f"С тобой в команде играют: <b>{teammates_text}</b>\n\n"
                        f"Удачи на игре! 🏆"
                    )
                    sent += 1
                except Exception:
                    pass

        # ── Сводка для Админа ─────────────────────────────────────────
        admin_lines = [f"🎲 <b>Команды сформированы!</b> ({gd_name})\n"]
        for i, team in enumerate(teams):
            bucket = team_players_buckets[i]
            avg_rating = sum(p.rating for p in bucket) / len(bucket) if bucket else 0
            admin_lines.append(f"\n{team.color_emoji} <b>Команда {team.name}</b> (⭐{avg_rating:.1f}):")
            for player in bucket:
                pos = POSITION_LABELS.get(player.position, player.position)
                admin_lines.append(f"  • {player.name} — {pos}")

        if gk_warnings:
            admin_lines.append("\n" + "\n".join(gk_warnings))
        admin_lines.append(f"\n\n📨 Уведомлено игроков: <b>{sent}/{len(players)}</b>")

        full_summary = "\n".join(admin_lines)

        # Разослать полный список судьям и другим админам
        referees_res = await session.execute(
            select(Player).where(
                Player.is_referee == True,
                Player.status == PlayerStatus.ACTIVE,
            )
        )
        referees = referees_res.scalars().all()
        notified_ids = {call.from_user.id}  # не дублировать тому кто нажал кнопку
        for ref in referees:
            if ref.telegram_id in notified_ids:
                continue
            try:
                await bot.send_message(ref.telegram_id, full_summary)
                notified_ids.add(ref.telegram_id)
            except Exception:
                pass
        # Остальные суперадмины из settings
        for admin_tg_id in settings.ADMIN_IDS:
            if admin_tg_id in notified_ids:
                continue
            try:
                await bot.send_message(admin_tg_id, full_summary)
                notified_ids.add(admin_tg_id)
            except Exception:
                pass

        await call.message.edit_text(
            full_summary,
            reply_markup=game_day_action_kb(game_day_id)
        )

    except Exception as e:
        await session.rollback()
        await call.message.edit_text(
            f"❌ <b>Ошибка при создании команд:</b>\n<code>{e}</code>",
            reply_markup=game_day_action_kb(game_day_id)
        )

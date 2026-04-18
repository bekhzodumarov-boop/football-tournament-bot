"""
Дополнительные хендлеры Admin:
  - Активные игры
  - Прошедшие игры
  - Финансовый итог
  - Моя лига
  - /create_league команда
"""
from urllib.parse import quote
import asyncio
import logging

logger = logging.getLogger(__name__)

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
    Player, PlayerStatus, Match, MatchStatus, Goal, GoalType, Card, League,
    RatingRound, RatingVote, Team, TeamPlayer, PlayerLeague, LeagueRole,
)
from app.database.models import _gen_invite_code
from app.locales.texts import t, goals_word as gw


async def _league_players(
    session,
    league_id: int | None,
    active_only: bool = True,
    exclude_player_id: int | None = None,
) -> list[Player]:
    """Игроки лиги через PlayerLeague (не player.league_id)."""
    if league_id is None:
        query = select(Player)
        if active_only:
            query = query.where(Player.status == PlayerStatus.ACTIVE)
        result = await session.execute(query)
        return result.scalars().all()

    query = (
        select(Player)
        .join(PlayerLeague, PlayerLeague.player_id == Player.id)
        .where(PlayerLeague.league_id == league_id)
    )
    if active_only:
        query = query.where(Player.status == PlayerStatus.ACTIVE)
    if exclude_player_id is not None:
        query = query.where(Player.id != exclude_player_id)
    result = await session.execute(query)
    return result.scalars().all()

router = Router()


class FinancialSummaryFSM(StatesGroup):
    waiting_expenses = State()
    waiting_players_count = State()
    waiting_confirm = State()
    waiting_card = State()


class CreateLeagueFSM(StatesGroup):
    waiting_name = State()
    waiting_city = State()
    waiting_player_limit = State()


class LeaguePasswordFSM(StatesGroup):
    waiting_password = State()


class EditLeagueFSM(StatesGroup):
    waiting_name = State()
    waiting_city = State()


class RatingVoteFSM(StatesGroup):
    voting = State()


class AutoTeamsFSM(StatesGroup):
    waiting_num_teams = State()


class RenameTeamsFSM(StatesGroup):
    waiting_new_name = State()


class AdminCardFSM(StatesGroup):
    waiting_card_number = State()


class PollFSM(StatesGroup):
    waiting_question = State()
    waiting_options = State()


class ScheduleFSM(StatesGroup):
    waiting_team1 = State()
    waiting_team2 = State()


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
            p = a.player
            if p.username:
                tg_ref = f' <a href="https://t.me/{p.username}">@{p.username}</a>'
            else:
                tg_ref = f' <a href="tg://user?id={p.telegram_id}">💬</a>'
            lines.append(f"  • {p.name}{tg_ref}")
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
async def gd_finance_confirm(call: CallbackQuery, state: FSMContext, session: AsyncSession):
    """После подтверждения суммы — спрашиваем номер карты."""
    await call.answer()

    data = await state.get_data()
    game_day_id = data["game_day_id"]

    # Ищем лигу игрового дня — может быть сохранённый номер карты
    game_day = await session.get(GameDay, game_day_id)
    league = await session.get(League, game_day.league_id) if game_day and game_day.league_id else None
    saved_card = league.card_number if league else None

    await state.set_state(FinancialSummaryFSM.waiting_card)

    kb = InlineKeyboardBuilder()
    if saved_card:
        kb.row(InlineKeyboardButton(
            text=f"✅ Использовать {saved_card}",
            callback_data=f"fin_use_card:{saved_card}"
        ))
        kb.row(InlineKeyboardButton(
            text="📲 Другая карта",
            callback_data="fin_new_card"
        ))
    else:
        kb.row(InlineKeyboardButton(text="❌ Отмена", callback_data="admin_back"))

    if saved_card:
        prompt = (
            f"💳 <b>Номер карты для оплаты</b>\n\n"
            f"Сохранённая карта: <code>{saved_card}</code>\n\n"
            "Использовать эту карту или ввести другую?"
        )
    else:
        prompt = (
            "💳 <b>Введите номер карты</b>\n\n"
            "На какую карту игроки должны переводить взнос?\n"
            "<i>Например: 8600 1234 5678 9012</i>"
        )

    await call.message.edit_text(prompt, reply_markup=kb.as_markup())


@router.callback_query(F.data.startswith("fin_use_card:"))
async def fin_use_saved_card(call: CallbackQuery, state: FSMContext,
                              session: AsyncSession, bot: Bot):
    """Использовать ранее сохранённую карту."""
    await call.answer()
    card_number = call.data.split(":", 1)[1]
    await _broadcast_finance(call.message, state, session, bot, card_number)


@router.callback_query(F.data == "fin_new_card")
async def fin_new_card_prompt(call: CallbackQuery, state: FSMContext):
    """Запросить новый номер карты."""
    await call.answer()
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="❌ Отмена", callback_data="admin_back"))
    await call.message.edit_text(
        "📲 <b>Введите новый номер карты:</b>\n<i>Например: 8600 1234 5678 9012</i>",
        reply_markup=kb.as_markup()
    )


@router.message(StateFilter(FinancialSummaryFSM.waiting_card))
async def fin_card_entered(message: Message, state: FSMContext,
                           session: AsyncSession, bot: Bot):
    """Администратор ввёл номер карты вручную."""
    if not settings.is_admin(message.from_user.id):
        return
    card_number = message.text.strip()
    if len(card_number) < 4:
        await message.answer("❌ Похоже, это не номер карты. Введи ещё раз:")
        return
    await _broadcast_finance(message, state, session, bot, card_number)


async def _broadcast_finance(msg, state: FSMContext, session: AsyncSession,
                              bot: Bot, card_number: str):
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

    # Сохраняем номер карты в лигу
    if game_day.league_id:
        league = await session.get(League, game_day.league_id)
        if league:
            league.card_number = card_number
            await session.commit()

    attendees = [a for a in game_day.attendances if a.response == AttendanceResponse.YES]

    sent = 0
    for att in attendees:
        p = att.player
        if not p:
            continue
        try:
            lang = getattr(p, 'language', None) or 'ru'
            base_text = t('finance_notice', lang,
                          game_name=game_day.display_name,
                          date=game_day.scheduled_at.strftime('%d.%m.%Y'),
                          location=game_day.location,
                          amount=f"{cost_per:,}")
            card_line = f"\n\n💳 <b>Номер карты для оплаты:</b>\n<code>{card_number}</code>"
            await bot.send_message(p.telegram_id, base_text + card_line)
            sent += 1
            await asyncio.sleep(0.05)
        except Exception as e:
            logger.warning(f"Cannot send finance notice to {p.telegram_id}: {e}")

    from app.keyboards.main_menu import admin_menu_kb
    await msg.answer(
        f"✅ <b>Финансовый итог отправлен!</b>\n\n"
        f"💰 Взнос: {cost_per:,} сум.\n"
        f"💳 Карта: <code>{card_number}</code>\n"
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

    players = await _league_players(session, league.id, active_only=True)

    # Получить username бота из settings если есть, иначе дефолт
    bot_username = getattr(cfg, "BOT_USERNAME", "football_manager_uz_bot")
    invite_link = f"https://t.me/{bot_username}?start=join_{league.invite_code}"
    share_url = _invite_share_url(invite_link, league.name)

    password_label = "🔑 Пароль: установлен 🔒" if league.password else "🔑 Установить пароль лиги"

    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="📤 Поделиться ссылкой", url=share_url))
    builder.row(InlineKeyboardButton(text="✏️ Редактировать лигу", callback_data=f"edit_league:{league.id}"))
    builder.row(InlineKeyboardButton(text=password_label, callback_data=f"league_password:{league.id}"))
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back"))

    await call.message.edit_text(
        f"🌐 <b>Моя лига</b>\n\n"
        f"🏆 <b>{league.name}</b>\n"
        f"📍 {league.city or '—'}\n"
        f"🔑 Инвайт-код: <code>{league.invite_code}</code>\n"
        f"👥 Активных игроков: {len(players)}\n"
        f"🔒 Пароль: {'установлен' if league.password else 'не установлен (открытая лига)'}\n\n"
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
async def create_league_skip_city(call: CallbackQuery, state: FSMContext):
    await call.answer()
    await state.update_data(city=None)
    await _ask_player_limit(call.message, state)


@router.message(StateFilter(CreateLeagueFSM.waiting_city))
async def create_league_city(message: Message, state: FSMContext):
    city = message.text.strip() or None
    await state.update_data(city=city)
    await _ask_player_limit(message, state)


async def _ask_player_limit(msg, state: FSMContext):
    await state.set_state(CreateLeagueFSM.waiting_player_limit)
    skip_kb = InlineKeyboardBuilder()
    skip_kb.row(InlineKeyboardButton(text="⏭ Пропустить (20 игроков)", callback_data="league_skip_limit"))
    await msg.answer(
        "👥 Сколько игроков в одном турнире? <i>(например: 16, 20, 24)</i>",
        reply_markup=skip_kb.as_markup()
    )


@router.callback_query(F.data == "league_skip_limit")
async def create_league_skip_limit(call: CallbackQuery, state: FSMContext, session: AsyncSession):
    await call.answer()
    await _finish_create_league(call.message, state, session, call.from_user.id, player_limit=20)


@router.message(StateFilter(CreateLeagueFSM.waiting_player_limit))
async def create_league_player_limit(message: Message, state: FSMContext, session: AsyncSession):
    try:
        limit = int(message.text.strip())
        if limit < 4 or limit > 100:
            raise ValueError
    except ValueError:
        await message.answer("❌ Введи число от 4 до 100:")
        return
    await _finish_create_league(message, state, session, message.from_user.id, player_limit=limit)


async def _finish_create_league(msg, state: FSMContext, session: AsyncSession,
                                 admin_tg_id: int, player_limit: int = 20):
    from app.config import register_league_admin
    data = await state.get_data()
    city = data.get("city")
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
        default_player_limit=player_limit,
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
        # Создать PlayerLeague с ролью ADMIN
        existing_pl = await session.execute(
            select(PlayerLeague).where(
                PlayerLeague.player_id == creator.id,
                PlayerLeague.league_id == league.id,
            )
        )
        if existing_pl.scalar_one_or_none() is None:
            session.add(PlayerLeague(
                player_id=creator.id,
                league_id=league.id,
                role=LeagueRole.ADMIN,
            ))

    await session.commit()

    # Зарегистрировать создателя как лига-админ в рантайм-кэше
    register_league_admin(admin_tg_id)

    bot_username = getattr(settings, "BOT_USERNAME", "football_manager_uz_bot")
    invite_link = f"https://t.me/{bot_username}?start=join_{league.invite_code}"
    share_url = _invite_share_url(invite_link, league.name)

    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="📤 Поделиться ссылкой", url=share_url))
    builder.row(InlineKeyboardButton(text="🔧 Панель администратора", callback_data="admin_back"))

    await msg.answer(
        f"✅ <b>Лига создана!</b>\n\n"
        f"🏆 {league.name}\n"
        f"📍 {city or '—'}\n"
        f"👥 Лимит игроков: {player_limit}\n"
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
        # Считаем прогресс: сколько уникальных voters уже проголосовало
        from sqlalchemy import func as sqlfunc
        voted_res = await session.execute(
            select(sqlfunc.count(sqlfunc.distinct(RatingVote.voter_id)))
            .where(RatingVote.round_id == existing.id)
        )
        voted_count = voted_res.scalar() or 0

        # Сколько было приглашено (через PlayerLeague)
        if league_id:
            total_count = len(await _league_players(session, league_id, active_only=True)) - 1
        else:
            total_res = await session.execute(
                select(sqlfunc.count(Player.id)).where(Player.status == PlayerStatus.ACTIVE)
            )
            total_count = (total_res.scalar() or 1) - 1

        builder = InlineKeyboardBuilder()
        builder.row(InlineKeyboardButton(
            text="🔄 Обновить прогресс",
            callback_data="admin_rating_round"
        ))
        builder.row(InlineKeyboardButton(
            text="🔒 Закрыть раунд и применить",
            callback_data=f"rating_round_close:{existing.id}"
        ))
        builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back"))
        await call.message.edit_text(
            f"⭐ <b>Раунд голосования активен</b>\n\n"
            f"Начат: {existing.started_at.strftime('%d.%m.%Y %H:%M')}\n\n"
            f"📊 Проголосовали: <b>{voted_count}</b> из ~{total_count} игроков\n\n"
            "Дождись голосования от игроков или закрой раунд вручную:",
            reply_markup=builder.as_markup()
        )
        return

    # Создать новый раунд
    round_ = RatingRound(triggered_by=f"admin:{call.from_user.id}", status="active")
    session.add(round_)
    await session.flush()

    # Разослать всем активным игрокам лиги
    players = await _league_players(session, league_id, active_only=True)

    await session.commit()

    vote_kb = InlineKeyboardBuilder()
    vote_kb.row(InlineKeyboardButton(
        text="⭐ Оценить игроков",
        callback_data=f"rv_start:{round_.id}"
    ))

    sent = 0
    for p in players:
        try:
            lang = getattr(p, 'language', None) or 'ru'
            await bot.send_message(
                p.telegram_id,
                t('rating_invite', lang),
                reply_markup=vote_kb.as_markup()
            )
            sent += 1
            await asyncio.sleep(0.05)
        except Exception as e:
            logger.warning(f"Cannot send rating invite to {p.telegram_id}: {e}")

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
        nominees_query_result = await _league_players(
            session, voter.league_id, active_only=True, exclude_player_id=voter.id
        )
        nominees = sorted(nominees_query_result, key=lambda p: p.name)

    if not nominees:
        await call.message.edit_text("Нет других игроков для оценки.")
        return

    voter_lang = getattr(voter, 'language', None) or 'ru'

    # Сохранить список в FSM
    await state.set_state(RatingVoteFSM.voting)
    await state.update_data(
        round_id=round_id,
        nominees=[{"id": p.id, "name": p.name} for p in nominees],
        current_idx=0,
        scores={},
        voter_lang=voter_lang,
    )

    # Показать первого
    await _show_vote_nominee(call.message, await state.get_data(), edit=True)


async def _show_vote_nominee(msg, data: dict, edit: bool = False):
    nominees = data["nominees"]
    idx = data["current_idx"]
    total = len(nominees)
    nominee = nominees[idx]
    scores = data.get("scores", {})
    lang = data.get("voter_lang", "ru")

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
        nav_row.append(InlineKeyboardButton(text=t('btn_vote_prev', lang), callback_data="rv_prev"))
    if idx < total - 1:
        nav_row.append(InlineKeyboardButton(text=t('btn_vote_next', lang), callback_data="rv_next"))
    if nav_row:
        builder.row(*nav_row)

    already_scored = str(nominee["id"]) in scores
    if idx == total - 1 and already_scored:
        builder.row(InlineKeyboardButton(text=t('btn_vote_submit', lang), callback_data="rv_submit"))
    elif all(str(n["id"]) in scores for n in nominees):
        builder.row(InlineKeyboardButton(text=t('btn_vote_submit', lang), callback_data="rv_submit"))

    current_display = str(scores[str(nominee["id"])]) if str(nominee["id"]) in scores else t('score_not_set', lang)
    text = t('rating_vote_nominee', lang,
             current=idx + 1,
             total=total,
             name=nominee['name'],
             score=current_display)

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

    lang = data.get("voter_lang", "ru")
    total_voted = len(scores)
    await call.message.edit_text(
        t('rating_voted', lang, count=total_voted)
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
        # Прогресс: сколько уже проголосовало
        from sqlalchemy import func as sqlfunc
        voted_res = await session.execute(
            select(sqlfunc.count(sqlfunc.distinct(RatingVote.voter_id)))
            .where(RatingVote.round_id == existing.id)
        )
        voted_count = voted_res.scalar() or 0

        # Сколько участников игрового дня
        att_count_res = await session.execute(
            select(sqlfunc.count(Attendance.id)).where(
                Attendance.game_day_id == game_day_id,
                Attendance.response == AttendanceResponse.YES,
            )
        )
        total_count = (att_count_res.scalar() or 1) - 1  # минус сам голосующий

        builder = InlineKeyboardBuilder()
        builder.row(InlineKeyboardButton(
            text="🔄 Обновить прогресс",
            callback_data=f"gd_rating_poll:{game_day_id}"
        ))
        builder.row(InlineKeyboardButton(
            text="🔒 Завершить и применить рейтинги",
            callback_data=f"gd_rating_close:{existing.id}:{game_day_id}"
        ))
        builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data=f"gd_players:{game_day_id}"))
        await call.message.edit_text(
            f"📊 <b>Опрос рейтингов активен</b>\n\n"
            f"Игровой день: <b>{game_day.display_name}</b>\n"
            f"Начат: {existing.started_at.strftime('%d.%m.%Y %H:%M')}\n\n"
            f"📊 Проголосовали: <b>{voted_count}</b> из ~{total_count} игроков\n\n"
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
            lang = getattr(p, 'language', None) or 'ru'
            await bot.send_message(
                p.telegram_id,
                t('rating_invite_gameday', lang, game_name=game_day.display_name),
                reply_markup=vote_kb.as_markup()
            )
            sent += 1
            await asyncio.sleep(0.05)
        except Exception as e:
            logger.warning(f"Cannot send game day rating invite to {p.telegram_id}: {e}")

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

TEAM_COLORS = ["🔴", "🟡", "🔵", "🟢", "🟠", "🟣", "⚪", "⚫"]
TEAM_NAMES  = ["Red", "Golden", "Blue", "Green", "E", "F", "G", "H"]


@router.callback_query(F.data.startswith("gd_auto_teams:"))
async def auto_teams_start(call: CallbackQuery, session: AsyncSession):
    if not settings.is_admin(call.from_user.id):
        await call.answer("⛔", show_alert=True)
        return
    await call.answer()

    game_day_id = int(call.data.split(":")[1])

    from app.database.models import Team as TeamModel, TeamPlayer as TeamPlayerModel
    from app.database.models import POSITION_LABELS
    from app.keyboards.game_day import game_day_action_kb

    # Если команды уже созданы и в них есть игроки — показываем состав
    from app.database.models import TeamPlayer as TeamPlayerModel2
    from sqlalchemy import delete as sql_delete_teams
    existing_res = await session.execute(
        select(TeamModel).where(TeamModel.game_day_id == game_day_id)
    )
    existing_teams = existing_res.scalars().all()

    # Проверяем что в командах реально есть игроки
    teams_have_players = False
    if existing_teams:
        from app.database.models import TeamPlayer as TPCheck
        tp_check = await session.execute(
            select(TPCheck).where(
                TPCheck.team_id.in_([t.id for t in existing_teams])
            ).limit(1)
        )
        teams_have_players = tp_check.scalar_one_or_none() is not None

    # Пустые команды (без игроков) — удаляем и даём создать заново
    if existing_teams and not teams_have_players:
        from sqlalchemy import delete as _del
        old_ids = [t.id for t in existing_teams]
        # Каскад: голы → карточки → матчи → составы → команды
        matches_res = await session.execute(
            select(Match).where(
                (Match.team_home_id.in_(old_ids)) | (Match.team_away_id.in_(old_ids))
            )
        )
        old_match_ids = [m.id for m in matches_res.scalars().all()]
        if old_match_ids:
            await session.execute(_del(Goal).where(Goal.match_id.in_(old_match_ids)))
            await session.execute(_del(Card).where(Card.match_id.in_(old_match_ids)))
            await session.execute(_del(Match).where(Match.id.in_(old_match_ids)))
        await session.execute(_del(TeamModel).where(TeamModel.id.in_(old_ids)))
        await session.commit()
        existing_teams = []

    if existing_teams:
        # Загружаем игроков отдельным запросом для надёжности
        from app.database.models import TeamPlayer as TPModel
        game_day = await session.get(GameDay, game_day_id)
        gd_name = game_day.display_name if game_day else f"#{game_day_id}"

        lines = [f"⚽ <b>Состав команд ({gd_name})</b>\n"]

        for team in existing_teams:
            tp_res = await session.execute(
                select(TPModel)
                .options(selectinload(TPModel.player))
                .where(TPModel.team_id == team.id)
            )
            tps = tp_res.scalars().all()
            lines.append(f"\n{team.color_emoji} <b>Команда {team.name}</b>:")
            if tps:
                for tp in tps:
                    if tp.player:
                        pos = POSITION_LABELS.get(tp.player.position, tp.player.position)
                        p = tp.player
                        if p.username:
                            tg_ref = f' <a href="https://t.me/{p.username}">@{p.username}</a>'
                        else:
                            tg_ref = f' <a href="tg://user?id={p.telegram_id}">💬</a>'
                        lines.append(f"  • {p.name}{tg_ref} — {pos}")
            else:
                lines.append("  <i>нет игроков</i>")

        # Кнопка пересоздания + назад
        kb = InlineKeyboardBuilder()
        kb.row(InlineKeyboardButton(
            text="🔄 Пересоздать команды",
            callback_data=f"auto_teams_reset:{game_day_id}"
        ))
        kb.row(InlineKeyboardButton(text="🔙 Назад", callback_data=f"gd_players:{game_day_id}"))

        await call.message.edit_text(
            "\n".join(lines),
            reply_markup=kb.as_markup()
        )
        return

    # Команд ещё нет — предлагаем выбрать количество
    result = await session.execute(
        select(Attendance)
        .where(
            Attendance.game_day_id == game_day_id,
            Attendance.response == AttendanceResponse.YES
        )
    )
    player_count = len(result.scalars().all())

    if player_count < 2:
        await call.answer("❌ Нужно минимум 2 игрока для создания команд.", show_alert=True)
        return

    builder = InlineKeyboardBuilder()
    for n in [2, 3, 4]:
        builder.button(text=f"{n} команды", callback_data=f"auto_teams_count:{game_day_id}:{n}")
    builder.adjust(3)
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data=f"gd_players:{game_day_id}"))

    await call.message.edit_text(
        f"⚽ <b>Создание команд</b>\n\n"
        f"Зарегистрировано: <b>{player_count}</b> игроков\n\n"
        f"Сколько команд создать?",
        reply_markup=builder.as_markup()
    )


@router.callback_query(F.data.startswith("auto_teams_reset:"))
async def auto_teams_reset(call: CallbackQuery, session: AsyncSession):
    """Удалить существующие команды и начать заново."""
    if not settings.is_admin(call.from_user.id):
        await call.answer("⛔", show_alert=True)
        return
    await call.answer()

    from app.database.models import Team as TeamModel, TeamPlayer as TeamPlayerModel
    from sqlalchemy import delete as _del

    game_day_id = int(call.data.split(":")[1])

    old_res = await session.execute(
        select(TeamModel).where(TeamModel.game_day_id == game_day_id)
    )
    old_teams = old_res.scalars().all()
    if old_teams:
        old_ids = [t.id for t in old_teams]
        matches_res = await session.execute(
            select(Match).where(
                (Match.team_home_id.in_(old_ids)) | (Match.team_away_id.in_(old_ids))
            )
        )
        mid = [m.id for m in matches_res.scalars().all()]
        if mid:
            await session.execute(_del(Goal).where(Goal.match_id.in_(mid)))
            await session.execute(_del(Card).where(Card.match_id.in_(mid)))
            await session.execute(_del(Match).where(Match.id.in_(mid)))
        await session.execute(_del(TeamPlayerModel).where(TeamPlayerModel.team_id.in_(old_ids)))
        await session.execute(_del(TeamModel).where(TeamModel.id.in_(old_ids)))
        await session.commit()

    # Перейти к выбору количества команд
    result = await session.execute(
        select(Attendance).where(
            Attendance.game_day_id == game_day_id,
            Attendance.response == AttendanceResponse.YES
        )
    )
    player_count = len(result.scalars().all())

    builder = InlineKeyboardBuilder()
    for n in [2, 3, 4]:
        builder.button(text=f"{n} команды", callback_data=f"auto_teams_count:{game_day_id}:{n}")
    builder.adjust(3)
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data=f"gd_players:{game_day_id}"))

    await call.message.edit_text(
        f"⚽ <b>Создание команд</b>\n\n"
        f"Зарегистрировано: <b>{player_count}</b> игроков\n\n"
        f"Сколько команд создать?",
        reply_markup=builder.as_markup()
    )


@router.callback_query(F.data.startswith("auto_teams_count:"))
async def auto_teams_ask_size(call: CallbackQuery, session: AsyncSession):
    """Шаг 2: спросить сколько человек в команде."""
    if not settings.is_admin(call.from_user.id):
        await call.answer("⛔", show_alert=True)
        return
    await call.answer()

    parts = call.data.split(":")
    game_day_id = int(parts[1])
    num_teams = int(parts[2])

    result = await session.execute(
        select(Attendance).where(
            Attendance.game_day_id == game_day_id,
            Attendance.response == AttendanceResponse.YES
        )
    )
    player_count = len(result.scalars().all())

    if player_count < num_teams:
        await call.answer(
            f"❌ Недостаточно игроков: {player_count} записано, нужно минимум {num_teams}.",
            show_alert=True
        )
        return

    # Предлагаем варианты размера команды
    natural = player_count // num_teams  # натуральное деление
    options = sorted({max(natural - 1, 1), natural, natural + 1})

    builder = InlineKeyboardBuilder()
    for size in options:
        total_used = size * num_teams
        if total_used > player_count:
            label = f"{size} чел. (не хватит игроков)"
        elif total_used < player_count:
            leftover = player_count - total_used
            label = f"{size} чел. ({leftover} в запасе)"
        else:
            label = f"{size} чел. (ровно)"
        builder.button(
            text=label,
            callback_data=f"auto_teams_size:{game_day_id}:{num_teams}:{size}"
        )
    builder.adjust(1)
    builder.row(InlineKeyboardButton(
        text="🔙 Назад",
        callback_data=f"gd_auto_teams:{game_day_id}"
    ))

    await call.message.edit_text(
        f"⚽ <b>Создание команд</b>\n\n"
        f"Игроков: <b>{player_count}</b> | Команд: <b>{num_teams}</b>\n\n"
        f"Сколько человек в каждой команде?",
        reply_markup=builder.as_markup()
    )


@router.callback_query(F.data.startswith("auto_teams_size:"))
async def auto_teams_execute(call: CallbackQuery, session: AsyncSession, bot: Bot):
    if not settings.is_admin(call.from_user.id):
        await call.answer("⛔", show_alert=True)
        return

    from app.database.models import (
        Team as TeamModel, TeamPlayer as TeamPlayerModel, Position
    )
    from app.database.models import POSITION_LABELS
    from app.keyboards.game_day import game_day_action_kb

    parts = call.data.split(":")
    game_day_id = int(parts[1])
    num_teams = int(parts[2])
    players_per_team = int(parts[3])

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

    total_spots = players_per_team * num_teams
    if len(players) < total_spots:
        await call.answer(
            f"❌ Нужно {total_spots} игроков, а записано {len(players)}.",
            show_alert=True
        )
        return

    # Если игроков больше чем мест — берём лучших по рейтингу
    if len(players) > total_spots:
        players = sorted(players, key=lambda p: p.rating, reverse=True)[:total_spots]

    await call.answer("⏳ Формирую команды...")

    # ── Алгоритм равного распределения ────────────────────────────────
    # 1. Сначала назначаем вратарей (макс 1 на команду)
    # 2. Остальных распределяем round-robin snake по рейтингу,
    #    соблюдая лимит players_per_team на команду

    gks = sorted([p for p in players if p.position == Position.GK],
                 key=lambda p: p.rating, reverse=True)
    rest = sorted([p for p in players if p.position != Position.GK],
                  key=lambda p: p.rating, reverse=True)

    team_players_buckets: list[list[Player]] = [[] for _ in range(num_teams)]
    gk_warnings: list[str] = []

    # Назначить вратарей: по одному на команду, лишние → в rest
    for i, gk in enumerate(gks):
        if i < num_teams:
            team_players_buckets[i].append(gk)
        else:
            rest.append(gk)
    rest.sort(key=lambda p: p.rating, reverse=True)

    if len(gks) < num_teams:
        missing = num_teams - len(gks)
        gk_warnings.append(
            f"⚠️ Вратарей {len(gks)} на {num_teams} команды — "
            f"{missing} {'команда' if missing == 1 else 'команды' if missing < 5 else 'команд'} без вратаря!"
        )

    # Round-robin snake по оставшимся слотам
    # Строим порядок выбора: тур 1: 0,1,2,...,n-1; тур 2: n-1,...,1,0; и т.д.
    pick_order = []
    for round_i in range(players_per_team):
        if round_i % 2 == 0:
            pick_order.extend(range(num_teams))
        else:
            pick_order.extend(range(num_teams - 1, -1, -1))

    rest_idx = 0
    for team_idx in pick_order:
        if rest_idx >= len(rest):
            break
        if len(team_players_buckets[team_idx]) < players_per_team:
            team_players_buckets[team_idx].append(rest[rest_idx])
            rest_idx += 1

    # Создать команды в БД
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

    # Сохранить TeamPlayer
    for i, team in enumerate(teams):
        for player in team_players_buckets[i]:
            session.add(TeamPlayerModel(team_id=team.id, player_id=player.id))

    # Снять все нужные данные ДО commit — после commit объекты становятся detached
    game_day = await session.get(GameDay, game_day_id)
    gd_name = game_day.display_name if game_day else f"#{game_day_id}"

    # Сериализуем команды в plain dict
    teams_data = []
    for i, team in enumerate(teams):
        bucket = team_players_buckets[i]
        avg_rating = sum(p.rating for p in bucket) / len(bucket) if bucket else 0.0
        members = [
            {
                "telegram_id": p.telegram_id,
                "name": p.name,
                "pos": POSITION_LABELS.get(p.position, p.position),
                "rating": p.rating,
                "language": getattr(p, 'language', None) or 'ru',
            }
            for p in bucket
        ]
        teams_data.append({
            "name": team.name,
            "color": team.color_emoji,
            "avg_rating": avg_rating,
            "members": members,
        })

    await session.commit()

    # ── Рассылка каждому игроку ────────────────────────────────────────
    sent = 0
    for team_info in teams_data:
        member_names = [m["name"] for m in team_info["members"]]
        for member in team_info["members"]:
            other_names = [n for n in member_names if n != member["name"]]
            lang = member.get('language', 'ru')
            teammates_text = ", ".join(other_names) if other_names else ("пока никого нет" if lang == 'ru' else "no one yet")
            try:
                await bot.send_message(
                    member["telegram_id"],
                    t('team_assigned', lang,
                      game_name=gd_name,
                      team_color=team_info['color'],
                      team_name=team_info['name'],
                      teammates=teammates_text)
                )
                sent += 1
                await asyncio.sleep(0.05)
            except Exception as e:
                logger.warning(f"Cannot send team assignment to {member['telegram_id']}: {e}")

    # ── Сводка для Админа ─────────────────────────────────────────────
    admin_lines = [f"⚽ <b>Команды сформированы!</b> ({gd_name})\n"]
    for team_info in teams_data:
        admin_lines.append(
            f"\n{team_info['color']} <b>Команда {team_info['name']}</b> "
            f"(⭐{team_info['avg_rating']:.1f}):"
        )
        for m in team_info["members"]:
            admin_lines.append(f"  • {m['name']} — {m['pos']}")
    if gk_warnings:
        admin_lines.append("\n" + "\n".join(gk_warnings))
    admin_lines.append(f"\n\n📨 Уведомлено: <b>{sent}/{len(players)}</b>")
    full_summary = "\n".join(admin_lines)

    # Разослать сводку судьям и другим админам
    referees_res = await session.execute(
        select(Player).where(
            Player.is_referee == True,
            Player.status == PlayerStatus.ACTIVE,
        )
    )
    referees = referees_res.scalars().all()
    notified_ids = {call.from_user.id}
    for ref in referees:
        if ref.telegram_id not in notified_ids:
            try:
                await bot.send_message(ref.telegram_id, full_summary)
                notified_ids.add(ref.telegram_id)
                await asyncio.sleep(0.05)
            except Exception as e:
                logger.warning(f"Cannot send team summary to referee {ref.telegram_id}: {e}")
    for admin_tg_id in settings.ADMIN_IDS:
        if admin_tg_id not in notified_ids:
            try:
                await bot.send_message(admin_tg_id, full_summary)
                notified_ids.add(admin_tg_id)
                await asyncio.sleep(0.05)
            except Exception as e:
                logger.warning(f"Cannot send team summary to admin {admin_tg_id}: {e}")

    # Показать сводку Админу (новым сообщением — надёжнее edit_text)
    await call.message.answer(full_summary, reply_markup=game_day_action_kb(game_day_id))


# ══════════════════════════════════════════════════════
#  ПЕРЕИМЕНОВАНИЕ КОМАНД
# ══════════════════════════════════════════════════════

def _teams_rename_kb(game_day_id: int, teams: list) -> object:
    """Клавиатура со списком команд для переименования."""
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    builder = InlineKeyboardBuilder()
    for team in teams:
        builder.row(InlineKeyboardButton(
            text=f"{team.color_emoji} {team.name}",
            callback_data=f"rename_team_pick:{game_day_id}:{team.id}"
        ))
    builder.row(InlineKeyboardButton(
        text="🔙 К игровому дню",
        callback_data=f"gd_players:{game_day_id}"
    ))
    return builder.as_markup()


@router.callback_query(F.data.startswith("gd_rename_teams:"))
async def gd_rename_teams(call: CallbackQuery, session: AsyncSession):
    """Список команд — выбери, какую переименовать."""
    if not settings.is_admin(call.from_user.id):
        await call.answer("⛔", show_alert=True)
        return
    await call.answer()

    game_day_id = int(call.data.split(":")[1])
    teams_res = await session.execute(
        select(Team).where(Team.game_day_id == game_day_id).order_by(Team.id)
    )
    teams = teams_res.scalars().all()
    if not teams:
        await call.answer("⚠️ Команды ещё не созданы.", show_alert=True)
        return

    await call.message.edit_text(
        "✏️ <b>Переименование команд</b>\n\nВыбери команду, название которой хочешь изменить:",
        reply_markup=_teams_rename_kb(game_day_id, teams)
    )


@router.callback_query(F.data.startswith("rename_team_pick:"))
async def rename_team_pick(call: CallbackQuery, state: FSMContext, session: AsyncSession):
    """Выбрана конкретная команда — просим новое название."""
    if not settings.is_admin(call.from_user.id):
        await call.answer("⛔", show_alert=True)
        return
    await call.answer()

    _, game_day_id_str, team_id_str = call.data.split(":")
    game_day_id = int(game_day_id_str)
    team_id = int(team_id_str)

    team = await session.get(Team, team_id)
    if not team:
        await call.answer("❌ Команда не найдена.", show_alert=True)
        return

    await state.update_data(game_day_id=game_day_id, team_id=team_id)
    await state.set_state(RenameTeamsFSM.waiting_new_name)

    cancel_kb = InlineKeyboardBuilder()
    cancel_kb.row(InlineKeyboardButton(
        text="❌ Отмена",
        callback_data=f"gd_rename_teams:{game_day_id}"
    ))

    await call.message.edit_text(
        f"✏️ Переименование команды <b>{team.color_emoji} {team.name}</b>\n\n"
        f"Введи новое название (например: Sharks, Волки, Dream Team):",
        reply_markup=cancel_kb.as_markup()
    )


@router.message(StateFilter(RenameTeamsFSM.waiting_new_name))
async def rename_team_save(message: Message, state: FSMContext, session: AsyncSession):
    """Сохраняем новое название команды."""
    if not settings.is_admin(message.from_user.id):
        return

    new_name = message.text.strip()
    if len(new_name) < 1 or len(new_name) > 30:
        await message.answer("❌ Название должно быть от 1 до 30 символов. Попробуй ещё раз:")
        return

    data = await state.get_data()
    game_day_id = data["game_day_id"]
    team_id = data["team_id"]
    await state.clear()

    team = await session.get(Team, team_id)
    if not team:
        await message.answer("❌ Команда не найдена.")
        return

    old_name = team.name
    team.name = new_name
    await session.commit()

    # Показываем обновлённый список
    teams_res = await session.execute(
        select(Team).where(Team.game_day_id == game_day_id).order_by(Team.id)
    )
    teams = teams_res.scalars().all()

    await message.answer(
        f"✅ Команда <b>{team.color_emoji} {old_name}</b> переименована в <b>{team.color_emoji} {new_name}</b>!\n\n"
        "Выбери следующую команду или вернись к игровому дню:",
        reply_markup=_teams_rename_kb(game_day_id, teams)
    )


# ══════════════════════════════════════════════════════
#  ИТОГИ ТУРНИРА
# ══════════════════════════════════════════════════════

@router.callback_query(F.data.startswith("gd_tournament_results:"))
async def gd_tournament_results(call: CallbackQuery, session: AsyncSession, bot: Bot):
    if not settings.is_admin(call.from_user.id):
        await call.answer("⛔", show_alert=True)
        return
    await call.answer()

    from collections import Counter
    from app.database.models import (
        Match, MatchStatus, Goal, GoalType, Card, CardType,
        Team, TeamPlayer, RatingRound, RatingVote,
    )
    from sqlalchemy.orm import selectinload

    game_day_id = int(call.data.split(":")[1])
    game_day = await session.get(GameDay, game_day_id)
    if not game_day:
        await call.message.edit_text("❌ Игровой день не найден.")
        return

    # Load all finished matches with goals
    matches_res = await session.execute(
        select(Match)
        .options(
            selectinload(Match.team_home),
            selectinload(Match.team_away),
            selectinload(Match.goals).selectinload(Goal.player),
        )
        .where(Match.game_day_id == game_day_id, Match.status == MatchStatus.FINISHED)
        .order_by(Match.id)
    )
    finished_matches = matches_res.scalars().all()

    if not finished_matches:
        await call.answer("⚠️ Нет завершённых матчей.", show_alert=True)
        return

    # ── Determine places from FINAL and THIRD_PLACE matches ──
    places: dict[int, str] = {}  # team_id → place label

    final_match = next(
        (m for m in finished_matches if (m.match_stage or "group") == "final"), None
    )
    third_match = next(
        (m for m in finished_matches if (m.match_stage or "group") == "third_place"), None
    )

    # Use place_teams: place_number → team_id
    place_teams: dict[int, int] = {}

    if final_match:
        if final_match.score_home >= final_match.score_away:
            place_teams[1] = final_match.team_home_id
            place_teams[2] = final_match.team_away_id
        else:
            place_teams[1] = final_match.team_away_id
            place_teams[2] = final_match.team_home_id

    if third_match:
        if third_match.score_home >= third_match.score_away:
            place_teams[3] = third_match.team_home_id
            place_teams[4] = third_match.team_away_id
        else:
            place_teams[3] = third_match.team_away_id
            place_teams[4] = third_match.team_home_id

    # ── Top scorer ──
    goal_counts: Counter = Counter()
    for m in finished_matches:
        for g in m.goals:
            if g.goal_type != GoalType.OWN_GOAL and g.player:
                goal_counts[g.player.name] += 1

    # ── Best player from rating votes (last round for this game_day) ──
    best_player_name: str | None = None
    rating_res = await session.execute(
        select(RatingRound)
        .options(selectinload(RatingRound.votes))
        .where(
            RatingRound.game_day_id == game_day_id,
            RatingRound.status == "finished",
        )
        .order_by(RatingRound.id.desc())
        .limit(1)
    )
    last_round = rating_res.scalar_one_or_none()
    if last_round and last_round.votes:
        vote_totals: Counter = Counter()
        for v in last_round.votes:
            vote_totals[v.nominee_id] += v.score
        best_id = vote_totals.most_common(1)[0][0]
        bp = await session.get(Player, best_id)
        if bp:
            best_player_name = bp.name

    # ── Build admin result text (Russian) ──
    place_keys = {1: 'place_1', 2: 'place_2', 3: 'place_3', 4: 'place_4'}
    lines = [t('tournament_results_header', 'ru', game_name=game_day.display_name)]

    if place_teams:
        for place_num, key in place_keys.items():
            team_id = place_teams.get(place_num)
            if team_id:
                team = await session.get(Team, team_id)
                if team:
                    lines.append(f"{t(key, 'ru')}: <b>{team.color_emoji} {team.name}</b>")
    else:
        lines.append("⚠️ Финал и матч за 3 место не найдены.")
        lines.append("Назначь матчи с нужными стадиями в панели судьи.")

    # Top scorer
    if goal_counts:
        top_name, top_cnt = goal_counts.most_common(1)[0]
        lines.append(t('top_scorer', 'ru', name=top_name, count=top_cnt, goals_word=gw(top_cnt, 'ru')))

    # Best player
    if best_player_name:
        lines.append(t('best_player', 'ru', name=best_player_name))

    lines.append(t('tournament_thanks', 'ru'))

    result_text = "\n".join(lines)

    # Store place_teams for broadcast
    # Broadcast to attendees
    att_res = await session.execute(
        select(Attendance)
        .options(selectinload(Attendance.player))
        .where(
            Attendance.game_day_id == game_day_id,
            Attendance.response == AttendanceResponse.YES,
        )
    )
    attendees = att_res.scalars().all()

    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(
        text="📢 Разослать итоги всем",
        callback_data=f"gd_results_broadcast:{game_day_id}"
    ))
    builder.row(InlineKeyboardButton(
        text="🔙 Назад",
        callback_data=f"gd_players:{game_day_id}"
    ))

    await call.message.edit_text(result_text, reply_markup=builder.as_markup())


@router.callback_query(F.data.startswith("gd_results_broadcast:"))
async def gd_results_broadcast(call: CallbackQuery, session: AsyncSession, bot: Bot):
    if not settings.is_admin(call.from_user.id):
        await call.answer("⛔", show_alert=True)
        return
    await call.answer("📢 Рассылаю...")

    from collections import Counter
    from app.database.models import (
        Match, MatchStatus, Goal, GoalType, Card, CardType,
        Team, RatingRound, RatingVote,
    )
    from sqlalchemy.orm import selectinload

    game_day_id = int(call.data.split(":")[1])
    game_day = await session.get(GameDay, game_day_id)
    if not game_day:
        return

    matches_res = await session.execute(
        select(Match)
        .options(
            selectinload(Match.team_home),
            selectinload(Match.team_away),
            selectinload(Match.goals).selectinload(Goal.player),
        )
        .where(Match.game_day_id == game_day_id, Match.status == MatchStatus.FINISHED)
    )
    finished_matches = matches_res.scalars().all()

    place_teams: dict[int, int] = {}
    final_match = next(
        (m for m in finished_matches if (m.match_stage or "group") == "final"), None
    )
    third_match = next(
        (m for m in finished_matches if (m.match_stage or "group") == "third_place"), None
    )
    if final_match:
        if final_match.score_home >= final_match.score_away:
            place_teams[1] = final_match.team_home_id
            place_teams[2] = final_match.team_away_id
        else:
            place_teams[1] = final_match.team_away_id
            place_teams[2] = final_match.team_home_id
    if third_match:
        if third_match.score_home >= third_match.score_away:
            place_teams[3] = third_match.team_home_id
            place_teams[4] = third_match.team_away_id
        else:
            place_teams[3] = third_match.team_away_id
            place_teams[4] = third_match.team_home_id

    goal_counts: Counter = Counter()
    for m in finished_matches:
        for g in m.goals:
            if g.goal_type != GoalType.OWN_GOAL and g.player:
                goal_counts[g.player.name] += 1

    best_player_name: str | None = None
    rating_res = await session.execute(
        select(RatingRound)
        .options(selectinload(RatingRound.votes))
        .where(
            RatingRound.game_day_id == game_day_id,
            RatingRound.status == "finished",
        )
        .order_by(RatingRound.id.desc())
        .limit(1)
    )
    last_round = rating_res.scalar_one_or_none()
    if last_round and last_round.votes:
        from collections import Counter as _C
        vote_totals: _C = _C()
        for v in last_round.votes:
            vote_totals[v.nominee_id] += v.score
        best_id = vote_totals.most_common(1)[0][0]
        bp = await session.get(Player, best_id)
        if bp:
            best_player_name = bp.name

    # Build cached team names for places
    place_team_objects: dict[int, Team] = {}
    place_keys = {1: 'place_1', 2: 'place_2', 3: 'place_3', 4: 'place_4'}
    for place_num, team_id in place_teams.items():
        team_obj = await session.get(Team, team_id)
        if team_obj:
            place_team_objects[place_num] = team_obj

    att_res = await session.execute(
        select(Attendance)
        .options(selectinload(Attendance.player))
        .where(
            Attendance.game_day_id == game_day_id,
            Attendance.response == AttendanceResponse.YES,
        )
    )
    attendees = att_res.scalars().all()

    sent = 0
    for att in attendees:
        try:
            lang = getattr(att.player, 'language', None) or 'ru'
            lines = [t('tournament_results_header', lang, game_name=game_day.display_name)]

            for place_num, key in place_keys.items():
                team_obj = place_team_objects.get(place_num)
                if team_obj:
                    lines.append(f"{t(key, lang)}: <b>{team_obj.color_emoji} {team_obj.name}</b>")

            if goal_counts:
                top_name, top_cnt = goal_counts.most_common(1)[0]
                lines.append(t('top_scorer', lang, name=top_name, count=top_cnt,
                                goals_word=gw(top_cnt, lang)))
            if best_player_name:
                lines.append(t('best_player', lang, name=best_player_name))
            lines.append(t('tournament_thanks', lang))

            broadcast_text = "\n".join(lines)
            await bot.send_message(att.player.telegram_id, broadcast_text)
            sent += 1
            await asyncio.sleep(0.05)
        except Exception as e:
            logger.warning(f"Cannot send results to {att.player.telegram_id}: {e}")

    from app.keyboards.game_day import game_day_action_kb
    await call.message.answer(
        f"✅ Итоги разосланы <b>{sent}</b> игрокам.",
        reply_markup=game_day_action_kb(game_day_id)
    )


# ══════════════════════════════════════════════════════
#  РАЗОСЛАТЬ ИТОГИ (I-013) — кнопка из action_kb
# ══════════════════════════════════════════════════════

@router.callback_query(F.data.startswith("gd_post_results:"))
async def gd_post_results(call: CallbackQuery, session: AsyncSession, bot: Bot):
    """Прямая рассылка итогов турнира всем участникам из action_kb."""
    if not settings.is_admin(call.from_user.id):
        await call.answer("⛔", show_alert=True)
        return
    await call.answer("📢 Рассылаю итоги...")

    from collections import Counter
    from app.keyboards.game_day import game_day_action_kb

    game_day_id = int(call.data.split(":")[1])
    game_day = await session.get(GameDay, game_day_id)
    if not game_day:
        return

    # Загружаем завершённые матчи
    matches_res = await session.execute(
        select(Match)
        .options(
            selectinload(Match.team_home),
            selectinload(Match.team_away),
            selectinload(Match.goals).selectinload(Goal.player),
        )
        .where(Match.game_day_id == game_day_id, Match.status == MatchStatus.FINISHED)
    )
    finished_matches = matches_res.scalars().all()

    if not finished_matches:
        await call.answer(t('results_broadcast_empty', 'ru'), show_alert=True)
        return

    # Подсчёт мест
    place_teams: dict[int, int] = {}
    final_match = next((m for m in finished_matches if (m.match_stage or "group") == "final"), None)
    third_match = next((m for m in finished_matches if (m.match_stage or "group") == "third_place"), None)
    if final_match:
        if final_match.score_home >= final_match.score_away:
            place_teams[1], place_teams[2] = final_match.team_home_id, final_match.team_away_id
        else:
            place_teams[1], place_teams[2] = final_match.team_away_id, final_match.team_home_id
    if third_match:
        if third_match.score_home >= third_match.score_away:
            place_teams[3], place_teams[4] = third_match.team_home_id, third_match.team_away_id
        else:
            place_teams[3], place_teams[4] = third_match.team_away_id, third_match.team_home_id

    goal_counts: Counter = Counter()
    for m in finished_matches:
        for g in m.goals:
            if g.goal_type != GoalType.OWN_GOAL and g.player:
                goal_counts[g.player.name] += 1

    place_keys = {1: 'place_1', 2: 'place_2', 3: 'place_3', 4: 'place_4'}
    place_team_objects: dict[int, Team] = {}
    for place_num, team_id in place_teams.items():
        team_obj = await session.get(Team, team_id)
        if team_obj:
            place_team_objects[place_num] = team_obj

    # Все матчи (для отображения результатов)
    match_lines = []
    for m in finished_matches:
        match_lines.append(f"  ⚽ {m.team_home.name} {m.score_home}:{m.score_away} {m.team_away.name}")

    # Рассылка участникам
    att_res = await session.execute(
        select(Attendance)
        .options(selectinload(Attendance.player))
        .where(
            Attendance.game_day_id == game_day_id,
            Attendance.response == AttendanceResponse.YES,
        )
    )
    attendees = att_res.scalars().all()

    sent = 0
    for att in attendees:
        if not att.player:
            continue
        try:
            lang = getattr(att.player, 'language', None) or 'ru'
            lines = [t('tournament_results_header', lang, game_name=game_day.display_name)]
            lines.append(f"📅 {game_day.scheduled_at.strftime('%d.%m.%Y')}\n")

            # Все результаты матчей
            if match_lines:
                lines.append("<b>Результаты матчей:</b>")
                lines.extend(match_lines)
                lines.append("")

            # Места
            for place_num, key in place_keys.items():
                team_obj = place_team_objects.get(place_num)
                if team_obj:
                    lines.append(f"{t(key, lang)}: <b>{team_obj.color_emoji} {team_obj.name}</b>")

            # Топ бомбардир
            if goal_counts:
                top_name, top_cnt = goal_counts.most_common(1)[0]
                lines.append(t('top_scorer', lang, name=top_name, count=top_cnt,
                                goals_word=gw(top_cnt, lang)))
            lines.append(t('tournament_thanks', lang))

            await bot.send_message(att.player.telegram_id, "\n".join(lines))
            sent += 1
            await asyncio.sleep(0.05)
        except Exception as e:
            logger.warning(f"gd_post_results: cannot send to {att.player.telegram_id}: {e}")

    await call.message.answer(
        t('results_broadcast_sent', 'ru', count=sent),
        reply_markup=game_day_action_kb(game_day_id)
    )


# ══════════════════════════════════════════════════════
#  В КАНАЛ (I-043) — превью поста в боте
# ══════════════════════════════════════════════════════

@router.callback_query(F.data.startswith("gd_to_channel:"))
async def gd_to_channel(call: CallbackQuery, session: AsyncSession):
    """Присылает готовый пост-итоги в текущий чат (превью для ручной публикации)."""
    if not settings.is_admin(call.from_user.id):
        await call.answer("⛔", show_alert=True)
        return
    await call.answer()

    from collections import Counter
    from app.keyboards.game_day import game_day_action_kb

    game_day_id = int(call.data.split(":")[1])
    game_day = await session.get(GameDay, game_day_id)
    if not game_day:
        return

    matches_res = await session.execute(
        select(Match)
        .options(
            selectinload(Match.team_home),
            selectinload(Match.team_away),
            selectinload(Match.goals).selectinload(Goal.player),
        )
        .where(Match.game_day_id == game_day_id, Match.status == MatchStatus.FINISHED)
    )
    finished_matches = matches_res.scalars().all()

    if not finished_matches:
        await call.answer("⚠️ Нет завершённых матчей.", show_alert=True)
        return

    # Определяем места по финалу
    place_teams: dict[int, int] = {}
    final_match = next((m for m in finished_matches if (m.match_stage or "group") == "final"), None)
    third_match = next((m for m in finished_matches if (m.match_stage or "group") == "third_place"), None)
    if final_match:
        if final_match.score_home >= final_match.score_away:
            place_teams[1], place_teams[2] = final_match.team_home_id, final_match.team_away_id
        else:
            place_teams[1], place_teams[2] = final_match.team_away_id, final_match.team_home_id
    if third_match:
        if third_match.score_home >= third_match.score_away:
            place_teams[3], place_teams[4] = third_match.team_home_id, third_match.team_away_id
        else:
            place_teams[3], place_teams[4] = third_match.team_away_id, third_match.team_home_id

    goal_counts: Counter = Counter()
    for m in finished_matches:
        for g in m.goals:
            if g.goal_type != GoalType.OWN_GOAL and g.player:
                goal_counts[g.player.name] += 1

    lines = [f"🏆 <b>Итоги {game_day.display_name}</b>"]
    lines.append(f"📅 {game_day.scheduled_at.strftime('%d.%m.%Y')} | 📍 {game_day.location}\n")

    # Групповые матчи
    group_matches = [m for m in finished_matches if (m.match_stage or "group") == "group"]
    if group_matches:
        lines.append("<b>Групповой этап:</b>")
        for m in group_matches:
            lines.append(f"  {m.team_home.name} {m.score_home}:{m.score_away} {m.team_away.name}")

    # Плей-офф матчи
    playoff = [m for m in finished_matches if (m.match_stage or "group") != "group"]
    if playoff:
        lines.append("\n<b>Плей-офф:</b>")
        stage_labels = {"semifinal": "Полуфинал", "third_place": "Матч за 3-е", "final": "Финал"}
        semi_n = 0
        for m in playoff:
            stage = m.match_stage or "group"
            if stage == "semifinal":
                semi_n += 1
                label = f"Полуфинал {semi_n}"
            else:
                label = stage_labels.get(stage, stage)
            lines.append(f"  {label}: {m.team_home.name} {m.score_home}:{m.score_away} {m.team_away.name}")

    lines.append("")
    place_keys = {1: 'place_1', 2: 'place_2', 3: 'place_3', 4: 'place_4'}
    for place_num, team_id in place_teams.items():
        team_obj = await session.get(Team, team_id)
        if team_obj:
            lines.append(f"{t(place_keys[place_num], 'ru')}: <b>{team_obj.color_emoji} {team_obj.name}</b>")

    if goal_counts:
        top_name, top_cnt = goal_counts.most_common(1)[0]
        lines.append(t('top_scorer', 'ru', name=top_name, count=top_cnt, goals_word=gw(top_cnt, 'ru')))

    lines.append(t('tournament_thanks', 'ru'))

    post_text = "\n".join(lines)
    # Отправляем как превью в текущий чат
    await call.message.answer(
        "📋 <b>Готовый пост (скопируй и опубликуй в канале):</b>\n\n" + post_text,
        reply_markup=InlineKeyboardBuilder().row(
            InlineKeyboardButton(text="🔙 Назад", callback_data=f"gd_players:{game_day_id}")
        ).as_markup()
    )


# ══════════════════════════════════════════════════════
#  РАСПИСАНИЕ МАТЧЕЙ (I-042) — сетка турнира
# ══════════════════════════════════════════════════════

_ST = {"scheduled": "⏳", "in_progress": "▶️", "finished": "✅"}


def _st(match) -> str:
    v = match.status.value if hasattr(match.status, "value") else str(match.status)
    return _ST.get(v, "❓")


@router.callback_query(F.data.startswith("gd_schedule:"))
async def gd_schedule_view(call: CallbackQuery, session: AsyncSession):
    """Сетка турнира: круги группового этапа + плей-офф."""
    if not settings.is_admin(call.from_user.id):
        await call.answer("⛔", show_alert=True)
        return
    await call.answer()

    game_day_id = int(call.data.split(":")[1])
    game_day = await session.get(GameDay, game_day_id)
    if not game_day:
        await call.message.edit_text("❌ Игровой день не найден.")
        return

    # Команды игрового дня
    teams_res = await session.execute(select(Team).where(Team.game_day_id == game_day_id))
    teams = teams_res.scalars().all()
    n = len(teams)
    pairs_per_circle = n * (n - 1) // 2 if n >= 2 else 1

    # Групповые матчи из расписания (match_order > 0)
    grp_res = await session.execute(
        select(Match)
        .options(selectinload(Match.team_home), selectinload(Match.team_away))
        .where(
            Match.game_day_id == game_day_id,
            Match.match_order > 0,
            Match.match_stage == "group",
        )
        .order_by(Match.match_order)
    )
    group_matches = grp_res.scalars().all()

    # Плей-офф матчи (semifinal, third_place, final)
    playoff_res = await session.execute(
        select(Match)
        .options(selectinload(Match.team_home), selectinload(Match.team_away))
        .where(
            Match.game_day_id == game_day_id,
            Match.match_stage.in_(["semifinal", "third_place", "final"]),
        )
        .order_by(Match.id)
    )
    playoff_matches = playoff_res.scalars().all()

    lines = [f"📅 <b>Сетка турнира — {game_day.display_name}</b>"]

    if not group_matches and not playoff_matches:
        lines.append("\n📋 Расписание ещё не создано.")
        if n < 2:
            lines.append("⚠️ Сначала создай команды через «🎲 Создать команды».")
    else:
        # ── Групповой этап (разбивка по кругам) ──
        from collections import defaultdict
        circles: dict = defaultdict(list)
        for m in group_matches:
            circle_num = (m.match_order - 1) // pairs_per_circle + 1
            circles[circle_num].append(m)

        for circle_num in sorted(circles.keys()):
            ms = circles[circle_num]
            lines.append(f"\n🔵 <b>Круг {circle_num} ({len(ms)} матчей):</b>")
            parts = []
            for m in ms:
                icon = _st(m)
                score = f" {m.score_home}:{m.score_away}" if m.status == MatchStatus.FINISHED else ""
                parts.append(f"{icon} {m.team_home.name}–{m.team_away.name}{score}")
            lines.append(" · ".join(parts))

        # ── Плей-офф ──
        if playoff_matches:
            lines.append("\n🏆 <b>Плей-офф:</b>")
            semi_n = 0
            stage_labels = {
                "semifinal": None,       # заполняется динамически
                "third_place": "Матч за 3-е",
                "final": "Финал",
            }
            for m in playoff_matches:
                stage = m.match_stage or "group"
                icon = _st(m)
                if stage == "semifinal":
                    semi_n += 1
                    label = f"Полуфинал {semi_n}"
                else:
                    label = stage_labels.get(stage, stage)
                score = f" {m.score_home}:{m.score_away}" if m.status == MatchStatus.FINISHED else ""
                lines.append(f"  {icon} <b>{label}</b>: {m.team_home.name}–{m.team_away.name}{score}")
        else:
            # Плей-офф ещё не создан — показываем как пустые слоты
            group_all_done = group_matches and all(
                m.status == MatchStatus.FINISHED for m in group_matches
            )
            if group_matches:
                lines.append("\n🏆 <b>Плей-офф:</b>")
                if group_all_done:
                    lines.append("  ⏳ Полуфинал 1 (1-е vs 4-е)")
                    lines.append("  ⏳ Полуфинал 2 (2-е vs 3-е)")
                    lines.append("  ⏳ Матч за 3-е · ⏳ Финал")
                else:
                    lines.append("  <i>Откроется после завершения группового этапа</i>")

    # ── Кнопки управления ──
    builder = InlineKeyboardBuilder()

    group_all_done = bool(group_matches) and all(
        m.status == MatchStatus.FINISHED for m in group_matches
    )
    semis = [m for m in playoff_matches if m.match_stage == "semifinal"]
    semis_done = bool(semis) and all(m.status == MatchStatus.FINISHED for m in semis)
    has_finals = any(m.match_stage in ("third_place", "final") for m in playoff_matches)

    if not group_matches and n >= 2:
        builder.row(InlineKeyboardButton(
            text="🎲 Авто-расписание",
            callback_data=f"gd_sched_auto:{game_day_id}"
        ))
        builder.row(InlineKeyboardButton(
            text="➕ Добавить матч вручную",
            callback_data=f"gd_sched_add:{game_day_id}"
        ))
    elif group_all_done and not playoff_matches:
        builder.row(InlineKeyboardButton(
            text="🏆 Сформировать плей-офф",
            callback_data=f"gd_sched_playoff:{game_day_id}"
        ))
    elif semis_done and not has_finals:
        builder.row(InlineKeyboardButton(
            text="🏆 Создать финалы (3-е место + Финал)",
            callback_data=f"gd_sched_finals:{game_day_id}"
        ))

    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data=f"gd_players:{game_day_id}"))
    await call.message.edit_text("\n".join(lines), reply_markup=builder.as_markup())


@router.callback_query(F.data.startswith("gd_sched_add:"))
async def gd_sched_add_start(call: CallbackQuery, state: FSMContext, session: AsyncSession):
    """Начало добавления матча в расписание — выбор команды 1."""
    if not settings.is_admin(call.from_user.id):
        await call.answer("⛔", show_alert=True)
        return
    await call.answer()

    game_day_id = int(call.data.split(":")[1])
    await state.update_data(game_day_id=game_day_id)

    teams_res = await session.execute(
        select(Team).where(Team.game_day_id == game_day_id)
    )
    teams = teams_res.scalars().all()

    builder = InlineKeyboardBuilder()
    for team in teams:
        builder.row(InlineKeyboardButton(
            text=f"{team.color_emoji} {team.name}",
            callback_data=f"gd_sched_t1:{team.id}"
        ))
    builder.row(InlineKeyboardButton(text="❌ Отмена", callback_data=f"gd_schedule:{game_day_id}"))

    await state.set_state(ScheduleFSM.waiting_team1)
    await call.message.edit_text(
        t('schedule_add_title', 'ru'),
        reply_markup=builder.as_markup()
    )


@router.callback_query(F.data.startswith("gd_sched_t1:"), StateFilter(ScheduleFSM.waiting_team1))
async def gd_sched_pick_team1(call: CallbackQuery, state: FSMContext, session: AsyncSession):
    await call.answer()
    team1_id = int(call.data.split(":")[1])
    team1 = await session.get(Team, team1_id)
    if not team1:
        await call.answer("❌ Команда не найдена.", show_alert=True)
        return

    await state.update_data(team1_id=team1_id, team1_name=team1.name)
    data = await state.get_data()
    game_day_id = data["game_day_id"]

    # Показываем команды кроме выбранной
    teams_res = await session.execute(
        select(Team).where(Team.game_day_id == game_day_id, Team.id != team1_id)
    )
    teams = teams_res.scalars().all()

    builder = InlineKeyboardBuilder()
    for team in teams:
        builder.row(InlineKeyboardButton(
            text=f"{team.color_emoji} {team.name}",
            callback_data=f"gd_sched_t2:{team.id}"
        ))
    builder.row(InlineKeyboardButton(text="❌ Отмена", callback_data=f"gd_schedule:{game_day_id}"))

    await state.set_state(ScheduleFSM.waiting_team2)
    await call.message.edit_text(
        t('schedule_pick_team2', 'ru', team1=team1.name),
        reply_markup=builder.as_markup()
    )


@router.callback_query(F.data.startswith("gd_sched_t2:"), StateFilter(ScheduleFSM.waiting_team2))
async def gd_sched_pick_team2(call: CallbackQuery, state: FSMContext, session: AsyncSession):
    await call.answer()
    team2_id = int(call.data.split(":")[1])
    team2 = await session.get(Team, team2_id)
    if not team2:
        await call.answer("❌ Команда не найдена.", show_alert=True)
        return

    data = await state.get_data()
    await state.clear()

    game_day_id = data["game_day_id"]
    team1_id = data["team1_id"]
    team1_name = data["team1_name"]

    # Определяем следующий номер в расписании
    count_res = await session.execute(
        select(Match).where(Match.game_day_id == game_day_id, Match.match_order > 0)
    )
    existing = count_res.scalars().all()
    next_order = max((m.match_order for m in existing), default=0) + 1

    # Достаём настройки игрового дня
    game_day = await session.get(GameDay, game_day_id)

    # Создаём матч в расписании
    new_match = Match(
        game_day_id=game_day_id,
        team_home_id=team1_id,
        team_away_id=team2_id,
        match_order=next_order,
        status=MatchStatus.SCHEDULED,
        match_format=game_day.match_format if game_day else "time",
        duration_min=game_day.match_duration_min if game_day else 20,
        goals_to_win=game_day.goals_to_win if game_day else 3,
        match_stage="group",
    )
    session.add(new_match)
    await session.commit()

    await call.message.edit_text(
        t('schedule_added', 'ru', num=next_order) + f"\n\n{next_order}. {team1_name} vs {team2.name}",
        reply_markup=InlineKeyboardBuilder().row(
            InlineKeyboardButton(text="📅 Назад к расписанию", callback_data=f"gd_schedule:{game_day_id}")
        ).as_markup()
    )


@router.callback_query(F.data.startswith("gd_sched_auto:"))
async def gd_sched_auto_ask(call: CallbackQuery, session: AsyncSession):
    """Выбор количества кругов для авто-расписания."""
    if not settings.is_admin(call.from_user.id):
        await call.answer("⛔", show_alert=True)
        return
    await call.answer()

    game_day_id = int(call.data.split(":")[1])

    teams_res = await session.execute(select(Team).where(Team.game_day_id == game_day_id))
    teams = teams_res.scalars().all()
    n = len(teams)

    if n < 2:
        await call.answer("⚠️ Нужно минимум 2 команды.", show_alert=True)
        return

    pairs = n * (n - 1) // 2
    names = " · ".join(t.name for t in teams)

    def circles_label(k):
        w = "круг" if k == 1 else "круга" if k in (2, 3) else "кругов"
        return f"{k} {w} ({k * pairs} матчей)"

    builder = InlineKeyboardBuilder()
    for k in (1, 2, 3):
        builder.row(InlineKeyboardButton(
            text=circles_label(k),
            callback_data=f"gd_sched_circles:{game_day_id}:{k}"
        ))
    builder.row(InlineKeyboardButton(text="❌ Отмена", callback_data=f"gd_schedule:{game_day_id}"))

    await call.message.edit_text(
        f"🎲 <b>Авто-расписание</b>\n\n"
        f"Команды ({n}): {names}\n"
        f"Пар за круг: <b>{pairs}</b>\n\n"
        "Сколько кругов сыграть?",
        reply_markup=builder.as_markup()
    )


@router.callback_query(F.data.startswith("gd_sched_circles:"))
async def gd_sched_circles(call: CallbackQuery, session: AsyncSession):
    """Генерирует N кругов round-robin."""
    if not settings.is_admin(call.from_user.id):
        await call.answer("⛔", show_alert=True)
        return
    await call.answer("⏳ Генерирую расписание...")

    parts = call.data.split(":")
    game_day_id = int(parts[1])
    circles = int(parts[2])

    game_day = await session.get(GameDay, game_day_id)
    teams_res = await session.execute(select(Team).where(Team.game_day_id == game_day_id))
    teams = teams_res.scalars().all()

    if len(teams) < 2:
        await call.answer("⚠️ Нужно минимум 2 команды.", show_alert=True)
        return

    # Составляем все пары
    pairs = [(teams[i], teams[j]) for i in range(len(teams)) for j in range(i + 1, len(teams))]

    order = 0
    for _ in range(circles):
        for home_team, away_team in pairs:
            order += 1
            session.add(Match(
                game_day_id=game_day_id,
                team_home_id=home_team.id,
                team_away_id=away_team.id,
                match_order=order,
                status=MatchStatus.SCHEDULED,
                match_format=game_day.match_format if game_day else "time",
                duration_min=game_day.match_duration_min if game_day else 20,
                goals_to_win=game_day.goals_to_win if game_day else 3,
                match_stage="group",
            ))

    await session.commit()

    await call.message.edit_text(
        f"✅ Создано <b>{order}</b> матчей ({circles} {'круг' if circles==1 else 'круга' if circles in (2,3) else 'кругов'} × {len(pairs)} пар).\n\n"
        "После завершения всех матчей появится кнопка «Сформировать плей-офф».",
        reply_markup=InlineKeyboardBuilder().row(
            InlineKeyboardButton(text="📅 Сетка турнира", callback_data=f"gd_schedule:{game_day_id}")
        ).as_markup()
    )


@router.callback_query(F.data.startswith("gd_sched_playoff:"))
async def gd_sched_playoff(call: CallbackQuery, session: AsyncSession):
    """Создаёт полуфиналы на основе таблицы группового этапа."""
    if not settings.is_admin(call.from_user.id):
        await call.answer("⛔", show_alert=True)
        return
    await call.answer("⏳ Считаю таблицу...")

    game_day_id = int(call.data.split(":")[1])
    game_day = await session.get(GameDay, game_day_id)

    # Загружаем все завершённые групповые матчи
    grp_res = await session.execute(
        select(Match)
        .where(
            Match.game_day_id == game_day_id,
            Match.match_stage == "group",
            Match.status == MatchStatus.FINISHED,
        )
    )
    group_matches = grp_res.scalars().all()

    # Считаем таблицу
    stats: dict[int, dict] = {}
    for m in group_matches:
        for team_id, gf, ga in [
            (m.team_home_id, m.score_home, m.score_away),
            (m.team_away_id, m.score_away, m.score_home),
        ]:
            if team_id not in stats:
                stats[team_id] = {"W": 0, "D": 0, "L": 0, "GF": 0, "GA": 0}
            s = stats[team_id]
            s["GF"] += gf
            s["GA"] += ga
            if gf > ga:
                s["W"] += 1
            elif gf == ga:
                s["D"] += 1
            else:
                s["L"] += 1

    for s in stats.values():
        s["Pts"] = s["W"] * 3 + s["D"]

    ranked = sorted(
        stats.keys(),
        key=lambda tid: (-stats[tid]["Pts"], -(stats[tid]["GF"] - stats[tid]["GA"]), -stats[tid]["GF"])
    )

    if len(ranked) < 2:
        await call.answer("⚠️ Недостаточно данных для плей-офф.", show_alert=True)
        return

    fmt = game_day.match_format if game_day else "time"
    dur = game_day.match_duration_min if game_day else 20
    gtw = game_day.goals_to_win if game_day else 3

    if len(ranked) >= 4:
        # 1-е vs 4-е, 2-е vs 3-е
        session.add(Match(
            game_day_id=game_day_id,
            team_home_id=ranked[0], team_away_id=ranked[3],
            match_order=0, match_stage="semifinal",
            status=MatchStatus.SCHEDULED,
            match_format=fmt, duration_min=dur, goals_to_win=gtw,
        ))
        session.add(Match(
            game_day_id=game_day_id,
            team_home_id=ranked[1], team_away_id=ranked[2],
            match_order=0, match_stage="semifinal",
            status=MatchStatus.SCHEDULED,
            match_format=fmt, duration_min=dur, goals_to_win=gtw,
        ))
        msg = "✅ Созданы <b>Полуфинал 1</b> (1-е vs 4-е) и <b>Полуфинал 2</b> (2-е vs 3-е)."
    elif len(ranked) == 3:
        # 1-е получает bye, 2-е vs 3-е → финал: 1-е vs победитель
        session.add(Match(
            game_day_id=game_day_id,
            team_home_id=ranked[1], team_away_id=ranked[2],
            match_order=0, match_stage="semifinal",
            status=MatchStatus.SCHEDULED,
            match_format=fmt, duration_min=dur, goals_to_win=gtw,
        ))
        msg = "✅ Создан <b>Полуфинал</b> (2-е vs 3-е). Победитель сыграет с 1-м в финале."
    else:
        # 2 команды — сразу финал
        session.add(Match(
            game_day_id=game_day_id,
            team_home_id=ranked[0], team_away_id=ranked[1],
            match_order=0, match_stage="final",
            status=MatchStatus.SCHEDULED,
            match_format=fmt, duration_min=dur, goals_to_win=gtw,
        ))
        msg = "✅ Создан <b>Финал</b> (1-е vs 2-е)."

    await session.commit()
    await call.message.edit_text(
        msg + "\n\nСудья найдёт матчи в своей панели.",
        reply_markup=InlineKeyboardBuilder().row(
            InlineKeyboardButton(text="📅 Сетка турнира", callback_data=f"gd_schedule:{game_day_id}")
        ).as_markup()
    )


@router.callback_query(F.data.startswith("gd_sched_finals:"))
async def gd_sched_finals(call: CallbackQuery, session: AsyncSession):
    """Создаёт матч за 3-е место и Финал по итогам полуфиналов."""
    if not settings.is_admin(call.from_user.id):
        await call.answer("⛔", show_alert=True)
        return
    await call.answer("⏳ Формирую финальные матчи...")

    game_day_id = int(call.data.split(":")[1])
    game_day = await session.get(GameDay, game_day_id)

    semis_res = await session.execute(
        select(Match)
        .where(
            Match.game_day_id == game_day_id,
            Match.match_stage == "semifinal",
            Match.status == MatchStatus.FINISHED,
        )
        .order_by(Match.id)
    )
    semis = semis_res.scalars().all()

    if len(semis) < 2:
        await call.answer("⚠️ Нужно минимум 2 завершённых полуфинала.", show_alert=True)
        return

    def winner(m: Match) -> int:
        return m.team_home_id if m.score_home >= m.score_away else m.team_away_id

    def loser(m: Match) -> int:
        return m.team_away_id if m.score_home >= m.score_away else m.team_home_id

    fmt = game_day.match_format if game_day else "time"
    dur = game_day.match_duration_min if game_day else 20
    gtw = game_day.goals_to_win if game_day else 3

    # Матч за 3-е: проигравшие полуфиналов
    session.add(Match(
        game_day_id=game_day_id,
        team_home_id=loser(semis[0]), team_away_id=loser(semis[1]),
        match_order=0, match_stage="third_place",
        status=MatchStatus.SCHEDULED,
        match_format=fmt, duration_min=dur, goals_to_win=gtw,
    ))
    # Финал: победители полуфиналов
    session.add(Match(
        game_day_id=game_day_id,
        team_home_id=winner(semis[0]), team_away_id=winner(semis[1]),
        match_order=0, match_stage="final",
        status=MatchStatus.SCHEDULED,
        match_format=fmt, duration_min=dur, goals_to_win=gtw,
    ))
    await session.commit()

    await call.message.edit_text(
        "✅ Созданы <b>Матч за 3-е место</b> и <b>Финал</b>.\n\n"
        "Судья найдёт их в своей панели.",
        reply_markup=InlineKeyboardBuilder().row(
            InlineKeyboardButton(text="📅 Сетка турнира", callback_data=f"gd_schedule:{game_day_id}")
        ).as_markup()
    )


# ══════════════════════════════════════════════════════
#  УПРАВЛЕНИЕ БАНКОВСКОЙ КАРТОЙ
# ══════════════════════════════════════════════════════

async def _get_admin_league(call: CallbackQuery, session: AsyncSession):
    """Получить лигу текущего администратора."""
    p_res = await session.execute(
        select(Player).where(Player.telegram_id == call.from_user.id)
    )
    admin_player = p_res.scalar_one_or_none()
    if not admin_player or not admin_player.league_id:
        return None
    return await session.get(League, admin_player.league_id)


def _card_kb(has_card: bool) -> "InlineKeyboardMarkup":
    builder = InlineKeyboardBuilder()
    if has_card:
        builder.row(InlineKeyboardButton(text="✏️ Изменить карту", callback_data="admin_card_edit"))
        builder.row(InlineKeyboardButton(text="🗑 Удалить карту", callback_data="admin_card_delete"))
    else:
        builder.row(InlineKeyboardButton(text="➕ Добавить карту", callback_data="admin_card_edit"))
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back"))
    return builder.as_markup()


@router.callback_query(F.data == "admin_card")
async def admin_card_view(call: CallbackQuery, session: AsyncSession):
    """Показать текущую банковскую карту лиги."""
    if not settings.is_admin(call.from_user.id):
        await call.answer("⛔", show_alert=True)
        return
    await call.answer()

    league = await _get_admin_league(call, session)
    if not league:
        await call.message.edit_text("❌ Лига не найдена.", reply_markup=_card_kb(False))
        return

    if league.card_number:
        text = (
            f"💳 <b>Банковская карта</b>\n\n"
            f"Текущий номер карты:\n<code>{league.card_number}</code>\n\n"
            "Этот номер отправляется игрокам при рассылке финансового итога."
        )
    else:
        text = (
            "💳 <b>Банковская карта</b>\n\n"
            "Карта пока не добавлена.\n\n"
            "Добавь номер карты — он будет отправляться игрокам при рассылке финансового итога."
        )

    await call.message.edit_text(text, reply_markup=_card_kb(bool(league.card_number)))


@router.callback_query(F.data == "admin_card_edit")
async def admin_card_edit_start(call: CallbackQuery, state: FSMContext):
    """Начать ввод нового номера карты."""
    if not settings.is_admin(call.from_user.id):
        await call.answer("⛔", show_alert=True)
        return
    await call.answer()

    await state.set_state(AdminCardFSM.waiting_card_number)
    cancel_kb = InlineKeyboardBuilder()
    cancel_kb.row(InlineKeyboardButton(text="❌ Отмена", callback_data="admin_card"))
    await call.message.edit_text(
        "💳 <b>Введи номер банковской карты</b>\n\n"
        "Например: <code>4276 1234 5678 9012</code>\n\n"
        "<i>Игроки увидят его как копируемый текст при запросе оплаты.</i>",
        reply_markup=cancel_kb.as_markup()
    )


@router.message(StateFilter(AdminCardFSM.waiting_card_number))
async def admin_card_save(message: Message, state: FSMContext, session: AsyncSession):
    """Сохранить новый номер карты."""
    if not settings.is_admin(message.from_user.id):
        return

    card = message.text.strip() if message.text else ""
    if not card:
        await message.answer("❌ Введи номер карты:")
        return

    p_res = await session.execute(
        select(Player).where(Player.telegram_id == message.from_user.id)
    )
    admin_player = p_res.scalar_one_or_none()
    if not admin_player or not admin_player.league_id:
        await message.answer("❌ Лига не найдена.")
        await state.clear()
        return

    league = await session.get(League, admin_player.league_id)
    if not league:
        await message.answer("❌ Лига не найдена.")
        await state.clear()
        return

    league.card_number = card
    await session.commit()
    await state.clear()

    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="💳 Моя карта", callback_data="admin_card"))
    builder.row(InlineKeyboardButton(text="🔙 Меню", callback_data="admin_back"))
    await message.answer(
        f"✅ Номер карты сохранён:\n<code>{card}</code>",
        reply_markup=builder.as_markup()
    )


@router.callback_query(F.data == "admin_card_delete")
async def admin_card_delete(call: CallbackQuery, session: AsyncSession):
    """Удалить номер карты из лиги."""
    if not settings.is_admin(call.from_user.id):
        await call.answer("⛔", show_alert=True)
        return
    await call.answer()

    league = await _get_admin_league(call, session)
    if not league:
        await call.message.edit_text("❌ Лига не найдена.")
        return

    league.card_number = None
    await session.commit()

    await call.message.edit_text(
        "🗑 Номер карты удалён.\n\n"
        "Теперь при рассылке финансового итога бот будет спрашивать номер карты каждый раз.",
        reply_markup=_card_kb(False)
    )


# ══════════════════════════════════════════════════════
#  ОПРОСЫ (Polls)
# ══════════════════════════════════════════════════════

def _poll_cancel_kb(back_data: str = "admin_back"):
    """Кнопка отмены FSM опроса."""
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="❌ Отмена", callback_data=back_data))
    return builder.as_markup()


@router.callback_query(F.data.startswith("gd_poll:"))
async def gd_poll_start(call: CallbackQuery, state: FSMContext, session: AsyncSession):
    """Запуск опроса для участников конкретного игрового дня."""
    if not settings.is_admin(call.from_user.id):
        await call.answer("⛔", show_alert=True)
        return
    await call.answer()

    game_day_id = int(call.data.split(":")[1])

    # Проверяем что есть участники
    result = await session.execute(
        select(Attendance)
        .options(selectinload(Attendance.player))
        .where(
            Attendance.game_day_id == game_day_id,
            Attendance.response == AttendanceResponse.YES,
        )
    )
    attendances = result.scalars().all()
    if not attendances:
        await call.message.edit_text(
            "⚠️ Нет зарегистрированных участников для этого игрового дня.",
            reply_markup=_poll_cancel_kb(f"gd_players:{game_day_id}")
        )
        return

    await state.set_state(PollFSM.waiting_question)
    await state.update_data(target="game_day", game_day_id=game_day_id)

    await call.message.edit_text(
        f"📢 <b>Опрос для участников игрового дня</b> (ID {game_day_id})\n\n"
        f"👥 Получателей: <b>{len(attendances)}</b>\n\n"
        "✏️ Введи <b>вопрос</b> для опроса:",
        reply_markup=_poll_cancel_kb(f"gd_players:{game_day_id}")
    )


@router.callback_query(F.data == "admin_poll")
async def admin_poll_start(call: CallbackQuery, state: FSMContext, session: AsyncSession):
    """Запуск опроса для всех игроков лиги."""
    if not settings.is_admin(call.from_user.id):
        await call.answer("⛔", show_alert=True)
        return
    await call.answer()

    # Получаем лигу администратора
    league = await _get_admin_league(call, session)
    if not league:
        await call.message.edit_text("❌ Лига не найдена.")
        return

    # Считаем активных игроков через PlayerLeague
    players = await _league_players(session, league.id, active_only=True)
    if not players:
        await call.message.edit_text(
            "⚠️ В лиге нет активных игроков.",
            reply_markup=_poll_cancel_kb("admin_back")
        )
        return

    await state.set_state(PollFSM.waiting_question)
    await state.update_data(target="league", league_id=league.id)

    await call.message.edit_text(
        f"📢 <b>Опрос для лиги «{league.name}»</b>\n\n"
        f"👥 Получателей: <b>{len(players)}</b>\n\n"
        "✏️ Введи <b>вопрос</b> для опроса:",
        reply_markup=_poll_cancel_kb("admin_back")
    )


@router.message(StateFilter(PollFSM.waiting_question))
async def poll_got_question(message: Message, state: FSMContext):
    """Получили вопрос — просим варианты ответов."""
    question = message.text.strip()
    if len(question) < 3:
        await message.answer("❗ Вопрос слишком короткий. Попробуй ещё раз:")
        return
    if len(question) > 300:
        await message.answer("❗ Вопрос слишком длинный (макс. 300 символов). Попробуй ещё раз:")
        return

    await state.update_data(question=question)
    await state.set_state(PollFSM.waiting_options)

    await message.answer(
        f"✅ Вопрос: <i>{question}</i>\n\n"
        "📝 Теперь введи <b>варианты ответов</b> — каждый с новой строки.\n"
        "<i>Минимум 2 варианта, максимум 10.</i>\n\n"
        "Пример:\n"
        "Да\n"
        "Нет\n"
        "Может быть",
        reply_markup=_poll_cancel_kb("admin_back")
    )


@router.message(StateFilter(PollFSM.waiting_options))
async def poll_got_options(message: Message, state: FSMContext, session: AsyncSession, bot: Bot):
    """Получили варианты — отправляем native Telegram poll."""
    raw = message.text.strip()
    options = [line.strip() for line in raw.splitlines() if line.strip()]

    if len(options) < 2:
        await message.answer("❗ Нужно минимум 2 варианта ответа. Попробуй ещё раз:")
        return
    if len(options) > 10:
        await message.answer("❗ Максимум 10 вариантов. Попробуй ещё раз:")
        return
    for opt in options:
        if len(opt) > 100:
            await message.answer(f"❗ Вариант слишком длинный (макс. 100 символов):\n«{opt[:50]}…»")
            return

    data = await state.get_data()
    question = data["question"]
    target = data.get("target", "league")
    await state.clear()

    # Собираем список получателей
    recipients: list[Player] = []

    if target == "game_day":
        game_day_id = data["game_day_id"]
        result = await session.execute(
            select(Attendance)
            .options(selectinload(Attendance.player))
            .where(
                Attendance.game_day_id == game_day_id,
                Attendance.response == AttendanceResponse.YES,
            )
        )
        recipients = [att.player for att in result.scalars().all() if att.player]
    else:
        league_id = data.get("league_id")
        if league_id:
            recipients = await _league_players(session, league_id, active_only=True)

    if not recipients:
        await message.answer("⚠️ Список получателей пуст. Опрос не отправлен.")
        return

    # Рассылаем
    sent = 0
    failed = 0
    for player in recipients:
        try:
            await bot.send_poll(
                chat_id=player.telegram_id,
                question=question,
                options=options,
                is_anonymous=True,
            )
            sent += 1
        except Exception as e:
            logger.warning(f"poll: не удалось отправить игроку {player.telegram_id}: {e}")
            failed += 1

    summary = (
        f"✅ Опрос разослан!\n\n"
        f"📨 Отправлено: <b>{sent}</b>\n"
    )
    if failed:
        summary += f"❌ Ошибки: <b>{failed}</b>"

    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🔙 Меню", callback_data="admin_back"))
    await message.answer(summary, reply_markup=builder.as_markup())


# ══════════════════════════════════════════════════════
#  ПАРОЛЬ ЛИГИ
# ══════════════════════════════════════════════════════

def _league_password_kb(league_id: int, has_password: bool) -> object:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(
        text="✏️ Изменить пароль" if has_password else "🔐 Установить пароль",
        callback_data=f"league_password_set:{league_id}"
    ))
    if has_password:
        builder.row(InlineKeyboardButton(
            text="🗑 Удалить пароль (открытая лига)",
            callback_data=f"league_password_delete:{league_id}"
        ))
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="admin_league_info"))
    return builder.as_markup()


@router.callback_query(F.data.startswith("league_password:"))
async def league_password_view(call: CallbackQuery, session: AsyncSession):
    """Просмотр/управление паролем лиги."""
    if not settings.is_admin(call.from_user.id):
        await call.answer("⛔", show_alert=True)
        return
    await call.answer()

    league_id = int(call.data.split(":")[1])
    league = await session.get(League, league_id)
    if not league:
        await call.message.edit_text("❌ Лига не найдена.")
        return

    if league.password:
        status = f"🔒 Пароль установлен: <code>{league.password}</code>"
    else:
        status = "🔓 Пароль не установлен — лига открытая (любой может вступить)"

    await call.message.edit_text(
        f"🔑 <b>Пароль лиги «{league.name}»</b>\n\n{status}",
        reply_markup=_league_password_kb(league_id, bool(league.password))
    )


@router.callback_query(F.data.startswith("league_password_set:"))
async def league_password_set_start(call: CallbackQuery, state: FSMContext):
    """Начать ввод нового пароля."""
    if not settings.is_admin(call.from_user.id):
        await call.answer("⛔", show_alert=True)
        return
    await call.answer()

    league_id = int(call.data.split(":")[1])
    await state.set_state(LeaguePasswordFSM.waiting_password)
    await state.update_data(league_id=league_id)

    cancel_kb = InlineKeyboardBuilder()
    cancel_kb.row(InlineKeyboardButton(
        text="❌ Отмена", callback_data=f"league_password:{league_id}"
    ))
    await call.message.edit_text(
        "🔐 Введи новый пароль для лиги:\n\n"
        "<i>Игроки будут вводить его при вступлении.\n"
        "Используй простые слова — игроки вводят вручную.</i>",
        reply_markup=cancel_kb.as_markup()
    )


@router.message(StateFilter(LeaguePasswordFSM.waiting_password))
async def league_password_save(message: Message, state: FSMContext, session: AsyncSession):
    """Сохранить пароль лиги."""
    password = message.text.strip()
    if len(password) < 2:
        await message.answer("❌ Пароль слишком короткий. Минимум 2 символа:")
        return
    if len(password) > 50:
        await message.answer("❌ Пароль слишком длинный. Максимум 50 символов:")
        return

    data = await state.get_data()
    league_id = data["league_id"]
    await state.clear()

    league = await session.get(League, league_id)
    if not league:
        await message.answer("❌ Лига не найдена.")
        return

    league.password = password
    await session.commit()

    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(
        text="🔑 Управление паролем", callback_data=f"league_password:{league_id}"
    ))
    builder.row(InlineKeyboardButton(text="🔙 Моя лига", callback_data="admin_league_info"))
    await message.answer(
        f"✅ Пароль установлен: <code>{password}</code>\n\n"
        "Теперь игроки должны ввести этот пароль при вступлении в лигу.",
        reply_markup=builder.as_markup()
    )


@router.callback_query(F.data.startswith("league_password_delete:"))
async def league_password_delete(call: CallbackQuery, session: AsyncSession):
    """Удалить пароль лиги."""
    if not settings.is_admin(call.from_user.id):
        await call.answer("⛔", show_alert=True)
        return
    await call.answer()

    league_id = int(call.data.split(":")[1])
    league = await session.get(League, league_id)
    if not league:
        await call.message.edit_text("❌ Лига не найдена.")
        return

    league.password = None
    await session.commit()

    await call.message.edit_text(
        "✅ Пароль удалён. Лига открытая — любой может вступить.",
        reply_markup=_league_password_kb(league_id, False)
    )

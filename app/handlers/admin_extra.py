"""
Дополнительные хендлеры Admin:
  - Активные игры
  - Прошедшие игры
  - Финансовый итог
  - Моя лига
  - /create_league команда
"""
from datetime import datetime
from urllib.parse import quote
import asyncio
import logging

logger = logging.getLogger(__name__)

from aiogram import Router, F, Bot
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message, InlineKeyboardButton, InlineKeyboardMarkup
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
    if finished_matches:
        builder.row(InlineKeyboardButton(
            text="✏️ Редактировать результаты матчей",
            callback_data=f"adm_edit_matches:{game_day_id}"
        ))
        builder.row(InlineKeyboardButton(
            text="🏆 Итоги турнира",
            callback_data=f"gd_tournament_results:{game_day_id}"
        ))
        builder.row(
            InlineKeyboardButton(
                text="📢 Разослать итоги",
                callback_data=f"gd_post_results:{game_day_id}"
            ),
            InlineKeyboardButton(
                text="📣 В канал",
                callback_data=f"gd_to_channel:{game_day_id}"
            ),
        )
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
            method_prompt = {
                "ru": "\n\nКак будешь платить? 👇",
                "en": "\n\nHow will you pay? 👇",
                "uz": "\n\nQanday to'laysiz? 👇",
                "de": "\n\nWie wirst du zahlen? 👇",
            }
            from app.keyboards.game_day import payment_method_kb
            await bot.send_message(
                p.telegram_id,
                base_text + card_line + method_prompt.get(lang, method_prompt["ru"]),
                reply_markup=payment_method_kb(game_day_id, lang),
            )
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


@router.callback_query(F.data.startswith("gd_rating:"))
async def gd_rating_start(call: CallbackQuery, session: AsyncSession, bot: Bot):
    """Запустить рейтинг-голосование среди участников конкретного игрового дня."""
    if not settings.is_admin(call.from_user.id):
        await call.answer("⛔", show_alert=True)
        return
    await call.answer()

    from app.keyboards.game_day import game_day_action_kb
    from datetime import datetime

    game_day_id = int(call.data.split(":")[1])

    # Проверить — нет ли уже активного раунда
    active_res = await session.execute(
        select(RatingRound).where(RatingRound.status == "active")
    )
    existing = active_res.scalar_one_or_none()
    if existing:
        from sqlalchemy import func as sqlfunc
        voted_res = await session.execute(
            select(sqlfunc.count(sqlfunc.distinct(RatingVote.voter_id)))
            .where(RatingVote.round_id == existing.id)
        )
        voted_count = voted_res.scalar() or 0
        builder = InlineKeyboardBuilder()
        builder.row(InlineKeyboardButton(
            text="🔒 Закрыть раунд и применить",
            callback_data=f"rating_round_close:{existing.id}"
        ))
        builder.row(InlineKeyboardButton(
            text="🔙 Назад", callback_data=f"gd_players:{game_day_id}"
        ))
        await call.message.edit_text(
            f"⚠️ <b>Уже есть активный раунд голосования</b>\n\n"
            f"Начат: {existing.started_at.strftime('%d.%m.%Y %H:%M')}\n"
            f"📊 Проголосовали: <b>{voted_count}</b> игроков\n\n"
            "Сначала закрой текущий раунд, потом запускай новый.",
            reply_markup=builder.as_markup()
        )
        return

    # Получить YES-участников этого игрового дня
    att_res = await session.execute(
        select(Attendance)
        .options(selectinload(Attendance.player))
        .where(
            Attendance.game_day_id == game_day_id,
            Attendance.response == AttendanceResponse.YES,
        )
    )
    attendances = att_res.scalars().all()
    players = [a.player for a in attendances if a.player]

    if not players:
        await call.answer("❌ Нет записавшихся игроков", show_alert=True)
        return

    # Создать раунд привязанный к игровому дню
    round_ = RatingRound(
        triggered_by=f"admin:{call.from_user.id}",
        status="active",
        game_day_id=game_day_id,
    )
    session.add(round_)
    await session.flush()
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
    builder.row(InlineKeyboardButton(
        text="🔙 Назад", callback_data=f"gd_players:{game_day_id}"
    ))

    game_day = await session.get(GameDay, game_day_id)
    gd_name = game_day.display_name if game_day else f"#{game_day_id}"

    await call.message.edit_text(
        f"⭐ <b>Рейтинг-голосование запущено!</b>\n\n"
        f"🏆 {gd_name} · {sent} игроков\n\n"
        "Каждый участник получил приглашение оценить других.\n"
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

TEAM_COLORS = ["🔴", "🟡", "🔵", "🟢", "⚫", "⚪"]
TEAM_NAMES  = ["Red", "Golden", "Blue", "Green", "Black", "White"]


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
#  РУЧНОЙ НАБОР КОМАНД
# ══════════════════════════════════════════════════════

class ManualTeamsFSM(StatesGroup):
    waiting_num_teams = State()   # выбор числа команд
    assigning = State()           # назначение игроков


def _manual_teams_kb(game_day_id: int, num_teams: int, assignments: dict,
                     current_idx: int, player_ids: list, players_map: dict,
                     current_sel: list) -> InlineKeyboardMarkup:
    """Клавиатура экрана ручного набора команд."""
    builder = InlineKeyboardBuilder()

    # Верхняя строка — кнопки команд
    team_row = []
    for i in range(num_teams):
        color = TEAM_COLORS[i]
        name = TEAM_NAMES[i]
        count = len(assignments.get(str(i), []))
        done = count > 0
        active = i == current_idx
        label = f"{'→ ' if active else ''}{color} {name}" + (f" ✓{count}" if done else "")
        team_row.append(InlineKeyboardButton(
            text=label,
            callback_data=f"mteam_pick:{game_day_id}:{i}"
        ))
    # По 3 в ряд
    for j in range(0, len(team_row), 3):
        builder.row(*team_row[j:j+3])

    # Список игроков — уже назначенные скрыты
    assigned_ids = {pid for lst in assignments.values() for pid in lst}
    available = [pid for pid in player_ids if pid not in assigned_ids]
    for pid in available:
        name = players_map.get(str(pid), f"#{pid}")
        label = f"✅ {name}" if pid in current_sel else name
        builder.button(text=label, callback_data=f"mteam_sel:{pid}")
    builder.adjust(*(
        [3] * (len(team_row) // 3 + (1 if len(team_row) % 3 else 0))
        + [2] * (len(available) // 2 + (1 if len(available) % 2 else 0))
    ))

    color = TEAM_COLORS[current_idx]
    tname = TEAM_NAMES[current_idx]
    if current_sel:
        builder.row(InlineKeyboardButton(
            text=f"💾 Сохранить в {color} {tname}",
            callback_data=f"mteam_save:{game_day_id}"
        ))
    builder.row(
        InlineKeyboardButton(text="🗑 Сбросить выбор", callback_data="mteam_clear_sel"),
        InlineKeyboardButton(text="🔙 Отмена", callback_data=f"gd_players:{game_day_id}"),
    )
    return builder.as_markup()


async def _render_manual_teams(msg, state: FSMContext, edit: bool = True) -> None:
    """Перерисовать экран ручного набора."""
    data = await state.get_data()
    game_day_id = data["game_day_id"]
    num_teams = data["num_teams"]
    assignments: dict = data.get("assignments", {})
    current_idx: int = data.get("current_idx", 0)
    player_ids: list = data["player_ids"]
    players_map: dict = data["players_map"]
    current_sel: list = data.get("current_sel", [])

    assigned_total = sum(len(v) for v in assignments.values())
    color = TEAM_COLORS[current_idx]
    tname = TEAM_NAMES[current_idx]

    lines = [f"👥 <b>Ручной набор команд</b>  ({assigned_total}/{len(player_ids)} распределено)\n"]
    lines.append(f"<b>Выбираешь: {color} {tname}</b>")
    if current_sel:
        sel_names = ", ".join(players_map.get(str(pid), f"#{pid}") for pid in current_sel)
        lines.append(f"Отмечено: {sel_names}")
    lines.append("\n<i>Нажми на игрока чтобы отметить, затем «Сохранить»</i>")

    kb = _manual_teams_kb(
        game_day_id, num_teams, assignments, current_idx,
        player_ids, players_map, current_sel
    )
    text = "\n".join(lines)
    if edit:
        await msg.edit_text(text, reply_markup=kb)
    else:
        await msg.answer(text, reply_markup=kb)


@router.callback_query(F.data.startswith("manual_teams:"))
async def manual_teams_start(call: CallbackQuery, session: AsyncSession, state: FSMContext):
    """Старт ручного набора: спрашиваем число команд."""
    if not settings.is_admin(call.from_user.id):
        await call.answer("⛔", show_alert=True)
        return
    await call.answer()

    game_day_id = int(call.data.split(":")[1])

    # Если уже есть команды — спросить подтверждение
    teams_res = await session.execute(select(Team).where(Team.game_day_id == game_day_id))
    existing = teams_res.scalars().all()
    if existing:
        builder = InlineKeyboardBuilder()
        builder.row(InlineKeyboardButton(
            text="🔄 Удалить команды и пересоздать",
            callback_data=f"manual_teams_reset:{game_day_id}"
        ))
        builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data=f"gd_players:{game_day_id}"))
        await call.message.edit_text(
            f"⚠️ Уже есть {len(existing)} команды. Удалить и начать заново?",
            reply_markup=builder.as_markup()
        )
        return

    # Загрузить записавшихся
    result = await session.execute(
        select(Attendance)
        .options(selectinload(Attendance.player))
        .where(Attendance.game_day_id == game_day_id, Attendance.response == AttendanceResponse.YES)
    )
    attendances = result.scalars().all()
    players = sorted([a.player for a in attendances if a.player], key=lambda p: p.name)

    if len(players) < 2:
        await call.answer("⚠️ Нужно минимум 2 игрока.", show_alert=True)
        return

    players_map = {str(p.id): p.name for p in players}
    await state.update_data(
        game_day_id=game_day_id,
        player_ids=[p.id for p in players],
        players_map=players_map,
        assignments={},
        current_idx=0,
        current_sel=[],
    )
    await state.set_state(ManualTeamsFSM.waiting_num_teams)

    n = len(players)
    builder = InlineKeyboardBuilder()
    for t in [2, 3, 4, 5, 6]:
        if n >= t * 2:
            builder.button(text=f"{t} команды" if t <= 4 else f"{t} команд",
                           callback_data=f"mteam_num:{game_day_id}:{t}")
    builder.adjust(3)
    builder.row(InlineKeyboardButton(text="🔙 Отмена", callback_data=f"gd_players:{game_day_id}"))

    await call.message.edit_text(
        f"✋ <b>Ручной набор команд</b>\n\n👥 Записалось: <b>{n}</b> игроков\n\nСколько команд?",
        reply_markup=builder.as_markup()
    )


@router.callback_query(F.data.startswith("manual_teams_reset:"))
async def manual_teams_reset(call: CallbackQuery, session: AsyncSession, state: FSMContext):
    """Удалить существующие команды и запустить ручной набор заново."""
    if not settings.is_admin(call.from_user.id):
        await call.answer("⛔", show_alert=True)
        return
    game_day_id = int(call.data.split(":")[1])
    from sqlalchemy import delete as sql_delete
    teams_res = await session.execute(select(Team).where(Team.game_day_id == game_day_id))
    for team in teams_res.scalars().all():
        await session.execute(sql_delete(TeamPlayer).where(TeamPlayer.team_id == team.id))
        await session.delete(team)
    await session.commit()
    call.data = f"manual_teams:{game_day_id}"
    await manual_teams_start(call, session, state)


@router.callback_query(F.data.startswith("mteam_num:"), StateFilter(ManualTeamsFSM.waiting_num_teams))
async def mteam_set_num(call: CallbackQuery, state: FSMContext):
    """Выбрали число команд — переходим к назначению."""
    await call.answer()
    num_teams = int(call.data.split(":")[2])
    await state.update_data(num_teams=num_teams, assignments={}, current_idx=0, current_sel=[])
    await state.set_state(ManualTeamsFSM.assigning)
    await _render_manual_teams(call.message, state, edit=True)


@router.callback_query(F.data.startswith("mteam_pick:"), StateFilter(ManualTeamsFSM.assigning))
async def mteam_pick_team(call: CallbackQuery, state: FSMContext):
    """Переключиться на другую команду."""
    await call.answer()
    idx = int(call.data.split(":")[2])
    await state.update_data(current_idx=idx, current_sel=[])
    await _render_manual_teams(call.message, state, edit=True)


@router.callback_query(F.data.startswith("mteam_sel:"), StateFilter(ManualTeamsFSM.assigning))
async def mteam_toggle_player(call: CallbackQuery, state: FSMContext):
    """Тогл игрока в текущем выборе."""
    pid = int(call.data.split(":")[1])
    data = await state.get_data()
    current_sel = list(data.get("current_sel", []))
    if pid in current_sel:
        current_sel.remove(pid)
        await call.answer("❌")
    else:
        current_sel.append(pid)
        await call.answer("✅")
    await state.update_data(current_sel=current_sel)
    await _render_manual_teams(call.message, state, edit=True)


@router.callback_query(F.data == "mteam_clear_sel", StateFilter(ManualTeamsFSM.assigning))
async def mteam_clear_sel(call: CallbackQuery, state: FSMContext):
    """Сбросить текущий выбор."""
    await call.answer("🗑 Сброшено")
    await state.update_data(current_sel=[])
    await _render_manual_teams(call.message, state, edit=True)


@router.callback_query(F.data.startswith("mteam_save:"), StateFilter(ManualTeamsFSM.assigning))
async def mteam_save_team(call: CallbackQuery, state: FSMContext):
    """Сохранить выбранных игроков в текущую команду."""
    await call.answer()
    data = await state.get_data()
    current_sel = list(data.get("current_sel", []))
    if not current_sel:
        await call.answer("⚠️ Никого не выбрано", show_alert=True)
        return

    assignments = dict(data.get("assignments", {}))
    current_idx = data["current_idx"]
    num_teams = data["num_teams"]

    assignments[str(current_idx)] = current_sel

    # Автопереход к следующей незаполненной команде
    next_idx = current_idx
    for i in range(num_teams):
        if str(i) not in assignments or not assignments[str(i)]:
            next_idx = i
            break
    else:
        next_idx = current_idx  # все заполнены

    await state.update_data(assignments=assignments, current_idx=next_idx, current_sel=[])
    data = await state.get_data()

    # Если все команды заполнены — показать сводку
    all_filled = all(str(i) in assignments and assignments[str(i)] for i in range(num_teams))
    if all_filled:
        await _render_manual_summary(call.message, data)
    else:
        await _render_manual_teams(call.message, state, edit=True)


async def _render_manual_summary(msg, data: dict) -> None:
    """Показать итоговую сводку команд с кнопками OK / Переназначить."""
    num_teams = data["num_teams"]
    assignments = data["assignments"]
    players_map = data["players_map"]
    game_day_id = data["game_day_id"]

    lines = ["👥 <b>Итоговые составы команд</b>\n"]
    for i in range(num_teams):
        color = TEAM_COLORS[i]
        name = TEAM_NAMES[i]
        pids = assignments.get(str(i), [])
        names = ", ".join(players_map.get(str(pid), f"#{pid}") for pid in pids)
        lines.append(f"{color} <b>{name}</b> ({len(pids)} чел.): {names}")

    unassigned_ids = {
        pid for pid in data["player_ids"]
        if not any(pid in assignments.get(str(i), []) for i in range(num_teams))
    }
    if unassigned_ids:
        un_names = ", ".join(players_map.get(str(pid), f"#{pid}") for pid in unassigned_ids)
        lines.append(f"\n⚠️ Не распределены: {un_names}")

    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="✅ Готово — создать команды", callback_data=f"mteam_confirm:{game_day_id}"),
    )
    builder.row(
        InlineKeyboardButton(text="🔄 Переназначить", callback_data=f"mteam_reassign:{game_day_id}"),
    )
    await msg.edit_text("\n".join(lines), reply_markup=builder.as_markup())


@router.callback_query(F.data.startswith("mteam_reassign:"))
async def mteam_reassign(call: CallbackQuery, state: FSMContext):
    """Вернуться к назначению (сбросить все команды)."""
    await call.answer()
    await state.update_data(assignments={}, current_idx=0, current_sel=[])
    await state.set_state(ManualTeamsFSM.assigning)
    await _render_manual_teams(call.message, state, edit=True)


@router.callback_query(F.data.startswith("mteam_confirm:"))
async def mteam_confirm(call: CallbackQuery, session: AsyncSession, state: FSMContext, bot: Bot):
    """Создать команды в БД и разослать игрокам."""
    if not settings.is_admin(call.from_user.id):
        await call.answer("⛔", show_alert=True)
        return
    await call.answer("⏳ Создаю команды...")

    data = await state.get_data()
    await state.clear()

    game_day_id = data["game_day_id"]
    num_teams = data["num_teams"]
    assignments = data["assignments"]
    players_map = data["players_map"]

    # Загрузить полные объекты Player
    all_pids = [pid for pids in assignments.values() for pid in pids]
    p_res = await session.execute(select(Player).where(Player.id.in_(all_pids)))
    players_by_id = {p.id: p for p in p_res.scalars().all()}

    game_day = await session.get(GameDay, game_day_id)
    gd_name = game_day.display_name if game_day else f"#{game_day_id}"

    from app.locales.texts import t as loc_t
    teams_data = []
    for i in range(num_teams):
        pids = assignments.get(str(i), [])
        if not pids:
            continue
        team = Team(game_day_id=game_day_id, name=TEAM_NAMES[i], color_emoji=TEAM_COLORS[i])
        session.add(team)
        await session.flush()
        members = []
        for pid in pids:
            session.add(TeamPlayer(team_id=team.id, player_id=pid))
            p = players_by_id.get(pid)
            if p:
                members.append({
                    "telegram_id": p.telegram_id,
                    "name": p.name,
                    "language": getattr(p, "language", None) or "ru",
                })
        teams_data.append({
            "name": TEAM_NAMES[i],
            "color": TEAM_COLORS[i],
            "members": members,
        })
    await session.commit()

    # Разослать игрокам
    sent = 0
    for team_info in teams_data:
        member_names = [m["name"] for m in team_info["members"]]
        for member in team_info["members"]:
            other_names = [n for n in member_names if n != member["name"]]
            lang = member.get("language", "ru")
            teammates_text = ", ".join(other_names) or "—"
            try:
                await bot.send_message(
                    member["telegram_id"],
                    loc_t("team_assigned", lang,
                          game_name=gd_name,
                          team_color=team_info["color"],
                          team_name=team_info["name"],
                          teammates=teammates_text),
                    parse_mode="HTML",
                )
                sent += 1
                await asyncio.sleep(0.05)
            except Exception as e:
                logger.warning(f"manual team notify failed: {e}")

    # Сводка для админа
    from app.keyboards.game_day import game_day_action_kb
    admin_lines = [f"✋ <b>Ручной набор завершён ({gd_name})</b>\n"]
    for team_info in teams_data:
        names = ", ".join(m["name"] for m in team_info["members"])
        admin_lines.append(f"{team_info['color']} <b>{team_info['name']}</b>: {names}")
    admin_lines.append(f"\n📨 Уведомлено: {sent}")
    await call.message.edit_text("\n".join(admin_lines), reply_markup=game_day_action_kb(game_day_id))


# ══════════════════════════════════════════════════════
#  BASKET-БАЛАНС (Task 19)
# ══════════════════════════════════════════════════════

class BasketFSM(StatesGroup):
    waiting_setup = State()             # выбор числа команд
    waiting_separate_players = State()  # задание правил разлучения


def _basket_render_setup(n_players: int, game_day_id: int) -> tuple[str, InlineKeyboardMarkup]:
    """Экран выбора числа команд."""
    auto = 4 if n_players >= 16 else (3 if n_players >= 9 else 2)
    text = (
        f"🎯 <b>Basket-баланс</b>\n\n"
        f"👥 Записалось: <b>{n_players}</b> игроков\n\n"
        f"Сколько команд создать?"
    )
    builder = InlineKeyboardBuilder()
    for t in [2, 3, 4, 5, 6]:
        if n_players >= t * 2:
            label = f"{t} команды" if t in (2, 3, 4) else f"{t} команд"
            if t == auto:
                label = "⭐ " + label
            builder.button(text=label, callback_data=f"basket_set_teams:{game_day_id}:{t}")
    builder.adjust(3)
    builder.row(InlineKeyboardButton(text="🔙 Отмена", callback_data=f"gd_players:{game_day_id}"))
    return text, builder.as_markup()


async def _basket_render_rules(msg, data: dict, edit: bool = True) -> None:
    """Экран выбора правил разлучения — перерисовывает сообщение."""
    game_day_id = data["game_day_id"]
    num_teams = data["num_teams"]
    player_ids: list[int] = data["player_ids"]
    players_map: dict[str, str] = data["players_map"]  # str(id) → name
    separate_rules: list[list[int]] = data.get("separate_rules", [])
    current_sel: list[int] = data.get("current_sel", [])

    lines = [f"🎯 <b>Basket-баланс</b>  👥 {len(player_ids)} игр. | {num_teams} команды"]

    if separate_rules:
        lines.append("\n<b>Правила разлучения:</b>")
        for i, rule in enumerate(separate_rules, 1):
            names = " ↔ ".join(players_map.get(str(pid), f"#{pid}") for pid in rule)
            lines.append(f"  {i}. {names}")

    if current_sel:
        sel_names = " + ".join(players_map.get(str(pid), f"#{pid}") for pid in current_sel)
        lines.append(f"\n<b>Текущий выбор:</b> {sel_names}")
        lines.append("<i>(выбери ещё игроков и нажми «Сохранить правило»)</i>")
    else:
        lines.append("\n<i>Выбери игроков для нового правила разлучения (минимум 2):</i>")

    # Собрать ID уже занятые правилами
    in_rule_ids = {pid for rule in separate_rules for pid in rule}

    builder = InlineKeyboardBuilder()
    for pid in player_ids:
        name = players_map.get(str(pid), f"#{pid}")
        if pid in current_sel:
            label = f"✅ {name}"
        elif pid in in_rule_ids:
            label = f"🔒 {name}"
        else:
            label = name
        builder.button(text=label, callback_data=f"basket_sep:{pid}")
    builder.adjust(2)

    if len(current_sel) >= 2:
        builder.row(
            InlineKeyboardButton(text="➕ Сохранить правило", callback_data="basket_add_rule"),
            InlineKeyboardButton(text="🗑 Сбросить выбор", callback_data="basket_clear_sel"),
        )
    elif current_sel:
        builder.row(InlineKeyboardButton(text="🗑 Сбросить выбор", callback_data="basket_clear_sel"))

    if separate_rules:
        builder.row(InlineKeyboardButton(text="❌ Очистить все правила", callback_data="basket_clear_rules"))

    builder.row(InlineKeyboardButton(
        text="✅ Готово — разбить на команды",
        callback_data=f"basket_execute:{game_day_id}:{num_teams}"
    ))
    builder.row(InlineKeyboardButton(text="🔙 Отмена", callback_data=f"gd_players:{game_day_id}"))

    text = "\n".join(lines)
    if edit:
        await msg.edit_text(text, reply_markup=builder.as_markup())
    else:
        await msg.answer(text, reply_markup=builder.as_markup())


@router.callback_query(F.data.startswith("gd_basket_teams:"))
async def basket_teams_start(call: CallbackQuery, session: AsyncSession, state: FSMContext):
    """Старт basket-балансировки: спрашиваем число команд."""
    if not settings.is_admin(call.from_user.id):
        await call.answer("⛔", show_alert=True)
        return
    await call.answer()

    game_day_id = int(call.data.split(":")[1])

    # Проверить — есть ли уже команды
    teams_res = await session.execute(select(Team).where(Team.game_day_id == game_day_id))
    existing_teams = teams_res.scalars().all()
    if existing_teams:
        builder = InlineKeyboardBuilder()
        builder.row(InlineKeyboardButton(
            text="🔄 Удалить команды и пересоздать",
            callback_data=f"basket_reset:{game_day_id}"
        ))
        builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data=f"gd_players:{game_day_id}"))
        await call.message.edit_text(
            f"⚠️ Уже есть {len(existing_teams)} команды. Удалить их и запустить basket-баланс?",
            reply_markup=builder.as_markup()
        )
        return

    # Загрузить записавшихся
    result = await session.execute(
        select(Attendance)
        .options(selectinload(Attendance.player))
        .where(Attendance.game_day_id == game_day_id, Attendance.response == AttendanceResponse.YES)
    )
    attendances = result.scalars().all()
    players: list[Player] = sorted(
        [a.player for a in attendances if a.player],
        key=lambda p: p.rating,
        reverse=True,
    )
    n_players = len(players)

    if n_players < 4:
        await call.answer("⚠️ Нужно минимум 4 игрока.", show_alert=True)
        return

    # Сохранить игроков в state для следующих шагов
    players_map = {str(p.id): p.name for p in players}
    await state.update_data(
        game_day_id=game_day_id,
        player_ids=[p.id for p in players],
        players_map=players_map,
        separate_rules=[],
        current_sel=[],
    )
    await state.set_state(BasketFSM.waiting_setup)

    text, kb = _basket_render_setup(n_players, game_day_id)
    await call.message.edit_text(text, reply_markup=kb)


@router.callback_query(F.data.startswith("basket_set_teams:"), StateFilter(BasketFSM.waiting_setup))
async def basket_set_teams(call: CallbackQuery, state: FSMContext):
    """Админ выбрал количество команд → переходим к правилам разлучения."""
    await call.answer()
    parts = call.data.split(":")
    num_teams = int(parts[2])

    await state.update_data(num_teams=num_teams, separate_rules=[], current_sel=[])
    await state.set_state(BasketFSM.waiting_separate_players)

    data = await state.get_data()
    await _basket_render_rules(call.message, data, edit=True)


def _split_baskets(players: list, num_teams: int, per_team: int) -> list[tuple[str, list]]:
    """Разбивает игроков на корзины для basket-балансировки."""
    total = num_teams * per_team
    players = players[:total]  # берём только нужное количество
    n = len(players)

    # Для 4 команд × 5 игроков: A(4) B(4) C(8) D(4) → 1+1+2+1
    # Общая формула: num_teams игроков на стандартную корзину, центральная = num_teams * (per_team - num_baskets + 1) ... но проще:
    # Корзины = [A: num_teams, B: num_teams, C: n - 3*num_teams, D: num_teams] для 4-корзинной схемы
    if per_team >= 4:
        a = players[:num_teams]
        b = players[num_teams:2 * num_teams]
        c = players[2 * num_teams: n - num_teams]
        d = players[n - num_teams:]
        return [("A", a), ("B", b), ("C", c), ("D", d)]
    elif per_team == 3:
        a = players[:num_teams]
        b = players[num_teams: 2 * num_teams]
        c = players[2 * num_teams:]
        return [("A", a), ("B", b), ("C", c)]
    else:
        a = players[:num_teams]
        b = players[num_teams:]
        return [("A", a), ("B", b)]


def _basket_assign(players: list, num_teams: int, per_team: int,
                   separate_rules: list[list[int]]) -> list[list]:
    """
    Распределяет игроков по num_teams командам используя basket-алгоритм.
    separate_rules: список правил — каждое правило = список ID игроков, которые
    должны оказаться в РАЗНЫХ командах.
    """
    import random
    from collections import defaultdict

    total = num_teams * per_team
    players = players[:total]
    baskets = _split_baskets(players, num_teams, per_team)

    # Построить граф ограничений: player_id → множество ID с кем нельзя быть
    constraints: dict[int, set[int]] = defaultdict(set)
    for rule in separate_rules:
        for i, pid in enumerate(rule):
            for j, other_pid in enumerate(rule):
                if i != j:
                    constraints[pid].add(other_pid)

    # Инициализируем команды
    teams: list[list] = [[] for _ in range(num_teams)]
    team_sets: list[set[int]] = [set() for _ in range(num_teams)]  # ID игроков в команде i

    # Из каждой корзины назначаем игроков с учётом ограничений
    for label, bucket in baskets:
        bucket = list(bucket)
        random.shuffle(bucket)

        # Сортируем: сначала игроки с ограничениями (их сложнее разместить)
        constrained = [p for p in bucket if p.id in constraints]
        free = [p for p in bucket if p.id not in constraints]
        ordered = constrained + free

        # Отслеживаем сколько из этой корзины уже назначено каждой команде
        basket_count = [0] * num_teams
        per_basket = len(bucket) // num_teams  # обычно 1

        for player in ordered:
            player_constraints = constraints.get(player.id, set())

            # Найти допустимые команды (нет нарушений ограничений + не переполнена)
            valid = [
                i for i in range(num_teams)
                if not (player_constraints & team_sets[i])
                and basket_count[i] < per_basket + 1
            ]
            if not valid:
                # Нарушение неизбежно — выбираем команду с наименьшим числом нарушений
                def violations(i):
                    return len(player_constraints & team_sets[i])
                valid = sorted(range(num_teams), key=lambda i: (violations(i), basket_count[i]))

            chosen = valid[0]
            teams[chosen].append(player)
            team_sets[chosen].add(player.id)
            basket_count[chosen] += 1

    return teams


@router.callback_query(F.data.startswith("basket_sep:"), StateFilter(BasketFSM.waiting_separate_players))
async def basket_sep_toggle(call: CallbackQuery, state: FSMContext):
    """Тогл выбора игрока для текущего правила."""
    player_id = int(call.data.split(":")[1])
    data = await state.get_data()
    current_sel: list = list(data.get("current_sel", []))
    separate_rules: list = data.get("separate_rules", [])

    # Не даём выбирать игрока который уже в каком-то правиле
    in_rule = any(player_id in rule for rule in separate_rules)
    if in_rule:
        await call.answer("🔒 Этот игрок уже в правиле разлучения", show_alert=False)
        return

    if player_id in current_sel:
        current_sel.remove(player_id)
        await call.answer("❌ Убран")
    else:
        current_sel.append(player_id)
        await call.answer("✅ Выбран")

    await state.update_data(current_sel=current_sel)
    data = await state.get_data()
    await _basket_render_rules(call.message, data, edit=True)


@router.callback_query(F.data == "basket_add_rule", StateFilter(BasketFSM.waiting_separate_players))
async def basket_add_rule(call: CallbackQuery, state: FSMContext):
    """Сохранить текущий выбор как правило разлучения."""
    data = await state.get_data()
    current_sel: list = list(data.get("current_sel", []))
    separate_rules: list = list(data.get("separate_rules", []))

    if len(current_sel) < 2:
        await call.answer("⚠️ Выбери минимум 2 игрока", show_alert=True)
        return

    separate_rules.append(current_sel)
    await state.update_data(separate_rules=separate_rules, current_sel=[])
    await call.answer(f"✅ Правило сохранено ({len(current_sel)} игроков)")

    data = await state.get_data()
    await _basket_render_rules(call.message, data, edit=True)


@router.callback_query(F.data == "basket_clear_sel", StateFilter(BasketFSM.waiting_separate_players))
async def basket_clear_sel(call: CallbackQuery, state: FSMContext):
    """Сбросить текущий выбор (не правила)."""
    await call.answer("🗑 Выбор сброшен")
    await state.update_data(current_sel=[])
    data = await state.get_data()
    await _basket_render_rules(call.message, data, edit=True)


@router.callback_query(F.data == "basket_clear_rules", StateFilter(BasketFSM.waiting_separate_players))
async def basket_clear_rules(call: CallbackQuery, state: FSMContext):
    """Очистить все правила разлучения."""
    await call.answer("❌ Все правила удалены")
    await state.update_data(separate_rules=[], current_sel=[])
    data = await state.get_data()
    await _basket_render_rules(call.message, data, edit=True)


@router.callback_query(F.data.startswith("basket_reset:"))
async def basket_reset(call: CallbackQuery, session: AsyncSession, state: FSMContext):
    """Удалить существующие команды и перезапустить basket-балансировку."""
    if not settings.is_admin(call.from_user.id):
        await call.answer("⛔", show_alert=True)
        return

    game_day_id = int(call.data.split(":")[1])
    from sqlalchemy import delete as sql_delete

    # Удалить TeamPlayer и Team
    teams_res = await session.execute(select(Team).where(Team.game_day_id == game_day_id))
    teams = teams_res.scalars().all()
    for team in teams:
        await session.execute(sql_delete(TeamPlayer).where(TeamPlayer.team_id == team.id))
        await session.delete(team)
    await session.commit()

    await call.answer("🗑 Команды удалены")
    # Перезапустить
    call.data = f"gd_basket_teams:{game_day_id}"
    await basket_teams_start(call, session, state)


@router.callback_query(F.data.startswith("basket_execute:"))
async def basket_execute(call: CallbackQuery, session: AsyncSession,
                         state: FSMContext, bot: Bot):
    """Создать команды по basket-алгоритму."""
    if not settings.is_admin(call.from_user.id):
        await call.answer("⛔", show_alert=True)
        return
    await call.answer("⏳ Формирую команды...")

    parts = call.data.split(":")
    game_day_id = int(parts[1])
    num_teams = int(parts[2])

    data = await state.get_data()
    separate_rules: list[list[int]] = data.get("separate_rules", [])
    await state.clear()

    # Загрузить игроков
    result = await session.execute(
        select(Attendance)
        .options(selectinload(Attendance.player))
        .where(Attendance.game_day_id == game_day_id, Attendance.response == AttendanceResponse.YES)
    )
    attendances = result.scalars().all()
    players: list[Player] = sorted(
        [a.player for a in attendances if a.player],
        key=lambda p: p.rating,
        reverse=True,
    )

    total_players = len(players)
    per_team = total_players // num_teams

    if per_team < 2:
        await call.answer("⚠️ Слишком мало игроков.", show_alert=True)
        return

    team_buckets = _basket_assign(players, num_teams, per_team, separate_rules)

    # Создать команды в БД
    from app.database.models import POSITION_LABELS, Position
    game_day = await session.get(GameDay, game_day_id)
    gd_name = game_day.display_name if game_day else f"#{game_day_id}"

    new_teams = []
    for i in range(num_teams):
        team = Team(game_day_id=game_day_id, name=TEAM_NAMES[i], color_emoji=TEAM_COLORS[i])
        session.add(team)
        new_teams.append(team)
    await session.flush()

    teams_data = []
    for i, team in enumerate(new_teams):
        bucket = team_buckets[i]
        avg_rating = sum(p.rating for p in bucket) / len(bucket) if bucket else 0.0
        members = []
        for p in bucket:
            session.add(TeamPlayer(team_id=team.id, player_id=p.id))
            members.append({
                "telegram_id": p.telegram_id,
                "name": p.name,
                "pos": POSITION_LABELS.get(p.position, p.position),
                "rating": p.rating,
                "language": getattr(p, "language", None) or "ru",
            })
        teams_data.append({
            "name": team.name,
            "color": team.color_emoji,
            "avg_rating": avg_rating,
            "members": members,
        })

    await session.commit()

    # Разослать командам
    from app.locales.texts import t as loc_t
    sent = 0
    for team_info in teams_data:
        member_names = [m["name"] for m in team_info["members"]]
        for member in team_info["members"]:
            other_names = [n for n in member_names if n != member["name"]]
            lang = member.get("language", "ru")
            teammates_text = ", ".join(other_names) or ("пока никого" if lang == "ru" else "no one yet")
            try:
                await bot.send_message(
                    member["telegram_id"],
                    loc_t("team_assigned", lang,
                          game_name=gd_name,
                          team_color=team_info["color"],
                          team_name=team_info["name"],
                          teammates=teammates_text)
                )
                sent += 1
                await asyncio.sleep(0.05)
            except Exception as e:
                logger.warning(f"basket team assign notify failed: {e}")

    # Сводка для администратора
    player_name_map = {p.id: p.name for p in players}
    admin_lines = [f"🎯 <b>Basket-баланс завершён! ({gd_name})</b>\n"]
    if separate_rules:
        admin_lines.append("↔️ <b>Правила разлучения:</b>")
        for rule in separate_rules:
            names = " ↔ ".join(player_name_map.get(pid, f"#{pid}") for pid in rule)
            admin_lines.append(f"  • {names}")
        admin_lines.append("")
    for team_info in teams_data:
        admin_lines.append(
            f"\n{team_info['color']} <b>Команда {team_info['name']}</b> "
            f"(⭐{team_info['avg_rating']:.1f}):"
        )
        for m in team_info["members"]:
            admin_lines.append(f"  • {m['name']} ({m['pos']}, ⭐{m['rating']})")
    admin_lines.append(f"\n📨 Уведомлено: {sent}/{total_players}")

    from app.keyboards.game_day import game_day_action_kb
    await call.message.answer("\n".join(admin_lines), reply_markup=game_day_action_kb(game_day_id))


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
#  ИТОГИ ТУРНИРА — вспомогательные функции
# ══════════════════════════════════════════════════════

from dataclasses import dataclass, field

@dataclass
class TournamentData:
    """Все данные о завершённом турнирном дне для формирования итогов."""
    game_day: object
    finished_matches: list
    place_teams: dict          # place_num → Team object
    # scorer_id → {"name": str, "count": int}
    scorer_stats: dict
    # player_id → {"name": str, "yellow": int, "red": int}
    card_stats: dict
    # team_id → {"team_name": str, "gk_name": str, "saves": int, "goals_conceded": int}
    gk_stats: dict
    # team_id → list of player names
    team_rosters: dict
    best_player_name: str | None
    total_goals: int
    total_matches: int


async def _gather_tournament_data(session, game_day_id: int) -> TournamentData | None:
    """Загружает все данные турнирного дня одним запросом."""
    from collections import Counter
    from app.database.models import (
        Match, MatchStatus, Goal, GoalType, Card, CardType,
        Team, RatingRound, MatchGoalkeeper,
    )
    from sqlalchemy.orm import selectinload

    game_day = await session.get(GameDay, game_day_id)
    if not game_day:
        return None

    # Все завершённые матчи + голы + карточки
    matches_res = await session.execute(
        select(Match)
        .options(
            selectinload(Match.team_home),
            selectinload(Match.team_away),
            selectinload(Match.goals).selectinload(Goal.player),
            selectinload(Match.cards).selectinload(Card.player),
        )
        .where(Match.game_day_id == game_day_id, Match.status == MatchStatus.FINISHED)
        .order_by(Match.id)
    )
    finished_matches = matches_res.scalars().all()
    if not finished_matches:
        return None

    # ── Места по финалу / матчу за 3-е ──
    place_teams: dict[int, object] = {}
    final_match = next((m for m in finished_matches if (m.match_stage or "group") == "final"), None)
    third_match = next((m for m in finished_matches if (m.match_stage or "group") == "third_place"), None)

    async def _team(team_id):
        return await session.get(Team, team_id)

    if final_match:
        if final_match.score_home >= final_match.score_away:
            place_teams[1] = await _team(final_match.team_home_id)
            place_teams[2] = await _team(final_match.team_away_id)
        else:
            place_teams[1] = await _team(final_match.team_away_id)
            place_teams[2] = await _team(final_match.team_home_id)
    if third_match:
        if third_match.score_home >= third_match.score_away:
            place_teams[3] = await _team(third_match.team_home_id)
            place_teams[4] = await _team(third_match.team_away_id)
        else:
            place_teams[3] = await _team(third_match.team_away_id)
            place_teams[4] = await _team(third_match.team_home_id)

    # ── Бомбардиры: player_id → {name, count} ──
    scorer_stats: dict[int, dict] = {}
    for m in finished_matches:
        for g in m.goals:
            if g.goal_type == GoalType.OWN_GOAL or not g.player:
                continue
            pid = g.player_id
            if pid not in scorer_stats:
                scorer_stats[pid] = {"name": g.player.name, "count": 0}
            scorer_stats[pid]["count"] += 1

    # ── Карточки: player_id → {name, yellow, red} ──
    card_stats: dict[int, dict] = {}
    for m in finished_matches:
        for c in m.cards:
            if not c.player:
                continue
            pid = c.player_id
            if pid not in card_stats:
                card_stats[pid] = {"name": c.player.name, "yellow": 0, "red": 0}
            if c.card_type == CardType.YELLOW:
                card_stats[pid]["yellow"] += 1
            else:
                card_stats[pid]["red"] += 1

    # ── Вратари / сейвы ──
    match_ids = [m.id for m in finished_matches]
    gk_stats: dict[int, dict] = {}  # team_id → stats
    if match_ids:
        gk_res = await session.execute(
            select(MatchGoalkeeper)
            .options(
                selectinload(MatchGoalkeeper.player),
                selectinload(MatchGoalkeeper.team),
                selectinload(MatchGoalkeeper.match),
            )
            .where(MatchGoalkeeper.match_id.in_(match_ids))
        )
        gk_records = gk_res.scalars().all()
        for gk in gk_records:
            if not gk.player or not gk.team:
                continue
            tid = gk.team_id
            # Считаем пропущенные голы (голы в матче в ворота этой команды)
            m = gk.match
            if m:
                conceded = m.score_away if gk.team_id == m.team_home_id else m.score_home
            else:
                conceded = 0
            if tid not in gk_stats:
                gk_stats[tid] = {
                    "team_name": gk.team.name,
                    "gk_name": gk.player.name,
                    "saves": 0,
                    "goals_conceded": 0,
                    "clean_sheets": 0,
                }
            gk_stats[tid]["saves"] += gk.saves or 0
            gk_stats[tid]["goals_conceded"] += conceded
            if conceded == 0:
                gk_stats[tid]["clean_sheets"] += 1

    # ── Лучший игрок (рейтинговое голосование) ──
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

    total_goals = sum(d["count"] for d in scorer_stats.values())
    # own goals too
    for m in finished_matches:
        for g in m.goals:
            if g.goal_type == GoalType.OWN_GOAL:
                total_goals += 1

    # ── Составы команд для итоговых мест ──
    team_rosters: dict[int, list[str]] = {}
    all_place_team_ids = {t.id for t in place_teams.values() if t}
    if all_place_team_ids:
        from sqlalchemy.orm import selectinload as _sl
        tp_res = await session.execute(
            select(TeamPlayer)
            .options(_sl(TeamPlayer.player))
            .where(TeamPlayer.team_id.in_(all_place_team_ids))
        )
        for tp in tp_res.scalars().all():
            if tp.player:
                team_rosters.setdefault(tp.team_id, []).append(tp.player.name)

    return TournamentData(
        game_day=game_day,
        finished_matches=finished_matches,
        place_teams=place_teams,
        scorer_stats=scorer_stats,
        card_stats=card_stats,
        gk_stats=gk_stats,
        team_rosters=team_rosters,
        best_player_name=best_player_name,
        total_goals=total_goals,
        total_matches=len(finished_matches),
    )


def _format_match_line(m, with_scorers: bool = True, label: str = "") -> list[str]:
    """Форматирует одну строку матча + (опционально) авторов голов."""
    from app.database.models import GoalType
    lines = []
    score = f"{m.score_home}:{m.score_away}"
    prefix = f"{label}: " if label else ""
    lines.append(f"  {prefix}{m.team_home.name} <b>{score}</b> {m.team_away.name}")
    if with_scorers and m.goals:
        home_scorers, away_scorers = [], []
        for g in m.goals:
            name = g.player.name if g.player else "?"
            suffix = " (аг)" if g.goal_type == GoalType.OWN_GOAL else (
                " (пен)" if g.goal_type == GoalType.PENALTY else ""
            )
            entry = f"{name}{suffix}"
            # автогол идёт в ворота своей команды — у нас team_id = атакующая команда
            if g.goal_type == GoalType.OWN_GOAL:
                # scored by home player → goes to away's goal
                if g.team_id == m.team_home_id:
                    away_scorers.append(entry)
                else:
                    home_scorers.append(entry)
            else:
                if g.team_id == m.team_home_id:
                    home_scorers.append(entry)
                else:
                    away_scorers.append(entry)
        scorer_parts = []
        if home_scorers:
            scorer_parts.append(f"    ⚽ {m.team_home.name}: {', '.join(home_scorers)}")
        if away_scorers:
            scorer_parts.append(f"    ⚽ {m.team_away.name}: {', '.join(away_scorers)}")
        lines.extend(scorer_parts)
    return lines


def _format_channel_post(data: TournamentData) -> str:
    """Строит полноценный пост-итог для публикации в канале."""
    gd = data.game_day
    lines = [
        f"🏆 <b>Итоги {gd.display_name}</b>",
        f"📅 {gd.scheduled_at.strftime('%d.%m.%Y')} | 📍 {gd.location}",
        "",
    ]

    # ── Матчи по стадиям ──
    stage_order = ["group", "semifinal", "third_place", "final"]
    stage_labels_ru = {
        "group": "Групповой этап",
        "semifinal": "Полуфинал",
        "third_place": "Матч за 3-е место",
        "final": "Финал",
    }
    grouped: dict[str, list] = {s: [] for s in stage_order}
    for m in data.finished_matches:
        stage = m.match_stage or "group"
        if stage not in grouped:
            grouped[stage] = []
        grouped[stage].append(m)

    for stage in stage_order:
        matches_in_stage = grouped.get(stage, [])
        if not matches_in_stage:
            continue
        lines.append(f"<b>{stage_labels_ru.get(stage, stage)}:</b>")
        semi_n = 0
        group_n = 0
        for m in matches_in_stage:
            if stage == "group":
                group_n += 1
                match_num = getattr(m, "match_order", 0) or group_n
                label = f"Матч {match_num}"
                lines.extend(_format_match_line(m, with_scorers=True, label=label))
            elif stage == "semifinal":
                semi_n += 1
                label = f"Полуфинал {semi_n}"
                lines.extend(_format_match_line(m, with_scorers=True, label=label))
            elif stage == "third_place":
                lines.extend(_format_match_line(m, with_scorers=True, label="Матч за 3-е место"))
            elif stage == "final":
                lines.extend(_format_match_line(m, with_scorers=True, label="Финал"))
            else:
                lines.extend(_format_match_line(m, with_scorers=True))
        lines.append("")

    # ── Места ──
    place_icons = {1: "🥇", 2: "🥈", 3: "🥉", 4: "4️⃣"}
    if data.place_teams:
        lines.append("<b>Итоговые места:</b>")
        for place_num in sorted(data.place_teams):
            team = data.place_teams[place_num]
            icon = place_icons.get(place_num, f"{place_num}.")
            lines.append(f"  {icon} {team.color_emoji} <b>{team.name}</b>")
            roster = data.team_rosters.get(team.id, [])
            if roster:
                lines.append(f"    👥 {', '.join(roster)}")
        lines.append("")

    # ── Топ-5 бомбардиров ──
    if data.scorer_stats:
        sorted_scorers = sorted(data.scorer_stats.values(), key=lambda x: x["count"], reverse=True)
        lines.append("<b>⚽ Лучшие бомбардиры:</b>")
        medals = ["🥇", "🥈", "🥉"]
        for i, s in enumerate(sorted_scorers[:5]):
            icon = medals[i] if i < 3 else f"{i + 1}."
            lines.append(f"  {icon} {s['name']} — {s['count']} гол(ов)")
        lines.append("")

    # ── Лучший игрок ──
    if data.best_player_name:
        lines.append(f"⭐ <b>Лучший игрок:</b> {data.best_player_name}")
        lines.append("")

    # ── Вратари / сейвы ──
    if data.gk_stats:
        gk_lines = []
        for tid, gk in data.gk_stats.items():
            parts = [f"🧤 {gk['gk_name']} ({gk['team_name']})"]
            if gk["saves"]:
                parts.append(f"{gk['saves']} сейв(ов)")
            if gk["clean_sheets"]:
                parts.append(f"{gk['clean_sheets']} «сухих»")
            gk_lines.append("  " + " — ".join(parts))
        if gk_lines:
            lines.append("<b>🧤 Вратари:</b>")
            lines.extend(gk_lines)
            lines.append("")

    # ── Карточки ──
    if data.card_stats:
        card_lines = []
        for pid, cs in data.card_stats.items():
            parts = []
            if cs["yellow"]:
                parts.append(f"🟨×{cs['yellow']}")
            if cs["red"]:
                parts.append(f"🟥×{cs['red']}")
            if parts:
                card_lines.append(f"  {cs['name']}: {' '.join(parts)}")
        if card_lines:
            lines.append("<b>📋 Карточки:</b>")
            lines.extend(card_lines)
            lines.append("")

    # ── Общая статистика ──
    avg = data.total_goals / data.total_matches if data.total_matches else 0
    lines.append(
        f"📊 <i>Матчей: {data.total_matches} | Голов: {data.total_goals} | "
        f"В среднем: {avg:.1f}/матч</i>"
    )
    lines.append("")
    lines.append("🙏 Всем спасибо за игру! До встречи на следующем турнире!")

    return "\n".join(lines)


def _format_personal_results(
    data: TournamentData,
    player_id: int,
    player_team_ids: set[int],
    lang: str = "ru",
) -> str:
    """Персональное сообщение об итогах для одного игрока."""
    gd = data.game_day
    lines = [
        f"🏆 <b>Итоги {gd.display_name}</b>",
        f"📅 {gd.scheduled_at.strftime('%d.%m.%Y')}\n",
    ]

    # ── Личная статистика ──
    personal_goals = data.scorer_stats.get(player_id, {}).get("count", 0)
    personal_cards = data.card_stats.get(player_id, {})
    personal_yellow = personal_cards.get("yellow", 0)
    personal_red = personal_cards.get("red", 0)

    personal_parts = []
    if personal_goals:
        personal_parts.append(f"⚽ {personal_goals} гол(ов)")
    if personal_yellow:
        personal_parts.append(f"🟨 {personal_yellow} ЖК")
    if personal_red:
        personal_parts.append(f"🟥 {personal_red} КК")

    # Место команды
    my_place_text = ""
    for place_num, team in data.place_teams.items():
        if team and team.id in player_team_ids:
            place_icons = {1: "🥇", 2: "🥈", 3: "🥉", 4: "4️⃣"}
            icon = place_icons.get(place_num, f"{place_num}.")
            my_place_text = f"{icon} Твоя команда <b>{team.color_emoji} {team.name}</b> — место #{place_num}"
            break

    if my_place_text:
        lines.append(my_place_text)
    if personal_parts:
        lines.append("👤 Твоя игра: " + " · ".join(personal_parts))
    if my_place_text or personal_parts:
        lines.append("")

    # ── Результаты матчей ──
    lines.append("<b>Результаты матчей:</b>")
    stage_order = ["group", "semifinal", "third_place", "final"]
    stage_labels_ru = {
        "group": "Групповой этап",
        "semifinal": "Полуфинал",
        "third_place": "Матч за 3-е место",
        "final": "Финал",
    }
    grouped: dict[str, list] = {s: [] for s in stage_order}
    for m in data.finished_matches:
        stage = m.match_stage or "group"
        if stage not in grouped:
            grouped[stage] = []
        grouped[stage].append(m)

    for stage in stage_order:
        ms = grouped.get(stage, [])
        if not ms:
            continue
        if stage != "group":
            lines.append(f"<i>{stage_labels_ru.get(stage, stage)}</i>")
        semi_n = 0
        group_n = 0
        for m in ms:
            if stage == "group":
                group_n += 1
                match_num = getattr(m, "match_order", 0) or group_n
                lines.extend(_format_match_line(m, with_scorers=True, label=f"Матч {match_num}"))
            elif stage == "semifinal":
                semi_n += 1
                lines.extend(_format_match_line(m, with_scorers=True, label=f"Полуфинал {semi_n}"))
            else:
                lines.extend(_format_match_line(m, with_scorers=True))
    lines.append("")

    # ── Топ-3 бомбардира ──
    if data.scorer_stats:
        sorted_scorers = sorted(data.scorer_stats.values(), key=lambda x: x["count"], reverse=True)
        medals = ["🥇", "🥈", "🥉"]
        top3 = sorted_scorers[:3]
        scorer_str = " · ".join(
            f"{medals[i]} {s['name']} ({s['count']})"
            for i, s in enumerate(top3)
        )
        lines.append(f"⚽ <b>Бомбардиры:</b> {scorer_str}")

    if data.best_player_name:
        lines.append(f"⭐ <b>Лучший игрок:</b> {data.best_player_name}")

    lines.append("")
    lines.append("🙏 Спасибо за игру! До встречи на следующем турнире!")
    return "\n".join(lines)


# ══════════════════════════════════════════════════════
#  ИТОГИ ТУРНИРА — просмотр и рассылка
# ══════════════════════════════════════════════════════

@router.callback_query(F.data.startswith("gd_tournament_results:"))
async def gd_tournament_results(call: CallbackQuery, session: AsyncSession, bot: Bot):
    if not settings.is_admin(call.from_user.id):
        await call.answer("⛔", show_alert=True)
        return
    await call.answer()

    game_day_id = int(call.data.split(":")[1])
    data = await _gather_tournament_data(session, game_day_id)
    if not data:
        await call.answer("⚠️ Нет завершённых матчей.", show_alert=True)
        return

    # Предпросмотр канального поста для админа (компактный)
    result_text = _format_channel_post(data)

    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(
        text="📢 Разослать итоги всем",
        callback_data=f"gd_results_broadcast:{game_day_id}"
    ))
    builder.row(InlineKeyboardButton(
        text="📋 Пост для канала",
        callback_data=f"gd_to_channel:{game_day_id}"
    ))
    builder.row(InlineKeyboardButton(
        text="🖼 Картинка таблицы",
        callback_data=f"gd_standings_img:{game_day_id}"
    ))
    builder.row(InlineKeyboardButton(
        text="🤖 AI Репортаж",
        callback_data=f"gd_ai_report:{game_day_id}"
    ))
    builder.row(InlineKeyboardButton(
        text="✏️ Исправить данные",
        callback_data=f"adm_edit_matches:{game_day_id}"
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

    game_day_id = int(call.data.split(":")[1])
    data = await _gather_tournament_data(session, game_day_id)
    if not data:
        await call.answer("⚠️ Нет завершённых матчей.", show_alert=True)
        return

    # Загружаем участников + их команды в этом игровом дне
    from app.database.models import TeamPlayer
    att_res = await session.execute(
        select(Attendance)
        .options(selectinload(Attendance.player))
        .where(
            Attendance.game_day_id == game_day_id,
            Attendance.response == AttendanceResponse.YES,
        )
    )
    attendees = att_res.scalars().all()

    # Строим карту player_id → set of team_ids (для этого игрового дня)
    tp_res = await session.execute(
        select(TeamPlayer)
        .join(Team, TeamPlayer.team_id == Team.id)
        .where(Team.game_day_id == game_day_id)
    )
    player_team_map: dict[int, set[int]] = {}
    for tp in tp_res.scalars().all():
        player_team_map.setdefault(tp.player_id, set()).add(tp.team_id)

    sent = 0
    for att in attendees:
        if not att.player or not att.player.telegram_id:
            continue
        try:
            player_team_ids = player_team_map.get(att.player.id, set())
            lang = getattr(att.player, 'language', None) or 'ru'
            msg = _format_personal_results(data, att.player.id, player_team_ids, lang)
            await bot.send_message(att.player.telegram_id, msg)
            sent += 1
            await asyncio.sleep(0.05)
        except Exception as e:
            logger.warning(f"Cannot send results to {att.player.telegram_id}: {e}")

    from app.keyboards.game_day import game_day_action_kb
    await call.message.answer(
        t('results_broadcast_sent', 'ru', count=sent),
        reply_markup=game_day_action_kb(game_day_id)
    )


# ══════════════════════════════════════════════════════
#  РАЗОСЛАТЬ ИТОГИ (I-013) — кнопка из action_kb
# ══════════════════════════════════════════════════════

@router.callback_query(F.data.startswith("gd_post_results:"))
async def gd_post_results(call: CallbackQuery, session: AsyncSession, bot: Bot):
    """Прямая рассылка персональных итогов турнира всем участникам из action_kb."""
    if not settings.is_admin(call.from_user.id):
        await call.answer("⛔", show_alert=True)
        return
    await call.answer("📢 Рассылаю итоги...")

    from app.keyboards.game_day import game_day_action_kb
    from app.database.models import TeamPlayer

    game_day_id = int(call.data.split(":")[1])
    data = await _gather_tournament_data(session, game_day_id)
    if not data:
        await call.answer(t('results_broadcast_empty', 'ru'), show_alert=True)
        return

    att_res = await session.execute(
        select(Attendance)
        .options(selectinload(Attendance.player))
        .where(
            Attendance.game_day_id == game_day_id,
            Attendance.response == AttendanceResponse.YES,
        )
    )
    attendees = att_res.scalars().all()

    # Карта player_id → set of team_ids
    tp_res = await session.execute(
        select(TeamPlayer)
        .join(Team, TeamPlayer.team_id == Team.id)
        .where(Team.game_day_id == game_day_id)
    )
    player_team_map: dict[int, set[int]] = {}
    for tp in tp_res.scalars().all():
        player_team_map.setdefault(tp.player_id, set()).add(tp.team_id)

    sent = 0
    for att in attendees:
        if not att.player or not att.player.telegram_id:
            continue
        try:
            player_team_ids = player_team_map.get(att.player.id, set())
            lang = getattr(att.player, 'language', None) or 'ru'
            msg = _format_personal_results(data, att.player.id, player_team_ids, lang)
            await bot.send_message(att.player.telegram_id, msg)
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

    game_day_id = int(call.data.split(":")[1])
    data = await _gather_tournament_data(session, game_day_id)
    if not data:
        await call.answer("⚠️ Нет завершённых матчей.", show_alert=True)
        return

    post_text = _format_channel_post(data)
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


# ══════════════════════════════════════════════════════
#  РЕДАКТИРОВАНИЕ РЕЗУЛЬТАТОВ МАТЧЕЙ (Task 20)
# ══════════════════════════════════════════════════════

def _edit_match_kb(match_id: int, game_day_id: int, goals: list,
                   is_finished: bool = True) -> "InlineKeyboardMarkup":
    """Клавиатура редактирования матча."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="🔴−1", callback_data=f"adm_score:home:minus:{match_id}"),
        InlineKeyboardButton(text="🔴+1", callback_data=f"adm_score:home:plus:{match_id}"),
        InlineKeyboardButton(text="🔵−1", callback_data=f"adm_score:away:minus:{match_id}"),
        InlineKeyboardButton(text="🔵+1", callback_data=f"adm_score:away:plus:{match_id}"),
    )
    builder.row(
        InlineKeyboardButton(text="➕ Добавить гол", callback_data=f"adm_add_goal:{match_id}"),
    )
    if goals:
        builder.row(
            InlineKeyboardButton(text="🗑 Удалить гол", callback_data=f"adm_del_goal_list:{match_id}"),
        )
    if not is_finished:
        builder.row(
            InlineKeyboardButton(
                text="✅ Завершить матч",
                callback_data=f"adm_finish_match:{match_id}:{game_day_id}"
            )
        )
    builder.row(
        InlineKeyboardButton(text="👥 Состав хозяев", callback_data=f"adm_edit_roster:home:{match_id}:{game_day_id}"),
        InlineKeyboardButton(text="👥 Состав гостей", callback_data=f"adm_edit_roster:away:{match_id}:{game_day_id}"),
    )
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data=f"adm_edit_matches:{game_day_id}"))
    return builder.as_markup()


@router.callback_query(F.data.startswith("adm_finish_match:"))
async def adm_finish_match(call: CallbackQuery, session: AsyncSession):
    """Принудительно завершает матч (переводит в FINISHED)."""
    if not settings.is_admin(call.from_user.id):
        await call.answer("⛔", show_alert=True)
        return

    parts = call.data.split(":")
    match_id = int(parts[1])
    game_day_id = int(parts[2])

    match = await session.get(Match, match_id, options=[
        selectinload(Match.team_home),
        selectinload(Match.team_away),
        selectinload(Match.goals).selectinload(Goal.player),
    ])
    if not match:
        await call.answer("❌ Матч не найден.", show_alert=True)
        return

    match.status = MatchStatus.FINISHED
    await session.commit()
    await call.answer("✅ Матч завершён")

    # Перерисовываем экран редактирования
    home = match.team_home.name
    away = match.team_away.name
    lines = [
        f"✏️ <b>Редактирование матча</b>",
        f"⚽ {home}  <b>{match.score_home}:{match.score_away}</b>  {away}",
        "",
        "Голы:",
    ]
    for i, g in enumerate(match.goals, 1):
        team_name = home if g.team_id == match.team_home_id else away
        own = " (авт.)" if g.goal_type == GoalType.OWN_GOAL else ""
        lines.append(f"  {i}. ⚽ {g.player.name}{own} [{team_name}]")

    await call.message.edit_text(
        "\n".join(lines),
        reply_markup=_edit_match_kb(match_id, game_day_id, match.goals, is_finished=True)
    )


@router.callback_query(F.data.startswith("adm_edit_matches:"))
async def adm_edit_matches(call: CallbackQuery, session: AsyncSession):
    """Список матчей игрового дня для редактирования."""
    if not settings.is_admin(call.from_user.id):
        await call.answer("⛔", show_alert=True)
        return
    await call.answer()

    game_day_id = int(call.data.split(":")[1])
    result = await session.execute(
        select(Match)
        .options(selectinload(Match.team_home), selectinload(Match.team_away))
        .where(Match.game_day_id == game_day_id)
        .order_by(Match.match_order, Match.id)
    )
    matches = result.scalars().all()

    if not matches:
        await call.message.edit_text("⚠️ Матчей нет.")
        return

    builder = InlineKeyboardBuilder()
    for m in matches:
        status = "✅" if m.status == MatchStatus.FINISHED else "⏳"
        builder.row(InlineKeyboardButton(
            text=f"{status} {m.team_home.name} {m.score_home}:{m.score_away} {m.team_away.name}",
            callback_data=f"adm_edit_match:{m.id}:{game_day_id}"
        ))
    builder.row(InlineKeyboardButton(
        text="🔙 К игровому дню",
        callback_data=f"adm_past_detail:{game_day_id}"
    ))

    await call.message.edit_text(
        "✏️ <b>Редактирование матчей</b>\n\nВыбери матч:",
        reply_markup=builder.as_markup()
    )


@router.callback_query(F.data.startswith("adm_edit_match:"))
async def adm_edit_match(call: CallbackQuery, session: AsyncSession):
    """Панель редактирования конкретного матча."""
    if not settings.is_admin(call.from_user.id):
        await call.answer("⛔", show_alert=True)
        return
    await call.answer()

    parts = call.data.split(":")
    match_id = int(parts[1])
    game_day_id = int(parts[2])

    match = await session.get(
        Match, match_id,
        options=[
            selectinload(Match.team_home),
            selectinload(Match.team_away),
            selectinload(Match.goals).selectinload(Goal.player),
        ]
    )
    if not match:
        await call.message.edit_text("❌ Матч не найден.")
        return

    home = match.team_home.name
    away = match.team_away.name
    lines = [
        f"✏️ <b>Редактирование матча</b>\n",
        f"⚽ {home}  <b>{match.score_home}:{match.score_away}</b>  {away}\n",
    ]

    if match.goals:
        lines.append("<b>Голы:</b>")
        for i, g in enumerate(sorted(match.goals, key=lambda x: x.scored_at), 1):
            team_name = home if g.team_id == match.team_home_id else away
            own = " (авт.)" if g.goal_type == GoalType.OWN_GOAL else ""
            lines.append(f"  {i}. ⚽ {g.player.name}{own} [{team_name}]")

    await call.message.edit_text(
        "\n".join(lines),
        reply_markup=_edit_match_kb(match_id, game_day_id, match.goals, is_finished=match.status == MatchStatus.FINISHED)
    )


@router.callback_query(F.data.startswith("adm_score:"))
async def adm_score_adjust(call: CallbackQuery, session: AsyncSession):
    """±1 к счёту. При +1 — спрашивает кто забил."""
    if not settings.is_admin(call.from_user.id):
        await call.answer("⛔", show_alert=True)
        return

    # format: adm_score:home/away:plus/minus:match_id
    parts = call.data.split(":")
    side = parts[1]      # "home" or "away"
    direction = parts[2] # "plus" or "minus"
    match_id = int(parts[3])

    match = await session.get(
        Match, match_id,
        options=[
            selectinload(Match.team_home),
            selectinload(Match.team_away),
            selectinload(Match.goals).selectinload(Goal.player),
        ]
    )
    if not match:
        await call.answer("❌ Матч не найден", show_alert=True)
        return

    game_day_id = match.game_day_id

    # +1 → перенаправляем на выбор игрока (команда уже известна)
    if direction == "plus":
        await call.answer()
        team_id = match.team_home_id if side == "home" else match.team_away_id
        team = match.team_home if side == "home" else match.team_away

        # Загружаем игроков команды
        players_result = await session.execute(
            select(Player)
            .join(TeamPlayer, TeamPlayer.player_id == Player.id)
            .where(TeamPlayer.team_id == team_id)
            .order_by(Player.name)
        )
        players = players_result.scalars().all()
        if not players:
            # Fallback: все записавшиеся на этот день
            players_result = await session.execute(
                select(Player)
                .join(Attendance, Attendance.player_id == Player.id)
                .where(
                    Attendance.game_day_id == game_day_id,
                    Attendance.response == AttendanceResponse.YES,
                )
                .order_by(Player.name)
            )
            players = players_result.scalars().all()

        builder = InlineKeyboardBuilder()
        for p in players:
            builder.button(
                text=p.name,
                callback_data=f"adm_add_goal_save:{match_id}:{team_id}:{p.id}:{game_day_id}"
            )
        builder.adjust(2)
        builder.row(InlineKeyboardButton(
            text="🔙 Назад",
            callback_data=f"adm_edit_match:{match_id}:{game_day_id}"
        ))

        team_emoji = team.color_emoji or ""
        await call.message.edit_text(
            f"➕ <b>Гол — {team_emoji} {team.name}</b>\n\nКто забил?",
            reply_markup=builder.as_markup()
        )
        return

    # -1 → просто уменьшаем счёт
    if side == "home":
        match.score_home = max(0, match.score_home - 1)
    else:
        match.score_away = max(0, match.score_away - 1)
    await session.commit()

    match = await session.get(
        Match, match_id,
        options=[
            selectinload(Match.team_home),
            selectinload(Match.team_away),
            selectinload(Match.goals).selectinload(Goal.player),
        ]
    )
    home = match.team_home.name
    away = match.team_away.name
    lines = [
        f"✏️ <b>Редактирование матча</b>\n",
        f"⚽ {home}  <b>{match.score_home}:{match.score_away}</b>  {away}\n",
    ]
    if match.goals:
        lines.append("<b>Голы:</b>")
        for i, g in enumerate(sorted(match.goals, key=lambda x: x.scored_at), 1):
            team_name = home if g.team_id == match.team_home_id else away
            own = " (авт.)" if g.goal_type == GoalType.OWN_GOAL else ""
            lines.append(f"  {i}. ⚽ {g.player.name}{own} [{team_name}]")

    await call.answer(f"✅ Счёт: {match.score_home}:{match.score_away}")
    await call.message.edit_text(
        "\n".join(lines),
        reply_markup=_edit_match_kb(match_id, game_day_id, match.goals, is_finished=match.status == MatchStatus.FINISHED)
    )


@router.callback_query(F.data.startswith("adm_add_goal:"))
async def adm_add_goal_team(call: CallbackQuery, session: AsyncSession):
    """Добавить гол: выбор команды."""
    if not settings.is_admin(call.from_user.id):
        await call.answer("⛔", show_alert=True)
        return
    await call.answer()

    match_id = int(call.data.split(":")[1])
    match = await session.get(
        Match, match_id,
        options=[selectinload(Match.team_home), selectinload(Match.team_away)]
    )
    if not match:
        return

    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text=f"{match.team_home.name}",
            callback_data=f"adm_add_goal_team:{match_id}:{match.team_home_id}:{match.game_day_id}"
        ),
        InlineKeyboardButton(
            text=f"{match.team_away.name}",
            callback_data=f"adm_add_goal_team:{match_id}:{match.team_away_id}:{match.game_day_id}"
        ),
    )
    builder.row(InlineKeyboardButton(
        text="🔙 Назад",
        callback_data=f"adm_edit_match:{match_id}:{match.game_day_id}"
    ))
    await call.message.edit_text(
        "➕ <b>Добавить гол</b>\n\nКакая команда забила?",
        reply_markup=builder.as_markup()
    )


@router.callback_query(F.data.startswith("adm_add_goal_team:"))
async def adm_add_goal_player(call: CallbackQuery, session: AsyncSession):
    """Добавить гол: выбор игрока."""
    if not settings.is_admin(call.from_user.id):
        await call.answer("⛔", show_alert=True)
        return
    await call.answer()

    parts = call.data.split(":")
    match_id = int(parts[1])
    team_id = int(parts[2])
    game_day_id = int(parts[3])

    # Загружаем игроков команды
    players_result = await session.execute(
        select(Player)
        .join(TeamPlayer, TeamPlayer.player_id == Player.id)
        .where(TeamPlayer.team_id == team_id)
        .order_by(Player.name)
    )
    players = players_result.scalars().all()
    if not players:
        # Fallback: все записавшиеся
        players_result = await session.execute(
            select(Player)
            .join(Attendance, Attendance.player_id == Player.id)
            .where(
                Attendance.game_day_id == game_day_id,
                Attendance.response == AttendanceResponse.YES,
            )
            .order_by(Player.name)
        )
        players = players_result.scalars().all()

    builder = InlineKeyboardBuilder()
    for p in players:
        builder.button(
            text=p.name,
            callback_data=f"adm_add_goal_save:{match_id}:{team_id}:{p.id}:{game_day_id}"
        )
    builder.adjust(2)
    builder.row(InlineKeyboardButton(
        text="🔙 Назад",
        callback_data=f"adm_edit_match:{match_id}:{game_day_id}"
    ))

    team = await session.get(Team, team_id)
    await call.message.edit_text(
        f"➕ <b>Гол — {team.name}</b>\n\nКто забил?",
        reply_markup=builder.as_markup()
    )


@router.callback_query(F.data.startswith("adm_add_goal_save:"))
async def adm_add_goal_save(call: CallbackQuery, session: AsyncSession):
    """Сохранить гол + пересчитать счёт."""
    if not settings.is_admin(call.from_user.id):
        await call.answer("⛔", show_alert=True)
        return

    parts = call.data.split(":")
    match_id = int(parts[1])
    team_id = int(parts[2])
    player_id = int(parts[3])
    game_day_id = int(parts[4])

    match = await session.get(
        Match, match_id,
        options=[selectinload(Match.team_home), selectinload(Match.team_away)]
    )
    scorer = await session.get(Player, player_id)
    if not match or not scorer:
        await call.answer("❌ Ошибка", show_alert=True)
        return

    session.add(Goal(
        match_id=match_id, player_id=player_id, team_id=team_id,
        goal_type=GoalType.GOAL, scored_at=datetime.now(),
    ))
    if team_id == match.team_home_id:
        match.score_home += 1
    else:
        match.score_away += 1
    await session.commit()

    await call.answer(f"✅ Гол добавлен: {scorer.name}")

    # Reload and show edit panel
    match = await session.get(
        Match, match_id,
        options=[
            selectinload(Match.team_home),
            selectinload(Match.team_away),
            selectinload(Match.goals).selectinload(Goal.player),
        ]
    )
    home = match.team_home.name
    away = match.team_away.name
    lines = [
        f"✏️ <b>Редактирование матча</b>\n",
        f"⚽ {home}  <b>{match.score_home}:{match.score_away}</b>  {away}\n",
    ]
    if match.goals:
        lines.append("<b>Голы:</b>")
        for i, g in enumerate(sorted(match.goals, key=lambda x: x.scored_at), 1):
            team_name = home if g.team_id == match.team_home_id else away
            own = " (авт.)" if g.goal_type == GoalType.OWN_GOAL else ""
            lines.append(f"  {i}. ⚽ {g.player.name}{own} [{team_name}]")

    await call.message.edit_text(
        "\n".join(lines),
        reply_markup=_edit_match_kb(match_id, game_day_id, match.goals, is_finished=match.status == MatchStatus.FINISHED)
    )


@router.callback_query(F.data.startswith("adm_del_goal_list:"))
async def adm_del_goal_list(call: CallbackQuery, session: AsyncSession):
    """Показать список голов для удаления."""
    if not settings.is_admin(call.from_user.id):
        await call.answer("⛔", show_alert=True)
        return
    await call.answer()

    match_id = int(call.data.split(":")[1])
    match = await session.get(
        Match, match_id,
        options=[
            selectinload(Match.team_home),
            selectinload(Match.team_away),
            selectinload(Match.goals).selectinload(Goal.player),
        ]
    )
    if not match or not match.goals:
        await call.answer("⚠️ Голов нет", show_alert=True)
        return

    home = match.team_home.name
    away = match.team_away.name
    game_day_id = match.game_day_id

    builder = InlineKeyboardBuilder()
    for g in sorted(match.goals, key=lambda x: x.scored_at):
        team_name = home if g.team_id == match.team_home_id else away
        own = " (авт.)" if g.goal_type == GoalType.OWN_GOAL else ""
        builder.row(InlineKeyboardButton(
            text=f"🗑 {g.player.name}{own} [{team_name}]",
            callback_data=f"adm_del_goal:{g.id}:{match_id}:{game_day_id}"
        ))
    builder.row(InlineKeyboardButton(
        text="🔙 Назад",
        callback_data=f"adm_edit_match:{match_id}:{game_day_id}"
    ))

    await call.message.edit_text(
        f"🗑 <b>Удалить гол</b>\n\n{home} {match.score_home}:{match.score_away} {away}\n\n"
        "Нажми на гол чтобы удалить:",
        reply_markup=builder.as_markup()
    )


@router.callback_query(F.data.startswith("adm_del_goal:"))
async def adm_del_goal(call: CallbackQuery, session: AsyncSession):
    """Удалить конкретный гол и пересчитать счёт."""
    if not settings.is_admin(call.from_user.id):
        await call.answer("⛔", show_alert=True)
        return

    parts = call.data.split(":")
    goal_id = int(parts[1])
    match_id = int(parts[2])
    game_day_id = int(parts[3])

    goal = await session.get(Goal, goal_id)
    match = await session.get(
        Match, match_id,
        options=[
            selectinload(Match.team_home),
            selectinload(Match.team_away),
            selectinload(Match.goals).selectinload(Goal.player),
        ]
    )
    if not goal or not match:
        await call.answer("❌ Ошибка", show_alert=True)
        return

    player_name = goal.player.name if goal.player else "?"
    # Пересчитать счёт
    if goal.team_id == match.team_home_id:
        match.score_home = max(0, match.score_home - 1)
    else:
        match.score_away = max(0, match.score_away - 1)

    await session.delete(goal)
    await session.commit()
    await call.answer(f"🗑 Гол {player_name} удалён")

    # Reload and show edit panel
    match = await session.get(
        Match, match_id,
        options=[
            selectinload(Match.team_home),
            selectinload(Match.team_away),
            selectinload(Match.goals).selectinload(Goal.player),
        ]
    )
    home = match.team_home.name
    away = match.team_away.name
    lines = [
        f"✏️ <b>Редактирование матча</b>\n",
        f"⚽ {home}  <b>{match.score_home}:{match.score_away}</b>  {away}\n",
    ]
    if match.goals:
        lines.append("<b>Голы:</b>")
        for i, g in enumerate(sorted(match.goals, key=lambda x: x.scored_at), 1):
            team_name = home if g.team_id == match.team_home_id else away
            own = " (авт.)" if g.goal_type == GoalType.OWN_GOAL else ""
            lines.append(f"  {i}. ⚽ {g.player.name}{own} [{team_name}]")

    await call.message.edit_text(
        "\n".join(lines),
        reply_markup=_edit_match_kb(match_id, game_day_id, match.goals, is_finished=match.status == MatchStatus.FINISHED)
    )


# ══════════════════════════════════════════════════════
#  РЕДАКТИРОВАНИЕ СОСТАВА КОМАНДЫ В МАТЧЕ
# ══════════════════════════════════════════════════════

def _roster_edit_kb(
    side: str,           # "home" | "away"
    match_id: int,
    game_day_id: int,
    team_id: int,
    current_player_ids: set[int],
    all_players: list[dict],   # [{"id": int, "name": str}, ...]
) -> "InlineKeyboardMarkup":
    """Клавиатура редактирования состава команды."""
    builder = InlineKeyboardBuilder()

    # Текущие игроки с кнопкой удаления
    for p in all_players:
        if p["id"] in current_player_ids:
            builder.row(InlineKeyboardButton(
                text=f"❌ {p['name']}",
                callback_data=f"adm_roster_remove:{side}:{match_id}:{game_day_id}:{team_id}:{p['id']}"
            ))

    # Доступные для добавления (не в этой команде)
    for p in all_players:
        if p["id"] not in current_player_ids:
            builder.row(InlineKeyboardButton(
                text=f"➕ {p['name']}",
                callback_data=f"adm_roster_add:{side}:{match_id}:{game_day_id}:{team_id}:{p['id']}"
            ))

    builder.row(InlineKeyboardButton(
        text="🔙 Назад к матчу",
        callback_data=f"adm_edit_match:{match_id}:{game_day_id}"
    ))
    return builder.as_markup()


async def _show_roster_panel(
    call: CallbackQuery,
    session: AsyncSession,
    side: str,
    match_id: int,
    game_day_id: int,
    team_id: int,
) -> None:
    """Общая функция отображения панели редактирования состава."""
    try:
        from app.database.models import Team as TeamModel

        # Данные матча — скалярный запрос, без ORM-объектов
        match_row = await session.execute(
            select(Match.team_home_id, Match.team_away_id)
            .where(Match.id == match_id)
        )
        match_data = match_row.first()
        if not match_data:
            await call.message.edit_text("❌ Матч не найден.")
            return
        home_team_id, away_team_id = match_data

        opp_team_id = away_team_id if side == "home" else home_team_id

        # Данные команд — скалярные запросы
        team_row = await session.execute(
            select(TeamModel.name, TeamModel.color_emoji).where(TeamModel.id == team_id)
        )
        t = team_row.first()
        team_name = t[0] if t else "?"
        team_emoji = (t[1] or "") if t else ""

        opp_row = await session.execute(
            select(TeamModel.name, TeamModel.color_emoji).where(TeamModel.id == opp_team_id)
        )
        o = opp_row.first()
        opp_name = o[0] if o else "?"
        opp_emoji = (o[1] or "") if o else ""

        # Текущий состав — только player_id
        tp_res = await session.execute(
            select(TeamPlayer.player_id).where(TeamPlayer.team_id == team_id)
        )
        current_player_ids: set[int] = {row[0] for row in tp_res.all()}

        # Пул = записавшиеся на этот день
        att_res = await session.execute(
            select(Player.id, Player.name)
            .join(Attendance, Attendance.player_id == Player.id)
            .where(
                Attendance.game_day_id == game_day_id,
                Attendance.response == AttendanceResponse.YES,
            )
            .order_by(Player.name)
        )
        all_players = [{"id": row[0], "name": row[1]} for row in att_res.all()]

        side_label = "хозяев" if side == "home" else "гостей"
        header = (
            f"👥 <b>Состав {side_label}</b>\n"
            f"{team_emoji} <b>{team_name}</b> vs {opp_emoji} {opp_name}\n\n"
            f"❌ — убрать  |  ➕ — добавить"
        )

        await call.message.edit_text(
            header,
            reply_markup=_roster_edit_kb(
                side, match_id, game_day_id, team_id,
                current_player_ids, all_players
            ),
            parse_mode="HTML",
        )
    except Exception as e:
        logger.error(f"_show_roster_panel error: {e}", exc_info=True)
        await call.message.edit_text(f"❌ Ошибка: {type(e).__name__}: {e}")


@router.callback_query(F.data.startswith("adm_edit_roster:"))
async def adm_edit_roster(call: CallbackQuery, session: AsyncSession):
    """Открывает панель редактирования состава команды."""
    if not settings.is_admin(call.from_user.id):
        await call.answer("⛔", show_alert=True)
        return
    await call.answer()

    # adm_edit_roster:{side}:{match_id}:{game_day_id}
    _, side, match_id_s, game_day_id_s = call.data.split(":")
    match_id = int(match_id_s)
    game_day_id = int(game_day_id_s)

    row = await session.execute(
        select(Match.team_home_id, Match.team_away_id).where(Match.id == match_id)
    )
    match_data = row.first()
    if not match_data:
        await call.message.edit_text("❌ Матч не найден.")
        return

    team_id = match_data[0] if side == "home" else match_data[1]
    await _show_roster_panel(call, session, side, match_id, game_day_id, team_id)


@router.callback_query(F.data.startswith("adm_roster_remove:"))
async def adm_roster_remove(call: CallbackQuery, session: AsyncSession):
    """Удаляет игрока из состава команды."""
    if not settings.is_admin(call.from_user.id):
        await call.answer("⛔", show_alert=True)
        return

    # adm_roster_remove:{side}:{match_id}:{game_day_id}:{team_id}:{player_id}
    parts = call.data.split(":")
    side = parts[1]
    match_id = int(parts[2])
    game_day_id = int(parts[3])
    team_id = int(parts[4])
    player_id = int(parts[5])

    tp_res = await session.execute(
        select(TeamPlayer).where(
            TeamPlayer.team_id == team_id,
            TeamPlayer.player_id == player_id,
        )
    )
    tp = tp_res.scalar_one_or_none()
    if tp:
        await session.delete(tp)
        await session.commit()
        await call.answer("✅ Игрок удалён из состава")
    else:
        await call.answer("⚠️ Игрок не найден в составе")

    await _show_roster_panel(call, session, side, match_id, game_day_id, team_id)


@router.callback_query(F.data.startswith("adm_roster_add:"))
async def adm_roster_add(call: CallbackQuery, session: AsyncSession):
    """Добавляет игрока в состав команды."""
    if not settings.is_admin(call.from_user.id):
        await call.answer("⛔", show_alert=True)
        return

    # adm_roster_add:{side}:{match_id}:{game_day_id}:{team_id}:{player_id}
    parts = call.data.split(":")
    side = parts[1]
    match_id = int(parts[2])
    game_day_id = int(parts[3])
    team_id = int(parts[4])
    player_id = int(parts[5])

    existing = await session.execute(
        select(TeamPlayer).where(
            TeamPlayer.team_id == team_id,
            TeamPlayer.player_id == player_id,
        )
    )
    if existing.scalar_one_or_none():
        await call.answer("⚠️ Игрок уже в составе")
    else:
        session.add(TeamPlayer(team_id=team_id, player_id=player_id))
        await session.commit()
        await call.answer("✅ Игрок добавлен в состав")

    await _show_roster_panel(call, session, side, match_id, game_day_id, team_id)


# ══════════════════════════════════════════════════════
#  AI РЕПОРТАЖ ТУРНИРА (Claude API)
# ══════════════════════════════════════════════════════

def _build_report_prompt(data: "TournamentData") -> str:
    """Формирует промпт для Claude на основе данных турнира."""
    from app.database.models import GoalType

    gd = data.game_day
    date_str = gd.scheduled_at.strftime("%d.%m.%Y")
    lines = [
        f"Напиши живой, увлекательный репортаж об итогах любительского футбольного турнира.",
        f"Пиши на русском языке. Стиль — спортивный журналист, эмоционально, с юмором, но по делу.",
        f"Используй эмодзи умеренно. Объём — 300–500 слов.",
        f"",
        f"=== ДАННЫЕ ТУРНИРА ===",
        f"Название: {gd.display_name}",
        f"Дата: {date_str}",
        f"Место: {gd.location}",
        f"Всего матчей: {data.total_matches}",
        f"Всего голов: {data.total_goals}",
        f"",
    ]

    # Итоговые места
    if data.place_teams:
        lines.append("ИТОГОВЫЕ МЕСТА:")
        medals = {1: "🥇 1 место", 2: "🥈 2 место", 3: "🥉 3 место", 4: "4 место"}
        for place, team in sorted(data.place_teams.items()):
            if team:
                roster = data.team_rosters.get(team.id, [])
                roster_str = f" (игроки: {', '.join(roster)})" if roster else ""
                lines.append(f"  {medals.get(place, f'{place} место')}: {team.name}{roster_str}")
        lines.append("")

    # Матчи по стадиям
    group_matches = [m for m in data.finished_matches if (m.match_stage or "group") == "group"]
    playoff_matches = [m for m in data.finished_matches if (m.match_stage or "group") != "group"]

    if group_matches:
        lines.append("ГРУППОВОЙ ЭТАП:")
        for i, m in enumerate(group_matches, 1):
            goal_details = []
            for g in sorted(m.goals, key=lambda x: x.scored_at):
                if g.player:
                    own = " (авт.)" if g.goal_type == GoalType.OWN_GOAL else ""
                    team_name = m.team_home.name if g.team_id == m.team_home_id else m.team_away.name
                    goal_details.append(f"{g.player.name}{own} ({team_name})")
            goals_str = f" — голы: {', '.join(goal_details)}" if goal_details else ""
            lines.append(
                f"  Матч {i}: {m.team_home.name} {m.score_home}:{m.score_away} {m.team_away.name}{goals_str}"
            )
        lines.append("")

    stage_labels = {"semifinal": "ПОЛУФИНАЛ", "third_place": "МАТЧ ЗА 3-Е МЕСТО", "final": "ФИНАЛ"}
    for m in playoff_matches:
        label = stage_labels.get(m.match_stage or "", "МАТЧ")
        goal_details = []
        for g in sorted(m.goals, key=lambda x: x.scored_at):
            if g.player:
                own = " (авт.)" if g.goal_type == GoalType.OWN_GOAL else ""
                team_name = m.team_home.name if g.team_id == m.team_home_id else m.team_away.name
                goal_details.append(f"{g.player.name}{own} ({team_name})")
        goals_str = f" — голы: {', '.join(goal_details)}" if goal_details else ""
        lines.append(
            f"{label}: {m.team_home.name} {m.score_home}:{m.score_away} {m.team_away.name}{goals_str}"
        )
    if playoff_matches:
        lines.append("")

    # Бомбардиры
    if data.scorer_stats:
        top = sorted(data.scorer_stats.values(), key=lambda x: x["count"], reverse=True)[:5]
        lines.append("БОМБАРДИРЫ:")
        for s in top:
            lines.append(f"  {s['name']} — {s['count']} гол(ов)")
        lines.append("")

    # Лучший игрок
    if data.best_player_name:
        lines.append(f"ЛУЧШИЙ ИГРОК ПО ГОЛОСОВАНИЮ: {data.best_player_name}")
        lines.append("")

    # Вратари
    if data.gk_stats:
        lines.append("ВРАТАРИ:")
        for tid, gk in data.gk_stats.items():
            if gk.get("gk_name"):
                lines.append(
                    f"  {gk['gk_name']} ({gk['team_name']}) — {gk['saves']} сейвов, "
                    f"пропустил {gk['goals_conceded']}"
                )
        lines.append("")

    lines.append("Напиши репортаж, опираясь только на эти данные. Не придумывай детали которых нет.")
    return "\n".join(lines)


async def _call_claude_api(prompt: str, api_key: str) -> str:
    """Асинхронный вызов Claude API через официальный SDK."""
    import anthropic
    client = anthropic.AsyncAnthropic(api_key=api_key)
    message = await client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text


@router.callback_query(F.data.startswith("gd_ai_report:"))
async def gd_ai_report(call: CallbackQuery, session: AsyncSession):
    """Генерирует AI-репортаж турнира через Claude API."""
    if not settings.is_admin(call.from_user.id):
        await call.answer("⛔", show_alert=True)
        return

    if not settings.ANTHROPIC_API_KEY:
        await call.answer("⚠️ ANTHROPIC_API_KEY не задан в настройках.", show_alert=True)
        return

    await call.answer("⏳ Генерирую репортаж...")
    await call.message.edit_text("🤖 <b>Генерирую репортаж...</b>\n\n⏳ Обычно занимает 5–10 секунд.")

    game_day_id = int(call.data.split(":")[1])
    data = await _gather_tournament_data(session, game_day_id)
    if not data:
        await call.message.edit_text("⚠️ Нет завершённых матчей.")
        return

    try:
        prompt = _build_report_prompt(data)
        report_text = await _call_claude_api(prompt, settings.ANTHROPIC_API_KEY)
    except Exception as e:
        logger.error(f"AI report error: {e}", exc_info=True)
        await call.message.edit_text(
            f"❌ Ошибка при генерации репортажа:\n<code>{type(e).__name__}: {e}</code>\n\n"
            "Проверь ANTHROPIC_API_KEY в переменных окружения Railway."
        )
        return

    # Показываем репортаж с кнопками
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(
        text="🔄 Сгенерировать заново",
        callback_data=f"gd_ai_report:{game_day_id}"
    ))
    builder.row(InlineKeyboardButton(
        text="🔙 К итогам",
        callback_data=f"gd_tournament_results:{game_day_id}"
    ))

    # Telegram ограничение 4096 символов
    header = f"🤖 <b>AI Репортаж — {data.game_day.display_name}</b>\n\n"
    full_text = header + report_text
    if len(full_text) > 4096:
        full_text = full_text[:4090] + "…"

    await call.message.edit_text(full_text, reply_markup=builder.as_markup())


# ══════════════════════════════════════════════════════
#  ИГРОКИ-БОТЫ (I-059)
# ══════════════════════════════════════════════════════

@router.callback_query(F.data.startswith("gd_bots:"))
async def gd_bots_menu(call: CallbackQuery, session: AsyncSession):
    """Меню управления бот-игроками для игрового дня."""
    if not settings.is_admin(call.from_user.id):
        await call.answer("⛔", show_alert=True)
        return
    await call.answer()

    game_day_id = int(call.data.split(":")[1])

    # Текущие команды и их составы
    teams_res = await session.execute(
        select(Team)
        .options(selectinload(Team.players).selectinload(TeamPlayer.player))
        .where(Team.game_day_id == game_day_id)
    )
    teams = teams_res.scalars().all()

    if not teams:
        await call.message.edit_text(
            "⚠️ Сначала создай команды через «🎲 Авто-команды», «✋ Вручную» или «🎯 Basket-баланс».",
            reply_markup=InlineKeyboardBuilder().row(
                InlineKeyboardButton(text="🔙 Назад", callback_data=f"gd_players:{game_day_id}")
            ).as_markup()
        )
        return

    lines = [f"👻 <b>Боты — Турнир #{game_day_id}</b>\n"]
    for team in teams:
        bots = [tp.player for tp in team.players if tp.player.is_bot]
        real = [tp.player for tp in team.players if not tp.player.is_bot]
        bot_names = ", ".join(p.name for p in bots) if bots else "—"
        lines.append(f"{team.color_emoji} <b>{team.name}</b>: {len(real)} игр. + {len(bots)} ботов ({bot_names})")

    lines.append("\nВыбери команду, в которую добавить бота:")

    builder = InlineKeyboardBuilder()
    for team in teams:
        builder.row(InlineKeyboardButton(
            text=f"{team.color_emoji} {team.name}",
            callback_data=f"gd_bot_add:{game_day_id}:{team.id}"
        ))

    # Кнопка удалить всех ботов если есть хоть один
    all_bots = [tp for t in teams for tp in t.players if tp.player.is_bot]
    if all_bots:
        builder.row(InlineKeyboardButton(
            text="🗑 Удалить всех ботов",
            callback_data=f"gd_bot_clear:{game_day_id}"
        ))

    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data=f"gd_players:{game_day_id}"))
    await call.message.edit_text("\n".join(lines), reply_markup=builder.as_markup(), parse_mode="HTML")


@router.callback_query(F.data.startswith("gd_bot_add:"))
async def gd_bot_add(call: CallbackQuery, session: AsyncSession):
    """Добавить одного бота в выбранную команду."""
    if not settings.is_admin(call.from_user.id):
        await call.answer("⛔", show_alert=True)
        return
    await call.answer("⏳ Создаю бота...")

    parts = call.data.split(":")
    game_day_id = int(parts[1])
    team_id = int(parts[2])

    team = await session.get(Team, team_id)
    if not team:
        await call.answer("❌ Команда не найдена.", show_alert=True)
        return

    # Посчитать сколько ботов уже в этой команде
    bots_res = await session.execute(
        select(TeamPlayer)
        .join(Player, Player.id == TeamPlayer.player_id)
        .where(TeamPlayer.team_id == team_id, Player.is_bot == True)
    )
    existing_bots = bots_res.scalars().all()
    bot_num = len(existing_bots) + 1
    bot_name = f"👻 Бот {bot_num} ({team.name})"

    # Создать бот-игрока с fake telegram_id (отрицательный уникальный)
    import time
    fake_tg_id = -(int(time.time() * 1000) % 2_000_000_000)
    bot_player = Player(
        telegram_id=fake_tg_id,
        name=bot_name,
        position=Position.MIDFIELDER,
        rating=5.0,
        rating_provisional=False,
        is_bot=True,
        status=PlayerStatus.ACTIVE,
        league_id=None,
    )
    session.add(bot_player)
    await session.flush()

    session.add(TeamPlayer(team_id=team_id, player_id=bot_player.id))
    await session.commit()

    await call.answer(f"✅ {bot_name} добавлен в команду {team.name}", show_alert=True)

    # Перезагрузить меню
    fake_call_data = f"gd_bots:{game_day_id}"
    call.data = fake_call_data
    await gd_bots_menu(call, session)


@router.callback_query(F.data.startswith("gd_bot_clear:"))
async def gd_bot_clear(call: CallbackQuery, session: AsyncSession):
    """Удалить всех бот-игроков из всех команд этого игрового дня."""
    if not settings.is_admin(call.from_user.id):
        await call.answer("⛔", show_alert=True)
        return
    await call.answer("⏳ Удаляю ботов...")

    game_day_id = int(call.data.split(":")[1])

    # Найти всех ботов через команды этого игрового дня
    bots_res = await session.execute(
        select(Player)
        .join(TeamPlayer, TeamPlayer.player_id == Player.id)
        .join(Team, Team.id == TeamPlayer.team_id)
        .where(Team.game_day_id == game_day_id, Player.is_bot == True)
    )
    bots = bots_res.scalars().all()

    for bot in bots:
        await session.delete(bot)
    await session.commit()

    await call.answer(f"🗑 Удалено ботов: {len(bots)}", show_alert=True)
    call.data = f"gd_bots:{game_day_id}"
    await gd_bots_menu(call, session)

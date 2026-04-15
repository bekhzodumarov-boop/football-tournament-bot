from aiogram import Router
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database.models import Player, POSITION_LABELS
from app.keyboards.main_menu import main_menu_kb, admin_menu_kb

router = Router()


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext):
    """Отмена любого активного действия / выход из FSM"""
    current = await state.get_state()
    if current is None:
        await message.answer("Нечего отменять. Ты в главном меню /start")
        return
    await state.clear()
    await message.answer(
        "❌ Действие отменено.\n\n"
        "Используй /start для главного меню или /admin для Админки."
    )


@router.message(CommandStart())
async def cmd_start(message: Message, player: Player | None, state: FSMContext):
    await state.clear()  # Сбросить любой активный FSM
    if player is None:
        await message.answer(
            "👋 Привет! Добро пожаловать в <b>Football Manager Bot</b>!\n\n"
            "Ты ещё не зарегистрирован. Давай исправим это!\n\n"
            "Нажми /register чтобы создать профиль игрока."
        )
        return

    await message.answer(
        f"⚽ Привет, <b>{player.name}</b>!\n\n"
        f"📍 Позиция: {POSITION_LABELS[player.position]}\n"
        f"⭐ Рейтинг: {player.rating:.1f}"
        + (" <i>(провизорный)</i>" if player.rating_provisional else "")
        + f"\n💰 Баланс: {player.balance} руб.\n\n"
        f"Выбери действие:",
        reply_markup=main_menu_kb()
    )


@router.message(Command("admin"))
async def cmd_admin(message: Message, player: Player | None, state: FSMContext):
    await state.clear()  # Сбросить любой активный FSM
    if not settings.is_admin(message.from_user.id):
        await message.answer("⛔ У тебя нет доступа к Админке.")
        return

    await message.answer(
        "🔧 <b>Панель администратора</b>\n\n"
        "Выбери действие:",
        reply_markup=admin_menu_kb()
    )


@router.callback_query(lambda c: c.data == "main_menu")
async def cb_main_menu(call: CallbackQuery, player: Player | None):
    await call.answer()
    if player is None:
        await call.message.answer("Ты не зарегистрирован. Нажми /register")
        return

    await call.message.edit_text(
        f"⚽ Главное меню, <b>{player.name}</b>:",
        reply_markup=main_menu_kb()
    )


@router.callback_query(lambda c: c.data == "my_profile")
async def cb_my_profile(call: CallbackQuery, player: Player | None):
    await call.answer()
    if not player:
        await call.message.answer("Ты не зарегистрирован. Нажми /register")
        return

    from app.database.models import POSITION_LABELS
    pos_label = POSITION_LABELS.get(player.position, player.position)

    text = (
        f"👤 <b>Профиль игрока</b>\n\n"
        f"Имя: <b>{player.name}</b>\n"
        f"Позиция: {pos_label}\n"
        f"⭐ Рейтинг: <b>{player.rating:.1f}</b>"
        + (" <i>(провизорный)</i>" if player.rating_provisional else "")
        + f"\n✅ Посещаемость: <b>{player.reliability_pct:.0f}%</b>\n"
        f"⚽ Игр: <b>{player.games_played}</b>\n"
        f"💰 Баланс: <b>{player.balance} руб.</b>"
    )
    await call.message.edit_text(text, reply_markup=main_menu_kb())


@router.callback_query(lambda c: c.data == "players_list")
async def cb_players_list(call: CallbackQuery, session: AsyncSession):
    await call.answer()
    from sqlalchemy import select
    from app.database.models import PlayerStatus, POSITION_LABELS

    result = await session.execute(
        select(Player)
        .where(Player.status == PlayerStatus.ACTIVE)
        .order_by(Player.rating.desc())
    )
    players = result.scalars().all()

    if not players:
        await call.message.edit_text("👥 Игроков пока нет.", reply_markup=main_menu_kb())
        return

    lines = ["👥 <b>Все игроки</b>\n"]
    for i, p in enumerate(players, 1):
        pos = POSITION_LABELS.get(p.position, p.position)
        provisional = " <i>(пров.)</i>" if p.rating_provisional else ""
        lines.append(f"{i}. <b>{p.name}</b> — {pos}, ⭐{p.rating:.1f}{provisional}")

    await call.message.edit_text("\n".join(lines), reply_markup=main_menu_kb())


@router.callback_query(lambda c: c.data == "match_results")
async def cb_match_results(call: CallbackQuery, session: AsyncSession):
    await call.answer()
    from sqlalchemy import select
    from app.database.models import Match, MatchStatus, Goal, Card, CardType, GoalType

    result = await session.execute(
        select(Match)
        .where(Match.status == MatchStatus.FINISHED)
        .order_by(Match.finished_at.desc())
        .limit(10)
    )
    matches = result.scalars().all()

    if not matches:
        await call.message.edit_text("📋 Сыгранных матчей пока нет.", reply_markup=main_menu_kb())
        return

    lines = ["📋 <b>Результаты игр</b>\n"]
    for match in matches:
        home = match.team_home.name
        away = match.team_away.name
        date = match.finished_at.strftime("%d.%m") if match.finished_at else "—"
        lines.append(f"\n⚽ <b>{home} {match.score_home}:{match.score_away} {away}</b> ({date})")

        # Голы
        for goal in match.goals:
            marker = "🥅" if goal.goal_type == GoalType.OWN_GOAL else "⚽"
            team_name = match.team_home.name if goal.team_id == match.team_home_id else match.team_away.name
            own = " (авт.)" if goal.goal_type == GoalType.OWN_GOAL else ""
            lines.append(f"  {marker} {goal.player.name}{own} [{team_name}]")

        # Карточки
        for card in match.cards:
            emoji = "🟡" if card.card_type == CardType.YELLOW else "🔴"
            team_name = match.team_home.name if card.team_id == match.team_home_id else match.team_away.name
            lines.append(f"  {emoji} {card.player.name} [{team_name}]")

    await call.message.edit_text("\n".join(lines), reply_markup=main_menu_kb())


@router.callback_query(lambda c: c.data == "my_stats")
async def cb_my_stats(call: CallbackQuery, player: Player | None, session: AsyncSession):
    await call.answer()
    if not player:
        await call.message.answer("Ты не зарегистрирован.")
        return

    from sqlalchemy import select, func
    from app.database.models import Goal, Attendance, AttendanceResponse

    # Голы
    goals_result = await session.execute(
        select(func.count(Goal.id)).where(Goal.player_id == player.id)
    )
    total_goals = goals_result.scalar() or 0

    text = (
        f"📊 <b>Статистика — {player.name}</b>\n\n"
        f"⚽ Игр сыграно: <b>{player.games_played}</b>\n"
        f"🥅 Голов: <b>{total_goals}</b>\n"
        f"✅ Надёжность: <b>{player.reliability_pct:.0f}%</b>\n"
        f"⭐ Рейтинг: <b>{player.rating:.1f}</b>\n"
    )
    await call.message.edit_text(text, reply_markup=main_menu_kb())

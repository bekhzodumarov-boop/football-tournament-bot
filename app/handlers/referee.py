"""
Обработчики для судьи (referee).
Доступ: игроки с is_referee=True ИЛИ администраторы.

Функции:
  - /referee  → выбор игрового дня
  - Новый матч: ввести названия команд + длительность
  - Управление матчем: старт таймера, голы, жёлтые/красные карточки, завершение
  - При истечении времени — уведомление судье (+ всем игрокам при желании)
"""
from datetime import datetime, timedelta

from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database.models import (
    GameDay, GameDayStatus,
    Attendance, AttendanceResponse,
    Team, Match, MatchStatus,
    Goal, GoalType,
    Card, CardType,
    Player,
)
from app.keyboards.referee import (
    referee_gamedays_kb, referee_gd_kb, referee_match_kb,
    select_team_kb, select_player_kb, confirm_finish_kb,
)
from app.scheduler import scheduler

router = Router()


# ─────────────────────────────────────────────
#  FSM
# ─────────────────────────────────────────────

class RefereeMatchFSM(StatesGroup):
    waiting_team1 = State()
    waiting_team2 = State()
    waiting_duration = State()


# ─────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────

def _is_referee(user_id: int, player: Player | None) -> bool:
    return settings.is_admin(user_id) or (player is not None and player.is_referee)


async def _get_attendees(session: AsyncSession, game_day_id: int) -> list[Player]:
    """Все игроки, записавшиеся на игровой день."""
    result = await session.execute(
        select(Player)
        .join(Attendance, Attendance.player_id == Player.id)
        .where(
            Attendance.game_day_id == game_day_id,
            Attendance.response == AttendanceResponse.YES,
        )
        .order_by(Player.name)
    )
    return result.scalars().all()


def _match_panel_text(match: Match) -> str:
    """Текст для панели управления матчем."""
    home = match.team_home.name
    away = match.team_away.name

    # Таймер
    if match.status == MatchStatus.IN_PROGRESS and match.started_at:
        elapsed = datetime.now() - match.started_at
        elapsed_min = int(elapsed.total_seconds() // 60)
        elapsed_sec = int(elapsed.total_seconds() % 60)
        timer_line = f"⏱ Идёт {elapsed_min}:{elapsed_sec:02d}"
    elif match.status == MatchStatus.FINISHED:
        timer_line = "✅ Матч завершён"
    else:
        timer_line = "⏱ Таймер не запущен"

    # Голы
    goals_lines = []
    for g in sorted(match.goals, key=lambda x: x.scored_at):
        own = " (авт.)" if g.goal_type == GoalType.OWN_GOAL else ""
        t = match.team_home.name if g.team_id == match.team_home_id else match.team_away.name
        goals_lines.append(f"  🥅 {g.player.name}{own} [{t}]")

    # Карточки
    card_lines = []
    for c in sorted(match.cards, key=lambda x: x.issued_at):
        emoji = "🟡" if c.card_type == CardType.YELLOW else "🔴"
        t = match.team_home.name if c.team_id == match.team_home_id else match.team_away.name
        card_lines.append(f"  {emoji} {c.player.name} [{t}]")

    text = (
        f"⚽ <b>{home}  {match.score_home} : {match.score_away}  {away}</b>\n"
        f"{timer_line}\n"
    )
    if goals_lines:
        text += "\n<b>Голы:</b>\n" + "\n".join(goals_lines) + "\n"
    if card_lines:
        text += "\n<b>Карточки:</b>\n" + "\n".join(card_lines) + "\n"

    return text


# ─────────────────────────────────────────────
#  /referee — вход
# ─────────────────────────────────────────────

@router.message(Command("referee"))
async def cmd_referee(message: Message, session: AsyncSession, player: Player | None, state: FSMContext):
    await state.clear()
    if not _is_referee(message.from_user.id, player):
        await message.answer("⛔ Нет доступа. Команда для судей.")
        return

    result = await session.execute(
        select(GameDay)
        .where(GameDay.status.in_([GameDayStatus.ANNOUNCED, GameDayStatus.CLOSED, GameDayStatus.IN_PROGRESS]))
        .order_by(GameDay.scheduled_at)
    )
    game_days = result.scalars().all()

    if not game_days:
        await message.answer("📅 Нет активных игровых дней.")
        return

    await message.answer(
        "🦺 <b>Панель судьи</b>\n\nВыбери игровой день:",
        reply_markup=referee_gamedays_kb(game_days)
    )


# ─────────────────────────────────────────────
#  Выбор игрового дня → список матчей
# ─────────────────────────────────────────────

@router.callback_query(F.data.startswith("ref_gd:"))
async def ref_select_gameday(call: CallbackQuery, session: AsyncSession, player: Player | None):
    if not _is_referee(call.from_user.id, player):
        await call.answer("⛔", show_alert=True)
        return
    await call.answer()

    game_day_id = int(call.data.split(":")[1])
    game_day = await session.get(GameDay, game_day_id)
    if not game_day:
        await call.message.edit_text("❌ Игровой день не найден.")
        return

    result = await session.execute(
        select(Match).where(Match.game_day_id == game_day_id).order_by(Match.id)
    )
    matches = result.scalars().all()

    await call.message.edit_text(
        f"🦺 <b>Игровой день {game_day.scheduled_at.strftime('%d.%m.%Y %H:%M')}</b>\n"
        f"📍 {game_day.location}\n\n"
        "Выбери матч или создай новый:",
        reply_markup=referee_gd_kb(game_day_id, matches)
    )


# ─────────────────────────────────────────────
#  Создание нового матча (FSM)
# ─────────────────────────────────────────────

@router.callback_query(F.data.startswith("ref_new_match:"))
async def ref_new_match_start(call: CallbackQuery, state: FSMContext, player: Player | None):
    if not _is_referee(call.from_user.id, player):
        await call.answer("⛔", show_alert=True)
        return
    await call.answer()

    game_day_id = int(call.data.split(":")[1])
    await state.update_data(game_day_id=game_day_id)
    await state.set_state(RefereeMatchFSM.waiting_team1)
    await call.message.edit_text(
        "➕ <b>Новый матч</b>\n\n"
        "Введи название <b>Команды 1</b>:\n"
        "<i>Например: Красные, Команда А, и т.д.</i>"
    )


@router.message(RefereeMatchFSM.waiting_team1)
async def ref_team1(message: Message, state: FSMContext):
    name = message.text.strip()
    if not name:
        await message.answer("❌ Название не может быть пустым.")
        return
    await state.update_data(team1_name=name)
    await state.set_state(RefereeMatchFSM.waiting_team2)
    await message.answer(
        f"✅ Команда 1: <b>{name}</b>\n\n"
        "Введи название <b>Команды 2</b>:"
    )


@router.message(RefereeMatchFSM.waiting_team2)
async def ref_team2(message: Message, state: FSMContext):
    name = message.text.strip()
    if not name:
        await message.answer("❌ Название не может быть пустым.")
        return
    await state.update_data(team2_name=name)
    await state.set_state(RefereeMatchFSM.waiting_duration)
    await message.answer(
        f"✅ Команда 2: <b>{name}</b>\n\n"
        "Длительность матча (в минутах)?\n"
        "<i>Введи число, например: 20</i>"
    )


@router.message(RefereeMatchFSM.waiting_duration)
async def ref_duration(message: Message, state: FSMContext, session: AsyncSession):
    try:
        duration = int(message.text.strip())
        if duration < 1 or duration > 120:
            raise ValueError
    except ValueError:
        await message.answer("❌ Введи число от 1 до 120:")
        return

    data = await state.get_data()
    await state.clear()

    game_day_id = data["game_day_id"]
    team1_name = data["team1_name"]
    team2_name = data["team2_name"]

    # Создать команды
    team1 = Team(game_day_id=game_day_id, name=team1_name, color_emoji="🔴")
    team2 = Team(game_day_id=game_day_id, name=team2_name, color_emoji="🔵")
    session.add_all([team1, team2])
    await session.flush()  # получить id до commit

    # Создать матч
    match = Match(
        game_day_id=game_day_id,
        team_home_id=team1.id,
        team_away_id=team2.id,
        match_format="time",
        status=MatchStatus.SCHEDULED,
    )
    # Сохранить длительность — используем поле match_duration через game_day (упрощённо)
    # Вместо этого сохраняем в notes game_day или добавляем атрибут напрямую
    # Проще: добавим duration как нестандартный атрибут через словарь состояния при старте
    session.add(match)
    await session.commit()
    await session.refresh(match)
    # Сохраняем duration в памяти (добавим в FSM-независимое хранилище при старте)

    await message.answer(
        f"✅ <b>Матч создан!</b>\n\n"
        f"⚽ {team1_name} vs {team2_name}\n"
        f"⏱ Длительность: {duration} мин.\n\n"
        "Используй кнопки для управления матчем:",
        reply_markup=referee_match_kb(match.id, is_started=False, is_finished=False)
    )

    # Сохранить длительность в scheduler-data (используем id матча как ключ)
    from app import scheduler as sch_module
    if not hasattr(sch_module, '_match_durations'):
        sch_module._match_durations = {}
    sch_module._match_durations[match.id] = duration


# ─────────────────────────────────────────────
#  Панель матча
# ─────────────────────────────────────────────

@router.callback_query(F.data.startswith("ref_match:"))
async def ref_match_panel(call: CallbackQuery, session: AsyncSession, player: Player | None):
    if not _is_referee(call.from_user.id, player):
        await call.answer("⛔", show_alert=True)
        return
    await call.answer()

    match_id = int(call.data.split(":")[1])
    match = await session.get(Match, match_id)
    if not match:
        await call.message.edit_text("❌ Матч не найден.")
        return

    is_started = match.status == MatchStatus.IN_PROGRESS
    is_finished = match.status == MatchStatus.FINISHED

    await call.message.edit_text(
        _match_panel_text(match),
        reply_markup=referee_match_kb(match_id, is_started, is_finished)
    )


# ─────────────────────────────────────────────
#  Старт таймера
# ─────────────────────────────────────────────

@router.callback_query(F.data.startswith("ref_start:"))
async def ref_start_timer(call: CallbackQuery, session: AsyncSession,
                          player: Player | None, bot: Bot):
    if not _is_referee(call.from_user.id, player):
        await call.answer("⛔", show_alert=True)
        return
    await call.answer("▶️ Таймер запущен!", show_alert=True)

    match_id = int(call.data.split(":")[1])
    match = await session.get(Match, match_id)
    if not match:
        return

    match.started_at = datetime.now()
    match.status = MatchStatus.IN_PROGRESS
    await session.commit()

    # Получить длительность
    from app import scheduler as sch_module
    durations = getattr(sch_module, '_match_durations', {})
    duration_min = durations.get(match_id, 20)  # default 20 мин

    finish_time = match.started_at + timedelta(minutes=duration_min)
    chat_id = call.message.chat.id

    # Запланировать уведомление об окончании
    scheduler.add_job(
        _notify_time_up,
        trigger="date",
        run_date=finish_time,
        args=[bot, chat_id, match_id, match.team_home.name, match.team_away.name],
        id=f"timer_{match_id}",
        replace_existing=True,
    )

    await call.message.edit_text(
        _match_panel_text(match) +
        f"\n⏱ <b>Таймер запущен!</b> Финиш через {duration_min} мин.",
        reply_markup=referee_match_kb(match_id, is_started=True, is_finished=False)
    )


async def _notify_time_up(bot: Bot, chat_id: int, match_id: int,
                          home_name: str, away_name: str):
    """Вызывается APScheduler когда время матча вышло."""
    text = (
        "🔔🔔🔔 <b>ВРЕМЯ ВЫШЛО!</b> 🔔🔔🔔\n\n"
        f"⚽ {home_name} vs {away_name}\n\n"
        "⏱ Регулярное время истекло.\n"
        "Зафиксируй финальный счёт в боте."
    )
    try:
        await bot.send_message(chat_id, text)
    except Exception:
        pass


# ─────────────────────────────────────────────
#  Статус таймера
# ─────────────────────────────────────────────

@router.callback_query(F.data.startswith("ref_timer:"))
async def ref_check_timer(call: CallbackQuery, session: AsyncSession, player: Player | None):
    if not _is_referee(call.from_user.id, player):
        await call.answer("⛔", show_alert=True)
        return
    await call.answer()

    match_id = int(call.data.split(":")[1])
    match = await session.get(Match, match_id)
    if not match:
        return

    from app import scheduler as sch_module
    durations = getattr(sch_module, '_match_durations', {})
    duration_min = durations.get(match_id, 20)

    elapsed = datetime.now() - match.started_at if match.started_at else timedelta()
    remaining = timedelta(minutes=duration_min) - elapsed
    if remaining.total_seconds() < 0:
        remaining = timedelta(0)
    rem_min = int(remaining.total_seconds() // 60)
    rem_sec = int(remaining.total_seconds() % 60)

    await call.message.edit_text(
        _match_panel_text(match) +
        f"\n⏱ Осталось: <b>{rem_min}:{rem_sec:02d}</b>",
        reply_markup=referee_match_kb(match_id, is_started=True, is_finished=False)
    )


# ─────────────────────────────────────────────
#  ГОЛ — шаг 1: выбор команды
# ─────────────────────────────────────────────

@router.callback_query(F.data.startswith("ref_goal:"))
async def ref_goal_select_team(call: CallbackQuery, session: AsyncSession, player: Player | None):
    if not _is_referee(call.from_user.id, player):
        await call.answer("⛔", show_alert=True)
        return
    await call.answer()

    match_id = int(call.data.split(":")[1])
    match = await session.get(Match, match_id)
    if not match:
        return

    await call.message.edit_text(
        "🥅 <b>Гол</b>\n\nКакая команда забила?",
        reply_markup=select_team_kb(
            match_id, "ref_goal_team",
            match.team_home_id, match.team_home.name,
            match.team_away_id, match.team_away.name,
        )
    )


# ─────────────────────────────────────────────
#  ГОЛ — шаг 2: выбор игрока
# ─────────────────────────────────────────────

@router.callback_query(F.data.startswith("ref_goal_team:"))
async def ref_goal_select_player(call: CallbackQuery, session: AsyncSession, player: Player | None):
    if not _is_referee(call.from_user.id, player):
        await call.answer("⛔", show_alert=True)
        return
    await call.answer()

    _, match_id_str, team_id_str = call.data.split(":")
    match_id = int(match_id_str)
    team_id = int(team_id_str)
    match = await session.get(Match, match_id)
    if not match:
        return

    players = await _get_attendees(session, match.game_day_id)
    if not players:
        await call.answer("❌ Нет записавшихся игроков", show_alert=True)
        return

    await call.message.edit_text(
        "🥅 <b>Гол</b>\n\nКто забил?",
        reply_markup=select_player_kb(match_id, "ref_goal_player", team_id, players)
    )


# ─────────────────────────────────────────────
#  ГОЛ — шаг 3: записать гол
# ─────────────────────────────────────────────

@router.callback_query(F.data.startswith("ref_goal_player:"))
async def ref_goal_record(call: CallbackQuery, session: AsyncSession, player: Player | None):
    if not _is_referee(call.from_user.id, player):
        await call.answer("⛔", show_alert=True)
        return

    parts = call.data.split(":")
    match_id = int(parts[1])
    scorer_id = int(parts[2])
    team_id = int(parts[3])

    match = await session.get(Match, match_id)
    scorer = await session.get(Player, scorer_id)
    if not match or not scorer:
        await call.answer("❌ Ошибка", show_alert=True)
        return

    goal = Goal(
        match_id=match_id,
        player_id=scorer_id,
        team_id=team_id,
        goal_type=GoalType.GOAL,
        scored_at=datetime.now(),
    )
    session.add(goal)

    # Обновить счёт
    if team_id == match.team_home_id:
        match.score_home += 1
    else:
        match.score_away += 1

    await session.commit()
    await session.refresh(match)

    await call.answer(f"✅ Гол! {scorer.name}", show_alert=True)
    await call.message.edit_text(
        _match_panel_text(match),
        reply_markup=referee_match_kb(match_id, is_started=match.started_at is not None,
                                      is_finished=False)
    )


# ─────────────────────────────────────────────
#  ЖЁЛТАЯ КАРТОЧКА — шаг 1: команда
# ─────────────────────────────────────────────

@router.callback_query(F.data.startswith("ref_yellow:"))
async def ref_yellow_select_team(call: CallbackQuery, session: AsyncSession, player: Player | None):
    if not _is_referee(call.from_user.id, player):
        await call.answer("⛔", show_alert=True)
        return
    await call.answer()

    match_id = int(call.data.split(":")[1])
    match = await session.get(Match, match_id)
    if not match:
        return

    await call.message.edit_text(
        "🟡 <b>Жёлтая карточка</b>\n\nИз какой команды игрок?",
        reply_markup=select_team_kb(
            match_id, "ref_yellow_team",
            match.team_home_id, match.team_home.name,
            match.team_away_id, match.team_away.name,
        )
    )


@router.callback_query(F.data.startswith("ref_yellow_team:"))
async def ref_yellow_select_player(call: CallbackQuery, session: AsyncSession, player: Player | None):
    if not _is_referee(call.from_user.id, player):
        await call.answer("⛔", show_alert=True)
        return
    await call.answer()

    _, match_id_str, team_id_str = call.data.split(":")
    match_id, team_id = int(match_id_str), int(team_id_str)
    match = await session.get(Match, match_id)
    if not match:
        return

    players = await _get_attendees(session, match.game_day_id)
    await call.message.edit_text(
        "🟡 <b>Жёлтая карточка</b>\n\nКому?",
        reply_markup=select_player_kb(match_id, "ref_yellow_player", team_id, players)
    )


@router.callback_query(F.data.startswith("ref_yellow_player:"))
async def ref_yellow_record(call: CallbackQuery, session: AsyncSession, player: Player | None):
    if not _is_referee(call.from_user.id, player):
        await call.answer("⛔", show_alert=True)
        return

    parts = call.data.split(":")
    match_id, player_id, team_id = int(parts[1]), int(parts[2]), int(parts[3])

    match = await session.get(Match, match_id)
    carded = await session.get(Player, player_id)
    if not match or not carded:
        await call.answer("❌ Ошибка", show_alert=True)
        return

    card = Card(
        match_id=match_id,
        player_id=player_id,
        team_id=team_id,
        card_type=CardType.YELLOW,
        issued_at=datetime.now(),
    )
    session.add(card)
    await session.commit()
    await session.refresh(match)

    await call.answer(f"🟡 ЖК: {carded.name}", show_alert=True)
    await call.message.edit_text(
        _match_panel_text(match),
        reply_markup=referee_match_kb(match_id, is_started=match.started_at is not None,
                                      is_finished=False)
    )


# ─────────────────────────────────────────────
#  КРАСНАЯ КАРТОЧКА — шаг 1: команда
# ─────────────────────────────────────────────

@router.callback_query(F.data.startswith("ref_red:"))
async def ref_red_select_team(call: CallbackQuery, session: AsyncSession, player: Player | None):
    if not _is_referee(call.from_user.id, player):
        await call.answer("⛔", show_alert=True)
        return
    await call.answer()

    match_id = int(call.data.split(":")[1])
    match = await session.get(Match, match_id)
    if not match:
        return

    await call.message.edit_text(
        "🔴 <b>Красная карточка</b>\n\nИз какой команды игрок?",
        reply_markup=select_team_kb(
            match_id, "ref_red_team",
            match.team_home_id, match.team_home.name,
            match.team_away_id, match.team_away.name,
        )
    )


@router.callback_query(F.data.startswith("ref_red_team:"))
async def ref_red_select_player(call: CallbackQuery, session: AsyncSession, player: Player | None):
    if not _is_referee(call.from_user.id, player):
        await call.answer("⛔", show_alert=True)
        return
    await call.answer()

    _, match_id_str, team_id_str = call.data.split(":")
    match_id, team_id = int(match_id_str), int(team_id_str)
    match = await session.get(Match, match_id)
    if not match:
        return

    players = await _get_attendees(session, match.game_day_id)
    await call.message.edit_text(
        "🔴 <b>Красная карточка</b>\n\nКому?",
        reply_markup=select_player_kb(match_id, "ref_red_player", team_id, players)
    )


@router.callback_query(F.data.startswith("ref_red_player:"))
async def ref_red_record(call: CallbackQuery, session: AsyncSession, player: Player | None):
    if not _is_referee(call.from_user.id, player):
        await call.answer("⛔", show_alert=True)
        return

    parts = call.data.split(":")
    match_id, player_id, team_id = int(parts[1]), int(parts[2]), int(parts[3])

    match = await session.get(Match, match_id)
    carded = await session.get(Player, player_id)
    if not match or not carded:
        await call.answer("❌ Ошибка", show_alert=True)
        return

    card = Card(
        match_id=match_id,
        player_id=player_id,
        team_id=team_id,
        card_type=CardType.RED,
        issued_at=datetime.now(),
    )
    session.add(card)
    await session.commit()
    await session.refresh(match)

    await call.answer(f"🔴 КК: {carded.name}", show_alert=True)
    await call.message.edit_text(
        _match_panel_text(match),
        reply_markup=referee_match_kb(match_id, is_started=match.started_at is not None,
                                      is_finished=False)
    )


# ─────────────────────────────────────────────
#  ЗАВЕРШИТЬ МАТЧ
# ─────────────────────────────────────────────

@router.callback_query(F.data.startswith("ref_finish:"))
async def ref_finish_confirm(call: CallbackQuery, session: AsyncSession, player: Player | None):
    if not _is_referee(call.from_user.id, player):
        await call.answer("⛔", show_alert=True)
        return
    await call.answer()

    match_id = int(call.data.split(":")[1])
    match = await session.get(Match, match_id)
    if not match:
        return

    await call.message.edit_text(
        f"🏁 Завершить матч?\n\n"
        f"<b>{match.team_home.name} {match.score_home}:{match.score_away} {match.team_away.name}</b>\n\n"
        "Это действие нельзя отменить.",
        reply_markup=confirm_finish_kb(match_id)
    )


@router.callback_query(F.data.startswith("ref_finish_ok:"))
async def ref_finish_match(call: CallbackQuery, session: AsyncSession,
                           player: Player | None, bot: Bot):
    if not _is_referee(call.from_user.id, player):
        await call.answer("⛔", show_alert=True)
        return
    await call.answer("✅ Матч завершён!")

    match_id = int(call.data.split(":")[1])
    match = await session.get(Match, match_id)
    if not match:
        return

    match.status = MatchStatus.FINISHED
    match.finished_at = datetime.now()
    await session.commit()
    await session.refresh(match)

    # Отменить таймер если ещё не сработал
    try:
        scheduler.remove_job(f"timer_{match_id}")
    except Exception:
        pass

    # Сформировать итоговый текст
    home = match.team_home.name
    away = match.team_away.name

    result_text = (
        f"🏁 <b>Финальный счёт</b>\n\n"
        f"⚽ <b>{home}  {match.score_home} : {match.score_away}  {away}</b>\n"
    )

    goals_by_team: dict[int, list[str]] = {match.team_home_id: [], match.team_away_id: []}
    for g in sorted(match.goals, key=lambda x: x.scored_at):
        own = " (авт.)" if g.goal_type == GoalType.OWN_GOAL else ""
        goals_by_team.setdefault(g.team_id, []).append(f"{g.player.name}{own}")

    if goals_by_team.get(match.team_home_id):
        result_text += f"\n🔴 {home}: " + ", ".join(goals_by_team[match.team_home_id])
    if goals_by_team.get(match.team_away_id):
        result_text += f"\n🔵 {away}: " + ", ".join(goals_by_team[match.team_away_id])

    cards = [c for c in match.cards]
    if cards:
        result_text += "\n\n<b>Карточки:</b>"
        for c in sorted(cards, key=lambda x: x.issued_at):
            emoji = "🟡" if c.card_type == CardType.YELLOW else "🔴"
            result_text += f"\n  {emoji} {c.player.name}"

    await call.message.edit_text(
        result_text,
        reply_markup=referee_match_kb(match_id, is_started=True, is_finished=True)
    )

    # Уведомить всех активных игроков об итогах матча
    game_day_players = await _get_attendees(session, match.game_day_id)
    notified = 0
    for p in game_day_players:
        try:
            await bot.send_message(p.telegram_id, result_text)
            notified += 1
        except Exception:
            pass

    if notified:
        await call.message.answer(f"📢 Результаты отправлены {notified} игрокам.")


# ─────────────────────────────────────────────
#  Заглушка для кнопки "noop"
# ─────────────────────────────────────────────

@router.callback_query(F.data == "noop")
async def noop(call: CallbackQuery):
    await call.answer()

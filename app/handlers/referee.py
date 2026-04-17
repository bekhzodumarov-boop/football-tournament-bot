"""
Обработчики для судьи (referee).
Доступ: игроки с is_referee=True ИЛИ администраторы.

Новая логика создания матча:
  1. Название Команды 1
  2. Выбор игроков Команды 1 (мультивыбор из записавшихся)
  3. Название Команды 2
  4. Выбор игроков Команды 2 (из оставшихся)
  5. Длительность матча

При фиксации гола/ЖК/КК — показывать только игроков выбранной команды.
"""
from datetime import datetime, timedelta

from aiogram import Router, F, Bot
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

import logging

logger = logging.getLogger(__name__)

from app.config import settings
from app.database.models import (
    GameDay, GameDayStatus,
    Attendance, AttendanceResponse,
    Team, TeamPlayer, Match, MatchStatus, MatchFormat,
    Goal, GoalType,
    Card, CardType,
    Player,
    MatchStage, MATCH_STAGE_LABELS,
)
from app.keyboards.referee import (
    referee_gamedays_kb, referee_gd_kb, referee_match_kb,
    select_team_kb, select_player_kb, confirm_finish_kb,
    team_players_select_kb, teams_list_kb, pick_team_kb,
    sub_player_out_kb, sub_player_in_kb, pick_format_kb, pick_stage_kb,
)
from app.scheduler import scheduler

router = Router()

# match_id → {bot, chat_id, message_id, started_at, duration_min, home, away, score_*}
_active_timers: dict[int, dict] = {}


# ─────────────────────────────────────────────
#  FSM
# ─────────────────────────────────────────────

class RefereeMatchFSM(StatesGroup):
    # Ручной ввод команд (когда нет заранее созданных команд)
    waiting_team1 = State()
    waiting_team1_players = State()
    waiting_team2 = State()
    waiting_team2_players = State()
    # Выбор из существующих команд
    waiting_pick_team1 = State()
    waiting_pick_team2 = State()
    # Общие шаги (оба потока)
    waiting_stage = State()        # выбор стадии: группа / полуфинал / ...
    waiting_format = State()       # выбор формата: время / голы
    waiting_duration = State()     # минуты (формат TIME)
    waiting_goals_count = State()  # кол-во голов (формат GOALS)


class RefereeTeamSetupFSM(StatesGroup):
    """Предварительное создание команд для игрового дня."""
    waiting_team_name = State()
    waiting_team_players = State()


# ─────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────

def _is_referee(user_id: int, player: Player | None) -> bool:
    return settings.is_admin(user_id) or (player is not None and player.is_referee)


async def _load_match(session: AsyncSession, match_id: int) -> Match | None:
    result = await session.execute(
        select(Match)
        .options(
            selectinload(Match.team_home),
            selectinload(Match.team_away),
            selectinload(Match.goals).selectinload(Goal.player),
            selectinload(Match.cards).selectinload(Card.player),
        )
        .where(Match.id == match_id)
    )
    return result.scalar_one_or_none()


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


async def _get_team_players(session: AsyncSession, team_id: int) -> list[Player]:
    """Игроки конкретной команды (из TeamPlayer)."""
    result = await session.execute(
        select(Player)
        .join(TeamPlayer, TeamPlayer.player_id == Player.id)
        .where(TeamPlayer.team_id == team_id)
        .order_by(Player.name)
    )
    return result.scalars().all()


def _progress_bar(elapsed_sec: float, total_sec: float, width: int = 20) -> str:
    pct = min(elapsed_sec / max(total_sec, 1), 1.0)
    filled = int(pct * width)
    return "█" * filled + "░" * (width - filled)


def _timer_text(home: str, away: str, started_at: datetime, duration_min: int,
                score_home: int = 0, score_away: int = 0) -> str:
    elapsed = datetime.now() - started_at
    total = timedelta(minutes=duration_min)
    remaining = total - elapsed
    elapsed_sec = max(elapsed.total_seconds(), 0)
    total_sec = total.total_seconds()

    if remaining.total_seconds() <= 0:
        return (
            f"🔔 <b>ВРЕМЯ ВЫШЛО!</b>\n\n"
            f"⚽ <b>{home}  {score_home}:{score_away}  {away}</b>\n\n"
            f"[{'█' * 20}] 100%\n\n"
            "Зафиксируй финальный счёт!"
        )

    rem_min = int(remaining.total_seconds() // 60)
    rem_sec = int(remaining.total_seconds() % 60)
    el_min = int(elapsed_sec // 60)
    el_sec = int(elapsed_sec % 60)
    pct = int(elapsed_sec / total_sec * 100)
    bar = _progress_bar(elapsed_sec, total_sec)
    return (
        f"⏱ <b>Таймер матча</b>\n\n"
        f"⚽ <b>{home}  {score_home}:{score_away}  {away}</b>\n\n"
        f"[{bar}] {pct}%\n\n"
        f"⬛ Прошло:    <b>{el_min}:{el_sec:02d}</b>\n"
        f"🔴 Осталось: <b>{rem_min}:{rem_sec:02d}</b>"
    )


def _match_panel_text(match: Match) -> str:
    home = match.team_home.name
    away = match.team_away.name

    if match.status == MatchStatus.IN_PROGRESS and match.started_at:
        elapsed = datetime.now() - match.started_at
        el_min = int(elapsed.total_seconds() // 60)
        el_sec = int(elapsed.total_seconds() % 60)
        timer_line = f"⏱ Идёт {el_min}:{el_sec:02d}"
    elif match.status == MatchStatus.FINISHED:
        timer_line = "✅ Матч завершён"
    else:
        timer_line = "⏱ Таймер не запущен"

    goals_lines = [
        f"  🥅 {g.player.name}"
        + (" (авт.)" if g.goal_type == GoalType.OWN_GOAL else "")
        + f" [{home if g.team_id == match.team_home_id else away}]"
        for g in sorted(match.goals, key=lambda x: x.scored_at)
    ]
    card_lines = [
        f"  {'🟨' if c.card_type == CardType.YELLOW else '🟥'} {c.player.name}"
        f" [{home if c.team_id == match.team_home_id else away}]"
        for c in sorted(match.cards, key=lambda x: x.issued_at)
    ]

    text = f"⚽ <b>{home}  {match.score_home} : {match.score_away}  {away}</b>\n{timer_line}\n"
    if goals_lines:
        text += "\n<b>Голы:</b>\n" + "\n".join(goals_lines) + "\n"
    if card_lines:
        text += "\n<b>Карточки:</b>\n" + "\n".join(card_lines) + "\n"
    return text


# ─────────────────────────────────────────────
#  Живой таймер (каждые 10 сек)
# ─────────────────────────────────────────────

async def _update_timer_message(match_id: int):
    data = _active_timers.get(match_id)
    if not data:
        return
    remaining = timedelta(minutes=data["duration_min"]) - (datetime.now() - data["started_at"])
    text = _timer_text(
        data["home"], data["away"], data["started_at"], data["duration_min"],
        data.get("score_home", 0), data.get("score_away", 0),
    )
    try:
        await data["bot"].edit_message_text(
            text, chat_id=data["chat_id"], message_id=data["message_id"], parse_mode="HTML"
        )
    except Exception as e:
        logger.warning(f"Timer message update failed for match {match_id}: {e}")
    if remaining.total_seconds() <= 0:
        try:
            scheduler.remove_job(f"timer_tick_{match_id}")
        except Exception:
            pass
        _active_timers.pop(match_id, None)


# ─────────────────────────────────────────────
#  /referee — вход
# ─────────────────────────────────────────────

@router.message(Command("referee"))
async def cmd_referee(message: Message, session: AsyncSession,
                      player: Player | None, state: FSMContext):
    await state.clear()
    if not _is_referee(message.from_user.id, player):
        await message.answer("⛔ Нет доступа. Команда для судей.")
        return

    result = await session.execute(
        select(GameDay)
        .where(GameDay.status.in_([
            GameDayStatus.ANNOUNCED, GameDayStatus.CLOSED, GameDayStatus.IN_PROGRESS
        ]))
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
#  Выбор игрового дня
# ─────────────────────────────────────────────

@router.callback_query(F.data.startswith("ref_gd:"))
async def ref_select_gameday(call: CallbackQuery, session: AsyncSession,
                             player: Player | None):
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
        select(Match)
        .options(selectinload(Match.team_home), selectinload(Match.team_away))
        .where(Match.game_day_id == game_day_id)
        .order_by(Match.id)
    )
    matches = result.scalars().all()

    await call.message.edit_text(
        f"🦺 <b>Игровой день {game_day.scheduled_at.strftime('%d.%m.%Y %H:%M')}</b>\n"
        f"📍 {game_day.location}\n\nВыбери матч или создай новый:",
        reply_markup=referee_gd_kb(game_day_id, matches)
    )


# ─────────────────────────────────────────────
#  Создание матча — шаг 1: название Команды 1
# ─────────────────────────────────────────────

@router.callback_query(F.data.startswith("ref_new_match:"))
async def ref_new_match_start(call: CallbackQuery, state: FSMContext,
                               player: Player | None, session: AsyncSession):
    if not _is_referee(call.from_user.id, player):
        await call.answer("⛔", show_alert=True)
        return
    await call.answer()

    game_day_id = int(call.data.split(":")[1])
    await state.update_data(game_day_id=game_day_id, team1_player_ids=[], team2_player_ids=[])

    # Проверить — есть ли уже созданные команды для этого игрового дня
    teams_result = await session.execute(
        select(Team).where(Team.game_day_id == game_day_id)
    )
    teams = teams_result.scalars().all()

    if len(teams) >= 2:
        # Поток: выбор из существующих команд
        await state.update_data(flow="existing")
        await state.set_state(RefereeMatchFSM.waiting_pick_team1)
        await call.message.edit_text(
            "➕ <b>Новый матч</b>\n\nШаг 1 из 3\n\n"
            "Выбери <b>Команду 1</b>:",
            reply_markup=pick_team_kb("ref_pick_t1", game_day_id, teams)
        )
    else:
        # Поток: ручной ввод
        await state.update_data(flow="manual")
        await state.set_state(RefereeMatchFSM.waiting_team1)
        await call.message.edit_text(
            "➕ <b>Новый матч</b>\n\nШаг 1 из 5\n\n"
            "Введи название <b>Команды 1</b>:\n"
            "<i>Например: Красные, Команда А…</i>\n\n"
            "<i>💡 Совет: создай команды заранее через «👥 Составы команд»</i>"
        )


@router.message(RefereeMatchFSM.waiting_team1)
async def ref_team1(message: Message, state: FSMContext, session: AsyncSession):
    name = message.text.strip() if message.text else ""
    if not name:
        await message.answer("❌ Название не может быть пустым.")
        return

    await state.update_data(team1_name=name, selected_player_ids=[])

    # Загрузить всех записавшихся и сохранить в FSM
    data = await state.get_data()
    attendees = await _get_attendees(session, data["game_day_id"])
    available = [{"id": p.id, "name": p.name} for p in attendees]
    await state.update_data(available_players=available)
    await state.set_state(RefereeMatchFSM.waiting_team1_players)

    await message.answer(
        f"✅ Команда 1: <b>{name}</b>\n\n"
        f"Шаг 2 из 5\n\n"
        f"👥 Выбери игроков <b>{name}</b> из записавшихся на игру:\n"
        f"<i>Нажимай на имена, потом «Готово»</i>",
        reply_markup=team_players_select_kb(available, [], name)
    )


# ─────────────────────────────────────────────
#  Создание матча — выбор игроков (общий для обеих команд)
# ─────────────────────────────────────────────

@router.callback_query(
    F.data.startswith("ref_toggle_player:"),
    StateFilter(
        RefereeMatchFSM.waiting_team1_players,
        RefereeMatchFSM.waiting_team2_players,
        RefereeTeamSetupFSM.waiting_team_players,
    )
)
async def ref_toggle_player(call: CallbackQuery, state: FSMContext,
                            player: Player | None):
    if not _is_referee(call.from_user.id, player):
        await call.answer("⛔", show_alert=True)
        return

    toggled_id = int(call.data.split(":")[1])
    data = await state.get_data()
    selected: list[int] = list(data.get("selected_player_ids", []))
    available: list[dict] = data.get("available_players", [])

    # Toggle
    if toggled_id in selected:
        selected.remove(toggled_id)
    else:
        selected.append(toggled_id)

    await state.update_data(selected_player_ids=selected)

    # Определить название текущей команды для кнопки «Готово»
    current_state = await state.get_state()
    if current_state == RefereeMatchFSM.waiting_team1_players.state:
        team_name = data.get("team1_name", "Команда 1")
    else:
        team_name = data.get("team2_name", "Команда 2")

    await call.message.edit_reply_markup(
        reply_markup=team_players_select_kb(available, selected, team_name)
    )
    await call.answer()


@router.callback_query(
    F.data == "ref_team_players_done",
    StateFilter(
        RefereeMatchFSM.waiting_team1_players,
        RefereeMatchFSM.waiting_team2_players,
        RefereeTeamSetupFSM.waiting_team_players,
    )
)
async def ref_team_players_done(call: CallbackQuery, state: FSMContext,
                                player: Player | None, session: AsyncSession):
    if not _is_referee(call.from_user.id, player):
        await call.answer("⛔", show_alert=True)
        return
    await call.answer()

    data = await state.get_data()
    selected: list[int] = data.get("selected_player_ids", [])
    if not selected:
        await call.answer("⚠️ Выбери хотя бы одного игрока", show_alert=True)
        return

    current_state = await state.get_state()

    # ── Ветка: настройка команд до турнира ──
    if current_state == RefereeTeamSetupFSM.waiting_team_players.state:
        team_name = data.get("setup_team_name", "Команда")
        game_day_id = data.get("game_day_id")

        # Создать команду и привязать игроков
        color_emojis = ["🔴", "🔵", "🟢", "🟡", "🟠", "🟣"]
        teams_count_result = await session.execute(
            select(Team).where(Team.game_day_id == game_day_id)
        )
        existing_count = len(teams_count_result.scalars().all())
        emoji = color_emojis[existing_count % len(color_emojis)]

        team = Team(game_day_id=game_day_id, name=team_name, color_emoji=emoji)
        session.add(team)
        await session.flush()
        for pid in selected:
            session.add(TeamPlayer(team_id=team.id, player_id=pid))
        await session.commit()

        # Показать обновлённый список команд
        teams_result = await session.execute(
            select(Team).where(Team.game_day_id == game_day_id)
        )
        teams = teams_result.scalars().all()
        await state.clear()

        lines = [f"👥 <b>Команды игрового дня</b>\n"]
        for t in teams:
            tp_result = await session.execute(
                select(TeamPlayer).options(selectinload(TeamPlayer.player))
                .where(TeamPlayer.team_id == t.id)
            )
            tp_list = tp_result.scalars().all()
            names = ", ".join(tp.player.name for tp in tp_list) or "—"
            lines.append(f"{t.color_emoji} <b>{t.name}</b> ({len(tp_list)} чел.): {names}")

        await call.message.edit_text(
            "\n".join(lines),
            reply_markup=teams_list_kb(game_day_id, teams)
        )
        return

    # ── Ветка: создание матча (ручной ввод) ──
    if current_state == RefereeMatchFSM.waiting_team1_players.state:
        await state.update_data(team1_player_ids=selected, selected_player_ids=[])
        all_available: list[dict] = data.get("available_players", [])
        remaining = [p for p in all_available if p["id"] not in selected]
        await state.update_data(available_players=remaining)
        await state.set_state(RefereeMatchFSM.waiting_team2)

        team1_name = data.get("team1_name", "Команда 1")
        await call.message.edit_text(
            f"✅ <b>{team1_name}</b>: {len(selected)} игроков выбрано\n\n"
            f"Шаг 3 из 5\n\n"
            "Введи название <b>Команды 2</b>:"
        )
    else:
        await state.update_data(team2_player_ids=selected, selected_player_ids=[])
        await state.set_state(RefereeMatchFSM.waiting_stage)

        team2_name = data.get("team2_name", "Команда 2")
        await call.message.edit_text(
            f"✅ <b>{team2_name}</b>: {len(selected)} игроков выбрано\n\n"
            f"Шаг 5 из 6\n\nВыбери <b>стадию матча</b>:",
            reply_markup=pick_stage_kb()
        )


# ─────────────────────────────────────────────
#  Создание матча — шаг 3: название Команды 2
# ─────────────────────────────────────────────

@router.message(RefereeMatchFSM.waiting_team2)
async def ref_team2(message: Message, state: FSMContext):
    name = message.text.strip() if message.text else ""
    if not name:
        await message.answer("❌ Название не может быть пустым.")
        return

    await state.update_data(team2_name=name, selected_player_ids=[])
    data = await state.get_data()
    available: list[dict] = data.get("available_players", [])
    await state.set_state(RefereeMatchFSM.waiting_team2_players)

    await message.answer(
        f"✅ Команда 2: <b>{name}</b>\n\n"
        f"Шаг 4 из 5\n\n"
        f"👥 Выбери игроков <b>{name}</b>:\n"
        f"<i>Нажимай на имена, потом «Готово»</i>",
        reply_markup=team_players_select_kb(available, [], name)
    )


# ─────────────────────────────────────────────
#  Создание матча — шаг 5: длительность → создание
# ─────────────────────────────────────────────

@router.message(RefereeMatchFSM.waiting_duration)
async def ref_duration(message: Message, state: FSMContext, session: AsyncSession):
    try:
        duration = int(message.text.strip())
        if duration < 1 or duration > 120:
            raise ValueError
    except ValueError:
        await message.answer("❌ Введи число от 1 до 120:")
        return

    await state.update_data(duration_min=duration)
    await _create_match_from_state(message, state, session)


async def _create_match_from_state(message: Message, state: FSMContext,
                                   session: AsyncSession):
    """Создать матч из данных FSM (общий для обоих форматов и потоков)."""
    data = await state.get_data()
    await state.clear()

    game_day_id = data["game_day_id"]
    flow = data.get("flow", "manual")
    fmt_str = data.get("match_format", "time")
    match_fmt = MatchFormat.GOALS if fmt_str == "goals" else MatchFormat.TIME
    duration = data.get("duration_min", 20)
    goals_to_win = data.get("goals_to_win", 3)
    match_stage_val = data.get("match_stage_val", "group")

    if flow == "existing":
        team1_id = data["existing_team1_id"]
        team2_id = data["existing_team2_id"]
        team1 = await session.get(Team, team1_id)
        team2 = await session.get(Team, team2_id)

        match = Match(
            game_day_id=game_day_id,
            team_home_id=team1_id,
            team_away_id=team2_id,
            match_format=match_fmt,
            duration_min=duration,
            goals_to_win=goals_to_win,
            status=MatchStatus.SCHEDULED,
            match_stage=match_stage_val,
        )
        session.add(match)
        await session.commit()
        match = await _load_match(session, match.id)

        fmt_line = (
            f"⏱ Длительность: {duration} мин." if match_fmt == MatchFormat.TIME
            else f"🥅 До {goals_to_win} голов"
        )
        await message.answer(
            f"✅ <b>Матч создан!</b>\n\n"
            f"{team1.color_emoji} {team1.name} vs {team2.color_emoji} {team2.name}\n"
            f"{fmt_line}\n\n"
            "Используй кнопки для управления матчем:",
            reply_markup=referee_match_kb(match.id, is_started=False, is_finished=False)
        )
    else:
        team1_name = data["team1_name"]
        team2_name = data["team2_name"]
        team1_player_ids: list[int] = data.get("team1_player_ids", [])
        team2_player_ids: list[int] = data.get("team2_player_ids", [])

        team1 = Team(game_day_id=game_day_id, name=team1_name, color_emoji="🔴")
        team2 = Team(game_day_id=game_day_id, name=team2_name, color_emoji="🔵")
        session.add_all([team1, team2])
        await session.flush()

        for pid in team1_player_ids:
            session.add(TeamPlayer(team_id=team1.id, player_id=pid))
        for pid in team2_player_ids:
            session.add(TeamPlayer(team_id=team2.id, player_id=pid))

        match = Match(
            game_day_id=game_day_id,
            team_home_id=team1.id,
            team_away_id=team2.id,
            match_format=match_fmt,
            duration_min=duration,
            goals_to_win=goals_to_win,
            status=MatchStatus.SCHEDULED,
            match_stage=match_stage_val,
        )
        session.add(match)
        await session.commit()
        match = await _load_match(session, match.id)

        fmt_line = (
            f"⏱ Длительность: {duration} мин." if match_fmt == MatchFormat.TIME
            else f"🥅 До {goals_to_win} голов"
        )
        await message.answer(
            f"✅ <b>Матч создан!</b>\n\n"
            f"🔴 {team1_name} ({len(team1_player_ids)} чел.) vs "
            f"🔵 {team2_name} ({len(team2_player_ids)} чел.)\n"
            f"{fmt_line}\n\n"
            "Используй кнопки для управления матчем:",
            reply_markup=referee_match_kb(match.id, is_started=False, is_finished=False)
        )


# ─────────────────────────────────────────────
#  Панель матча
# ─────────────────────────────────────────────

@router.callback_query(F.data.startswith("ref_match:"))
async def ref_match_panel(call: CallbackQuery, session: AsyncSession,
                          player: Player | None):
    if not _is_referee(call.from_user.id, player):
        await call.answer("⛔", show_alert=True)
        return
    await call.answer()

    match_id = int(call.data.split(":")[1])
    match = await _load_match(session, match_id)
    if not match:
        await call.message.edit_text("❌ Матч не найден.")
        return

    await call.message.edit_text(
        _match_panel_text(match),
        reply_markup=referee_match_kb(
            match_id,
            is_started=match.status == MatchStatus.IN_PROGRESS,
            is_finished=match.status == MatchStatus.FINISHED,
        )
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
    match = await _load_match(session, match_id)
    if not match:
        return

    now = datetime.now()
    match.started_at = now
    match.status = MatchStatus.IN_PROGRESS
    await session.commit()

    home = match.team_home.name
    away = match.team_away.name
    duration_min = match.duration_min

    timer_msg = await call.message.answer(
        _timer_text(home, away, now, duration_min, match.score_home, match.score_away)
    )

    _active_timers[match_id] = {
        "bot": bot,
        "chat_id": timer_msg.chat.id,
        "message_id": timer_msg.message_id,
        "started_at": now,
        "duration_min": duration_min,
        "home": home,
        "away": away,
        "score_home": match.score_home,
        "score_away": match.score_away,
    }

    scheduler.add_job(
        _update_timer_message,
        trigger="interval",
        seconds=10,
        args=[match_id],
        id=f"timer_tick_{match_id}",
        replace_existing=True,
        max_instances=1,
    )

    await call.message.edit_text(
        _match_panel_text(match),
        reply_markup=referee_match_kb(match_id, is_started=True, is_finished=False)
    )


# ─────────────────────────────────────────────
#  ГОЛ — шаг 1: выбор команды
# ─────────────────────────────────────────────

@router.callback_query(F.data.startswith("ref_goal:"))
async def ref_goal_select_team(call: CallbackQuery, session: AsyncSession,
                                player: Player | None):
    if not _is_referee(call.from_user.id, player):
        await call.answer("⛔", show_alert=True)
        return
    await call.answer()

    match_id = int(call.data.split(":")[1])
    match = await _load_match(session, match_id)
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
#  ГОЛ — шаг 2: выбор игрока из состава команды
# ─────────────────────────────────────────────

@router.callback_query(F.data.startswith("ref_goal_team:"))
async def ref_goal_select_player(call: CallbackQuery, session: AsyncSession,
                                  player: Player | None):
    if not _is_referee(call.from_user.id, player):
        await call.answer("⛔", show_alert=True)
        return
    await call.answer()

    _, match_id_str, team_id_str = call.data.split(":")
    match_id = int(match_id_str)
    team_id = int(team_id_str)

    match = await _load_match(session, match_id)
    if not match:
        return

    team_name = match.team_home.name if team_id == match.team_home_id else match.team_away.name

    # Игроки конкретной команды
    players = await _get_team_players(session, team_id)
    if not players:
        # Fallback: если состав не задан — показать всех записавшихся
        players = await _get_attendees(session, match.game_day_id)

    await call.message.edit_text(
        f"🥅 <b>Гол — {team_name}</b>\n\nКто забил?",
        reply_markup=select_player_kb(match_id, "ref_goal_player", team_id, players)
    )


# ─────────────────────────────────────────────
#  ГОЛ — шаг 3: записать
# ─────────────────────────────────────────────

@router.callback_query(F.data.startswith("ref_goal_player:"))
async def ref_goal_record(call: CallbackQuery, session: AsyncSession,
                          player: Player | None):
    if not _is_referee(call.from_user.id, player):
        await call.answer("⛔", show_alert=True)
        return

    parts = call.data.split(":")
    match_id, scorer_id, team_id = int(parts[1]), int(parts[2]), int(parts[3])

    match = await _load_match(session, match_id)
    scorer = await session.get(Player, scorer_id)
    if not match or not scorer:
        await call.answer("❌ Ошибка", show_alert=True)
        return

    session.add(Goal(
        match_id=match_id, player_id=scorer_id, team_id=team_id,
        goal_type=GoalType.GOAL, scored_at=datetime.now(),
    ))
    if team_id == match.team_home_id:
        match.score_home += 1
    else:
        match.score_away += 1

    # Автофиниш при формате "до N голов"
    auto_finished = False
    if match.match_format == MatchFormat.GOALS:
        winning_score = max(match.score_home, match.score_away)
        if winning_score >= match.goals_to_win:
            match.status = MatchStatus.FINISHED
            match.finished_at = datetime.now()
            auto_finished = True
            try:
                scheduler.remove_job(f"timer_tick_{match_id}")
            except Exception:
                pass
            _active_timers.pop(match_id, None)

    await session.commit()
    match = await _load_match(session, match_id)

    if match_id in _active_timers:
        _active_timers[match_id]["score_home"] = match.score_home
        _active_timers[match_id]["score_away"] = match.score_away

    if auto_finished:
        winner = match.team_home.name if match.score_home > match.score_away else match.team_away.name
        await call.answer(f"🏆 {winner} побеждает!", show_alert=True)
    else:
        await call.answer(f"✅ Гол! {scorer.name}", show_alert=True)

    await call.message.edit_text(
        _match_panel_text(match),
        reply_markup=referee_match_kb(
            match_id,
            is_started=match.status == MatchStatus.IN_PROGRESS,
            is_finished=match.status == MatchStatus.FINISHED,
        )
    )


# ─────────────────────────────────────────────
#  ЖЁЛТАЯ КАРТОЧКА
# ─────────────────────────────────────────────

@router.callback_query(F.data.startswith("ref_yellow:"))
async def ref_yellow_select_team(call: CallbackQuery, session: AsyncSession,
                                  player: Player | None):
    if not _is_referee(call.from_user.id, player):
        await call.answer("⛔", show_alert=True)
        return
    await call.answer()

    match_id = int(call.data.split(":")[1])
    match = await _load_match(session, match_id)
    if not match:
        return

    await call.message.edit_text(
        "🟨 <b>Жёлтая карточка</b>\n\nИз какой команды?",
        reply_markup=select_team_kb(
            match_id, "ref_yellow_team",
            match.team_home_id, match.team_home.name,
            match.team_away_id, match.team_away.name,
        )
    )


@router.callback_query(F.data.startswith("ref_yellow_team:"))
async def ref_yellow_select_player(call: CallbackQuery, session: AsyncSession,
                                    player: Player | None):
    if not _is_referee(call.from_user.id, player):
        await call.answer("⛔", show_alert=True)
        return
    await call.answer()

    _, match_id_str, team_id_str = call.data.split(":")
    match_id, team_id = int(match_id_str), int(team_id_str)
    match = await _load_match(session, match_id)
    if not match:
        return

    team_name = match.team_home.name if team_id == match.team_home_id else match.team_away.name
    players = await _get_team_players(session, team_id)
    if not players:
        players = await _get_attendees(session, match.game_day_id)

    await call.message.edit_text(
        f"🟨 <b>Жёлтая карточка — {team_name}</b>\n\nКому?",
        reply_markup=select_player_kb(match_id, "ref_yellow_player", team_id, players)
    )


@router.callback_query(F.data.startswith("ref_yellow_player:"))
async def ref_yellow_record(call: CallbackQuery, session: AsyncSession,
                            player: Player | None):
    if not _is_referee(call.from_user.id, player):
        await call.answer("⛔", show_alert=True)
        return

    parts = call.data.split(":")
    match_id, player_id, team_id = int(parts[1]), int(parts[2]), int(parts[3])
    match = await _load_match(session, match_id)
    carded = await session.get(Player, player_id)
    if not match or not carded:
        await call.answer("❌ Ошибка", show_alert=True)
        return

    session.add(Card(
        match_id=match_id, player_id=player_id, team_id=team_id,
        card_type=CardType.YELLOW, issued_at=datetime.now(),
    ))
    await session.commit()
    match = await _load_match(session, match_id)

    await call.answer(f"🟨 ЖК: {carded.name}", show_alert=True)
    await call.message.edit_text(
        _match_panel_text(match),
        reply_markup=referee_match_kb(
            match_id,
            is_started=match.status == MatchStatus.IN_PROGRESS,
            is_finished=False,
        )
    )


# ─────────────────────────────────────────────
#  КРАСНАЯ КАРТОЧКА
# ─────────────────────────────────────────────

@router.callback_query(F.data.startswith("ref_red:"))
async def ref_red_select_team(call: CallbackQuery, session: AsyncSession,
                               player: Player | None):
    if not _is_referee(call.from_user.id, player):
        await call.answer("⛔", show_alert=True)
        return
    await call.answer()

    match_id = int(call.data.split(":")[1])
    match = await _load_match(session, match_id)
    if not match:
        return

    await call.message.edit_text(
        "🟥 <b>Красная карточка</b>\n\nИз какой команды?",
        reply_markup=select_team_kb(
            match_id, "ref_red_team",
            match.team_home_id, match.team_home.name,
            match.team_away_id, match.team_away.name,
        )
    )


@router.callback_query(F.data.startswith("ref_red_team:"))
async def ref_red_select_player(call: CallbackQuery, session: AsyncSession,
                                 player: Player | None):
    if not _is_referee(call.from_user.id, player):
        await call.answer("⛔", show_alert=True)
        return
    await call.answer()

    _, match_id_str, team_id_str = call.data.split(":")
    match_id, team_id = int(match_id_str), int(team_id_str)
    match = await _load_match(session, match_id)
    if not match:
        return

    team_name = match.team_home.name if team_id == match.team_home_id else match.team_away.name
    players = await _get_team_players(session, team_id)
    if not players:
        players = await _get_attendees(session, match.game_day_id)

    await call.message.edit_text(
        f"🟥 <b>Красная карточка — {team_name}</b>\n\nКому?",
        reply_markup=select_player_kb(match_id, "ref_red_player", team_id, players)
    )


@router.callback_query(F.data.startswith("ref_red_player:"))
async def ref_red_record(call: CallbackQuery, session: AsyncSession,
                         player: Player | None):
    if not _is_referee(call.from_user.id, player):
        await call.answer("⛔", show_alert=True)
        return

    parts = call.data.split(":")
    match_id, player_id, team_id = int(parts[1]), int(parts[2]), int(parts[3])
    match = await _load_match(session, match_id)
    carded = await session.get(Player, player_id)
    if not match or not carded:
        await call.answer("❌ Ошибка", show_alert=True)
        return

    session.add(Card(
        match_id=match_id, player_id=player_id, team_id=team_id,
        card_type=CardType.RED, issued_at=datetime.now(),
    ))
    await session.commit()
    match = await _load_match(session, match_id)

    # Check if player already had a red in an earlier match of this game_day
    prev_red_result = await session.execute(
        select(Card)
        .join(Match, Match.id == Card.match_id)
        .where(
            Match.game_day_id == match.game_day_id,
            Card.player_id == player_id,
            Card.card_type == CardType.RED,
            Match.id != match_id,
        )
        .limit(1)
    )
    already_banned = prev_red_result.scalar_one_or_none() is not None
    if already_banned:
        disq_msg = f"🟥 КК: {carded.name}\n⛔ Уже дисквалифицирован — пропускает этот и следующий матч!"
    else:
        disq_msg = f"🟥 КК: {carded.name} — дисквалификация на этот и следующий матч!"
    await call.answer(disq_msg, show_alert=True)
    await call.message.edit_text(
        _match_panel_text(match),
        reply_markup=referee_match_kb(
            match_id,
            is_started=match.status == MatchStatus.IN_PROGRESS,
            is_finished=False,
        )
    )


# ─────────────────────────────────────────────
#  ЗАВЕРШИТЬ МАТЧ
# ─────────────────────────────────────────────

@router.callback_query(F.data.startswith("ref_finish:"))
async def ref_finish_confirm(call: CallbackQuery, session: AsyncSession,
                             player: Player | None):
    if not _is_referee(call.from_user.id, player):
        await call.answer("⛔", show_alert=True)
        return
    await call.answer()

    match_id = int(call.data.split(":")[1])
    match = await _load_match(session, match_id)
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
    match = await _load_match(session, match_id)
    if not match:
        return

    match.status = MatchStatus.FINISHED
    match.finished_at = datetime.now()
    await session.commit()
    match = await _load_match(session, match_id)

    try:
        scheduler.remove_job(f"timer_tick_{match_id}")
    except Exception:
        pass
    _active_timers.pop(match_id, None)

    home = match.team_home.name
    away = match.team_away.name

    result_text = (
        f"🏁 <b>Финальный счёт</b>\n\n"
        f"⚽ <b>{home}  {match.score_home} : {match.score_away}  {away}</b>\n"
    )

    goals_by_team: dict[int, list[str]] = {}
    for g in sorted(match.goals, key=lambda x: x.scored_at):
        own = " (авт.)" if g.goal_type == GoalType.OWN_GOAL else ""
        goals_by_team.setdefault(g.team_id, []).append(f"{g.player.name}{own}")

    if goals_by_team.get(match.team_home_id):
        result_text += f"\n🔴 {home}: " + ", ".join(goals_by_team[match.team_home_id])
    if goals_by_team.get(match.team_away_id):
        result_text += f"\n🔵 {away}: " + ", ".join(goals_by_team[match.team_away_id])

    if match.cards:
        result_text += "\n\n<b>Карточки:</b>"
        for c in sorted(match.cards, key=lambda x: x.issued_at):
            emoji = "🟨" if c.card_type == CardType.YELLOW else "🟥"
            result_text += f"\n  {emoji} {c.player.name}"

    await call.message.edit_text(
        result_text,
        reply_markup=referee_match_kb(match_id, is_started=True, is_finished=True)
    )

    # Разослать результаты участникам
    game_day_players = await _get_attendees(session, match.game_day_id)
    notified = 0
    for p in game_day_players:
        try:
            await bot.send_message(p.telegram_id, result_text)
            notified += 1
        except Exception as e:
            logger.warning(f"Cannot send match result to {p.telegram_id}: {e}")

    if notified:
        await call.message.answer(f"📢 Результаты отправлены {notified} игрокам.")


# ─────────────────────────────────────────────
#  Заглушка
# ─────────────────────────────────────────────

@router.callback_query(F.data == "noop")
async def noop(call: CallbackQuery):
    await call.answer()


# ─────────────────────────────────────────────
#  Статус таймера
# ─────────────────────────────────────────────

@router.callback_query(F.data.startswith("ref_timer:"))
async def ref_timer_status(call: CallbackQuery, session: AsyncSession,
                           player: Player | None):
    if not _is_referee(call.from_user.id, player):
        await call.answer("⛔", show_alert=True)
        return

    match_id = int(call.data.split(":")[1])

    data = _active_timers.get(match_id)
    if data:
        elapsed = datetime.now() - data["started_at"]
        remaining = timedelta(minutes=data["duration_min"]) - elapsed
        rem_sec_total = max(int(remaining.total_seconds()), 0)
        rem_min = rem_sec_total // 60
        rem_sec = rem_sec_total % 60
        await call.answer(f"⏱ Осталось: {rem_min}:{rem_sec:02d}")
    else:
        await call.answer()

    match = await _load_match(session, match_id)
    if not match:
        return
    await call.message.edit_text(
        _match_panel_text(match),
        reply_markup=referee_match_kb(
            match_id,
            is_started=match.status == MatchStatus.IN_PROGRESS,
            is_finished=match.status == MatchStatus.FINISHED,
        )
    )


# ─────────────────────────────────────────────
#  Отмена FSM судьи
# ─────────────────────────────────────────────

@router.message(
    Command("cancel"),
    StateFilter(
        RefereeMatchFSM.waiting_team1, RefereeMatchFSM.waiting_team1_players,
        RefereeMatchFSM.waiting_team2, RefereeMatchFSM.waiting_team2_players,
        RefereeMatchFSM.waiting_pick_team1, RefereeMatchFSM.waiting_pick_team2,
        RefereeMatchFSM.waiting_stage, RefereeMatchFSM.waiting_format,
        RefereeMatchFSM.waiting_duration, RefereeMatchFSM.waiting_goals_count,
        RefereeTeamSetupFSM.waiting_team_name, RefereeTeamSetupFSM.waiting_team_players,
    )
)
async def referee_fsm_cancel(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "❌ Действие отменено.\n\n"
        "📋 /referee — вернуться в панель судьи"
    )


# ─────────────────────────────────────────────
#  Выбор стадии матча
# ─────────────────────────────────────────────

@router.callback_query(
    F.data.startswith("ref_stage:"),
    StateFilter(RefereeMatchFSM.waiting_stage)
)
async def ref_pick_stage(call: CallbackQuery, state: FSMContext, player: Player | None):
    if not _is_referee(call.from_user.id, player):
        await call.answer("⛔", show_alert=True)
        return
    await call.answer()

    stage_str = call.data.split(":")[1]  # group / semifinal / third_place / final
    await state.update_data(match_stage_val=stage_str)
    await state.set_state(RefereeMatchFSM.waiting_format)

    stage_label = MATCH_STAGE_LABELS.get(MatchStage(stage_str), stage_str)
    await call.message.edit_text(
        f"✅ Стадия: <b>{stage_label}</b>\n\nВыбери формат матча:",
        reply_markup=pick_format_kb()
    )


# ─────────────────────────────────────────────
#  Выбор формата матча
# ─────────────────────────────────────────────

@router.callback_query(
    F.data.startswith("ref_fmt:"),
    StateFilter(RefereeMatchFSM.waiting_format)
)
async def ref_pick_format(call: CallbackQuery, state: FSMContext, player: Player | None):
    if not _is_referee(call.from_user.id, player):
        await call.answer("⛔", show_alert=True)
        return
    await call.answer()

    fmt = call.data.split(":")[1]   # "time" или "goals"
    await state.update_data(match_format=fmt)

    if fmt == "time":
        await state.set_state(RefereeMatchFSM.waiting_duration)
        await call.message.edit_text(
            "⏱ <b>Формат: по времени</b>\n\n"
            "Длительность матча (в минутах)?\n"
            "<i>Введи число, например: 6</i>"
        )
    else:
        await state.set_state(RefereeMatchFSM.waiting_goals_count)
        await call.message.edit_text(
            "🥅 <b>Формат: до N голов</b>\n\n"
            "Сколько голов нужно забить для победы?\n"
            "<i>Введи число, например: 3</i>"
        )


@router.message(RefereeMatchFSM.waiting_goals_count)
async def ref_goals_count(message: Message, state: FSMContext, session: AsyncSession):
    try:
        n = int(message.text.strip())
        if n < 1 or n > 20:
            raise ValueError
    except ValueError:
        await message.answer("❌ Введи число от 1 до 20:")
        return

    await state.update_data(goals_to_win=n)
    # Создать матч сразу (duration_min не нужен для этого формата, ставим 0)
    await state.update_data(duration_min=0)
    await _create_match_from_state(message, state, session)


# ─────────────────────────────────────────────
#  Выбор из существующих команд (создание матча)
# ─────────────────────────────────────────────

@router.callback_query(
    F.data.startswith("ref_pick_t1:"),
    StateFilter(RefereeMatchFSM.waiting_pick_team1)
)
async def ref_pick_team1(call: CallbackQuery, state: FSMContext,
                         player: Player | None, session: AsyncSession):
    if not _is_referee(call.from_user.id, player):
        await call.answer("⛔", show_alert=True)
        return
    await call.answer()

    _, gd_id_str, team1_id_str = call.data.split(":")
    game_day_id = int(gd_id_str)
    team1_id = int(team1_id_str)

    await state.update_data(existing_team1_id=team1_id)
    await state.set_state(RefereeMatchFSM.waiting_pick_team2)

    teams_result = await session.execute(
        select(Team).where(Team.game_day_id == game_day_id)
    )
    teams = teams_result.scalars().all()
    team1 = next((t for t in teams if t.id == team1_id), None)

    await call.message.edit_text(
        f"✅ Команда 1: <b>{team1.color_emoji} {team1.name}</b>\n\n"
        "Шаг 2 из 3\n\nВыбери <b>Команду 2</b>:",
        reply_markup=pick_team_kb("ref_pick_t2", game_day_id, teams, exclude_id=team1_id)
    )


@router.callback_query(
    F.data.startswith("ref_pick_t2:"),
    StateFilter(RefereeMatchFSM.waiting_pick_team2)
)
async def ref_pick_team2(call: CallbackQuery, state: FSMContext,
                         player: Player | None, session: AsyncSession):
    if not _is_referee(call.from_user.id, player):
        await call.answer("⛔", show_alert=True)
        return
    await call.answer()

    _, gd_id_str, team2_id_str = call.data.split(":")
    team2_id = int(team2_id_str)

    await state.update_data(existing_team2_id=team2_id)
    await state.set_state(RefereeMatchFSM.waiting_stage)

    data = await state.get_data()
    team1 = await session.get(Team, data["existing_team1_id"])
    team2 = await session.get(Team, team2_id)

    await call.message.edit_text(
        f"✅ {team1.color_emoji} {team1.name} vs {team2.color_emoji} {team2.name}\n\n"
        "Шаг 3 из 4\n\nВыбери <b>стадию матча</b>:",
        reply_markup=pick_stage_kb()
    )


# ─────────────────────────────────────────────
#  Составы команд — предварительная настройка
# ─────────────────────────────────────────────

@router.callback_query(F.data.startswith("ref_setup_teams:"))
async def ref_setup_teams(call: CallbackQuery, player: Player | None,
                          session: AsyncSession, state: FSMContext):
    if not _is_referee(call.from_user.id, player):
        await call.answer("⛔", show_alert=True)
        return
    await call.answer()
    await state.clear()

    game_day_id = int(call.data.split(":")[1])
    teams_result = await session.execute(
        select(Team).where(Team.game_day_id == game_day_id)
    )
    teams = teams_result.scalars().all()

    if not teams:
        await call.message.edit_text(
            "👥 <b>Составы команд</b>\n\n"
            "Команд ещё нет. Создай первую команду:",
            reply_markup=teams_list_kb(game_day_id, [])
        )
        return

    lines = ["👥 <b>Составы команд</b>\n"]
    for team in teams:
        tp_result = await session.execute(
            select(TeamPlayer).options(selectinload(TeamPlayer.player))
            .where(TeamPlayer.team_id == team.id)
        )
        tp_list = tp_result.scalars().all()
        names = ", ".join(tp.player.name for tp in tp_list) or "—"
        lines.append(f"{team.color_emoji} <b>{team.name}</b> ({len(tp_list)} чел.): {names}")

    await call.message.edit_text(
        "\n".join(lines),
        reply_markup=teams_list_kb(game_day_id, teams)
    )


@router.callback_query(F.data.startswith("ref_add_team:"))
async def ref_add_team(call: CallbackQuery, player: Player | None,
                       state: FSMContext):
    if not _is_referee(call.from_user.id, player):
        await call.answer("⛔", show_alert=True)
        return
    await call.answer()

    game_day_id = int(call.data.split(":")[1])
    await state.update_data(game_day_id=game_day_id, selected_player_ids=[])
    await state.set_state(RefereeTeamSetupFSM.waiting_team_name)

    await call.message.edit_text(
        "👥 <b>Новая команда</b>\n\n"
        "Введи название команды:\n"
        "<i>Например: Красные, Команда А, Барса…</i>"
    )


@router.message(RefereeTeamSetupFSM.waiting_team_name)
async def ref_setup_team_name(message: Message, state: FSMContext,
                               session: AsyncSession):
    name = message.text.strip() if message.text else ""
    if not name:
        await message.answer("❌ Название не может быть пустым.")
        return

    await state.update_data(setup_team_name=name, selected_player_ids=[])
    data = await state.get_data()

    attendees = await _get_attendees(session, data["game_day_id"])
    if not attendees:
        await message.answer(
            "⚠️ На этот игровой день ещё никто не записался.\n"
            "Создай команду без игроков и добавь их позже."
        )
        # Сохранить пустую команду сразу
        color_emojis = ["🔴", "🔵", "🟢", "🟡", "🟠", "🟣"]
        teams_count_result = await session.execute(
            select(Team).where(Team.game_day_id == data["game_day_id"])
        )
        cnt = len(teams_count_result.scalars().all())
        emoji = color_emojis[cnt % len(color_emojis)]
        team = Team(game_day_id=data["game_day_id"], name=name, color_emoji=emoji)
        session.add(team)
        await session.commit()

        teams_result = await session.execute(
            select(Team).where(Team.game_day_id == data["game_day_id"])
        )
        teams = teams_result.scalars().all()
        await state.clear()
        await message.answer(
            f"✅ Команда <b>{name}</b> создана (без игроков).",
            reply_markup=teams_list_kb(data["game_day_id"], teams)
        )
        return

    available = [{"id": p.id, "name": p.name} for p in attendees]
    await state.update_data(available_players=available)
    await state.set_state(RefereeTeamSetupFSM.waiting_team_players)

    await message.answer(
        f"✅ Название: <b>{name}</b>\n\n"
        "👥 Выбери игроков этой команды из записавшихся:\n"
        "<i>Нажимай имена, потом «Готово»</i>",
        reply_markup=team_players_select_kb(available, [], name)
    )


@router.callback_query(F.data.startswith("ref_team_detail:"))
async def ref_team_detail(call: CallbackQuery, player: Player | None,
                          session: AsyncSession):
    """Просмотр состава конкретной команды."""
    if not _is_referee(call.from_user.id, player):
        await call.answer("⛔", show_alert=True)
        return
    await call.answer()

    _, gd_id_str, team_id_str = call.data.split(":")
    game_day_id = int(gd_id_str)
    team_id = int(team_id_str)

    team = await session.get(Team, team_id)
    tp_result = await session.execute(
        select(TeamPlayer).options(selectinload(TeamPlayer.player))
        .where(TeamPlayer.team_id == team_id)
    )
    tp_list = tp_result.scalars().all()

    lines = [f"{team.color_emoji} <b>{team.name}</b>\n"]
    for i, tp in enumerate(tp_list, 1):
        lines.append(f"{i}. {tp.player.name}")

    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(
        text="🔙 К составам",
        callback_data=f"ref_setup_teams:{game_day_id}"
    ))

    await call.message.edit_text("\n".join(lines), reply_markup=builder.as_markup())


# ─────────────────────────────────────────────
#  Таблица турнира
# ─────────────────────────────────────────────

async def _compute_standings(session: AsyncSession, game_day_id: int) -> list[dict]:
    """Подсчёт очков: В=3, Н=1, П=0."""
    result = await session.execute(
        select(Match)
        .options(selectinload(Match.team_home), selectinload(Match.team_away))
        .where(Match.game_day_id == game_day_id, Match.status == MatchStatus.FINISHED)
    )
    matches = result.scalars().all()

    stats: dict[int, dict] = {}
    for match in matches:
        for team, gf, ga in [
            (match.team_home, match.score_home, match.score_away),
            (match.team_away, match.score_away, match.score_home),
        ]:
            if team.id not in stats:
                stats[team.id] = {
                    "name": team.name, "emoji": team.color_emoji,
                    "W": 0, "D": 0, "L": 0, "GF": 0, "GA": 0, "GP": 0,
                }
            s = stats[team.id]
            s["GP"] += 1
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

    return sorted(stats.values(), key=lambda x: (-x["Pts"], -(x["GF"] - x["GA"]), -x["GF"]))


@router.callback_query(F.data.startswith("ref_standings:"))
async def ref_standings(call: CallbackQuery, player: Player | None,
                        session: AsyncSession):
    if not _is_referee(call.from_user.id, player):
        await call.answer("⛔", show_alert=True)
        return
    await call.answer()

    game_day_id = int(call.data.split(":")[1])

    # Load ALL matches with goals/cards
    all_matches_result = await session.execute(
        select(Match)
        .options(
            selectinload(Match.team_home),
            selectinload(Match.team_away),
            selectinload(Match.goals).selectinload(Goal.player),
        )
        .where(Match.game_day_id == game_day_id)
        .order_by(Match.id)
    )
    all_matches = all_matches_result.scalars().all()

    from aiogram.utils.keyboard import InlineKeyboardBuilder
    from aiogram.types import InlineKeyboardButton
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(
        text="🔙 К игровому дню",
        callback_data=f"ref_gd:{game_day_id}"
    ))

    if not all_matches:
        await call.message.edit_text(
            "📊 <b>Таблица турнира</b>\n\nМатчей ещё нет.",
            reply_markup=builder.as_markup()
        )
        return

    # ── Standings (group stage only) ──
    standings = await _compute_standings(session, game_day_id)
    lines = ["📊 <b>Таблица турнира</b>\n"]
    if standings:
        lines.append("<code>№  Команда          И  В  Н  П  ГЗ ГП  О</code>")
        lines.append("<code>" + "─" * 42 + "</code>")
        for i, s in enumerate(standings, 1):
            name = s["name"][:14].ljust(14)
            row = (
                f"{i:<3}{name} "
                f"{s['GP']:<3}{s['W']:<3}{s['D']:<3}{s['L']:<3}"
                f"{s['GF']:<3}{s['GA']:<3}{s['Pts']}"
            )
            lines.append(f"<code>{row}</code>")

    # ── All matches grouped by stage ──
    stage_order = ["group", "semifinal", "third_place", "final"]
    stage_buckets: dict[str, list] = {s: [] for s in stage_order}
    for m in all_matches:
        stage_key = m.match_stage or "group"
        if stage_key not in stage_buckets:
            stage_buckets[stage_key] = []
        stage_buckets[stage_key].append(m)

    for stage_key in stage_order:
        bucket = stage_buckets.get(stage_key, [])
        if not bucket:
            continue
        try:
            label = MATCH_STAGE_LABELS[MatchStage(stage_key)]
        except (ValueError, KeyError):
            label = stage_key
        lines.append(f"\n<b>{label}:</b>")
        for m in bucket:
            status_icon = "✅" if m.status == MatchStatus.FINISHED else (
                "▶️" if m.status == MatchStatus.IN_PROGRESS else "⏳"
            )
            lines.append(
                f"{status_icon} {m.team_home.name} "
                f"<b>{m.score_home}:{m.score_away}</b> "
                f"{m.team_away.name}"
            )

    # ── Top scorers (бомбардиры) ──
    from collections import Counter
    goal_counts: Counter = Counter()
    for m in all_matches:
        for g in m.goals:
            if g.goal_type != GoalType.OWN_GOAL and g.player:
                goal_counts[g.player.name] += 1

    if goal_counts:
        lines.append("\n⚽ <b>Бомбардиры:</b>")
        for i, (name, cnt) in enumerate(goal_counts.most_common(5), 1):
            suffix = "гол" if cnt == 1 else ("гола" if cnt <= 4 else "голов")
            lines.append(f"  {i}. {name} — {cnt} {suffix}")

    await call.message.edit_text("\n".join(lines), reply_markup=builder.as_markup())


# ─────────────────────────────────────────────
#  Замена игрока
# ─────────────────────────────────────────────

@router.callback_query(F.data.startswith("ref_sub:"))
async def ref_sub_select_team(call: CallbackQuery, session: AsyncSession,
                               player: Player | None):
    if not _is_referee(call.from_user.id, player):
        await call.answer("⛔", show_alert=True)
        return
    await call.answer()

    match_id = int(call.data.split(":")[1])
    match = await _load_match(session, match_id)
    if not match:
        return

    await call.message.edit_text(
        "🔄 <b>Замена</b>\n\nВ какой команде производится замена?",
        reply_markup=select_team_kb(
            match_id, "ref_sub_team",
            match.team_home_id, match.team_home.name,
            match.team_away_id, match.team_away.name,
        )
    )


@router.callback_query(F.data.startswith("ref_sub_team:"))
async def ref_sub_select_out(call: CallbackQuery, session: AsyncSession,
                              player: Player | None):
    if not _is_referee(call.from_user.id, player):
        await call.answer("⛔", show_alert=True)
        return
    await call.answer()

    _, match_id_str, team_id_str = call.data.split(":")
    match_id = int(match_id_str)
    team_id = int(team_id_str)

    match = await _load_match(session, match_id)
    if not match:
        return

    team_name = match.team_home.name if team_id == match.team_home_id else match.team_away.name
    players = await _get_team_players(session, team_id)
    if not players:
        players = await _get_attendees(session, match.game_day_id)

    await call.message.edit_text(
        f"🔄 <b>Замена — {team_name}</b>\n\nКто <b>выходит</b> (покидает поле)?",
        reply_markup=sub_player_out_kb(match_id, team_id, players)
    )


@router.callback_query(F.data.startswith("ref_sub_out:"))
async def ref_sub_select_in(call: CallbackQuery, session: AsyncSession,
                             player: Player | None):
    if not _is_referee(call.from_user.id, player):
        await call.answer("⛔", show_alert=True)
        return
    await call.answer()

    parts = call.data.split(":")
    match_id = int(parts[1])
    team_id = int(parts[2])
    player_out_id = int(parts[3])

    match = await _load_match(session, match_id)
    player_out = await session.get(Player, player_out_id)
    if not match or not player_out:
        await call.answer("❌ Ошибка", show_alert=True)
        return

    team_name = match.team_home.name if team_id == match.team_home_id else match.team_away.name

    # Доступны для замены:
    # 1. Записавшиеся на игровой день, но не в командах (скамейка)
    # 2. Игроки из ДРУГОЙ команды этого матча (Т-023: взять из противника/партнёра)
    all_attendees = await _get_attendees(session, match.game_day_id)
    team_home_players = await _get_team_players(session, match.team_home_id)
    team_away_players = await _get_team_players(session, match.team_away_id)

    this_team_ids = {p.id for p in (team_home_players if team_id == match.team_home_id else team_away_players)}
    # Исключаем только игрока из ЭТОЙ команды (кроме выходящего), доступны все остальные
    available_subs = [
        p for p in all_attendees
        if p.id != player_out_id and p.id not in this_team_ids
    ]

    if not available_subs:
        await call.answer("⚠️ Нет доступных игроков для замены.", show_alert=True)
        return

    # Пометить игроков из другой команды
    other_team_ids = {p.id for p in (team_away_players if team_id == match.team_home_id else team_home_players)}

    await call.message.edit_text(
        f"🔄 <b>Замена — {team_name}</b>\n\n"
        f"Выходит: <b>{player_out.name}</b>\n\n"
        "Кто <b>выходит на поле</b>?\n"
        "<i>* — игрок из другой команды</i>",
        reply_markup=sub_player_in_kb(match_id, team_id, player_out_id, available_subs,
                                      other_team_ids=other_team_ids)
    )


@router.callback_query(F.data.startswith("ref_sub_in:"))
async def ref_sub_execute(call: CallbackQuery, session: AsyncSession,
                          player: Player | None):
    if not _is_referee(call.from_user.id, player):
        await call.answer("⛔", show_alert=True)
        return

    parts = call.data.split(":")
    match_id = int(parts[1])
    team_id = int(parts[2])
    player_out_id = int(parts[3])
    player_in_id = int(parts[4])

    match = await _load_match(session, match_id)
    player_out = await session.get(Player, player_out_id)
    player_in = await session.get(Player, player_in_id)
    if not match or not player_out or not player_in:
        await call.answer("❌ Ошибка", show_alert=True)
        return

    # Удалить выходящего из его команды
    from sqlalchemy import delete as sql_delete
    await session.execute(
        sql_delete(TeamPlayer).where(
            TeamPlayer.team_id == team_id,
            TeamPlayer.player_id == player_out_id,
        )
    )
    # Если входящий был в другой команде — убрать его оттуда тоже
    await session.execute(
        sql_delete(TeamPlayer).where(
            TeamPlayer.player_id == player_in_id,
        )
    )
    session.add(TeamPlayer(team_id=team_id, player_id=player_in_id))
    await session.commit()
    match = await _load_match(session, match_id)

    team_name = match.team_home.name if team_id == match.team_home_id else match.team_away.name
    await call.answer(
        f"✅ {player_out.name} → {player_in.name} ({team_name})",
        show_alert=True
    )
    await call.message.edit_text(
        _match_panel_text(match),
        reply_markup=referee_match_kb(
            match_id,
            is_started=match.status == MatchStatus.IN_PROGRESS,
            is_finished=match.status == MatchStatus.FINISHED,
        )
    )

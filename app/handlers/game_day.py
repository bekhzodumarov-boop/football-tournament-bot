from datetime import datetime, timedelta
import logging
import asyncio
from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database.models import (
    GameDay, GameDayStatus, Attendance, AttendanceResponse,
    Player, MatchFormat, PlayerLeague, PlayerStatus,
    Match, MatchStatus, Goal, GoalType, Card, CardType,
    MatchStage, MATCH_STAGE_LABELS,
)
from app.keyboards.game_day import join_game_kb, join_confirm_kb, game_day_action_kb
from app.data.reglament import REGLAMENT_AGREEMENT, REGLAMENT_AGREEMENT_EN
from app.reminders import schedule_reminders, schedule_announcement
from app.locales.texts import t, t_g

logger = logging.getLogger(__name__)
router = Router()


class CreateGameDayFSM(StatesGroup):
    waiting_date = State()
    waiting_location = State()
    waiting_limit = State()


# ── Cancel регистрируется ПЕРВЫМ — перехватывает раньше FSM-хендлеров ──

@router.message(Command("cancel"))
async def gameday_cancel(message: Message, state: FSMContext):
    current = await state.get_state()
    if current is None:
        return  # передать другим роутерам
    await state.clear()
    from app.keyboards.main_menu import admin_menu_kb
    await message.answer(
        "❌ Создание игрового дня отменено.",
        reply_markup=admin_menu_kb()
    )


# ---------- Вспомогательная функция: сформировать share_url для игры ----------

def _make_share_url(gd) -> str:
    """Ссылка для кнопки «Поделиться» — открывает Telegram share-диалог."""
    import urllib.parse
    bot_url = f"https://t.me/{settings.BOT_USERNAME}?start=game_{gd.id}"
    share_text = (
        f"🏆 {gd.display_name}\n"
        f"📅 {gd.scheduled_at.strftime('%d.%m.%Y %H:%M')}\n"
        f"📍 {gd.location}\n"
        f"👥 Лимит: {gd.player_limit} чел."
    )
    return f"https://t.me/share/url?url={urllib.parse.quote(bot_url)}&text={urllib.parse.quote(share_text)}"


# ---------- Вспомогательная функция: текст карточки игры ----------

def _game_card_text(gd, player: Player | None, player_atts: dict) -> str:
    """Формирует текст с информацией об игровом дне."""
    registered = sum(1 for a in gd.attendances if a.response == AttendanceResponse.YES)
    waitlist = sum(1 for a in gd.attendances if a.response == AttendanceResponse.WAITLIST)
    spots_left = gd.player_limit - registered

    player_status = ""
    if player:
        att = player_atts.get(gd.id)
        _gender = getattr(player, 'gender', 'm') or 'm'
        if att and att.response == AttendanceResponse.YES:
            _signed = "записана" if _gender == 'f' else "записан"
            player_status = f"\n✅ <b>Ты {_signed}</b>"
            if att.confirmed_final:
                player_status += " (подтверждено)"
        elif att and att.response == AttendanceResponse.WAITLIST:
            waitlist_list = sorted(
                [a for a in gd.attendances if a.response == AttendanceResponse.WAITLIST],
                key=lambda a: a.responded_at or datetime.min,
            )
            pos = next((i + 1 for i, a in enumerate(waitlist_list) if a.player_id == player.id), "?")
            player_status = f"\n📋 <b>Ты в листе ожидания (#{pos})</b>"
        elif att and att.response == AttendanceResponse.NO:
            _declined = "отказалась" if _gender == 'f' else "отказался"
            player_status = f"\n❌ Ты {_declined} от этой игры"

    status_icon = "🔴 LIVE" if gd.status == GameDayStatus.IN_PROGRESS else "📅"
    name_line = f"🏆 <b>{gd.display_name}</b>\n" if gd.tournament_number else ""
    return (
        f"{name_line}"
        f"{status_icon} {gd.scheduled_at.strftime('%d.%m.%Y %H:%M')}\n"
        f"📍 {gd.location}\n"
        f"👥 Записалось: <b>{registered}/{gd.player_limit}</b>"
        + (f" (свободно: {spots_left})" if spots_left > 0 else " (<b>мест нет</b>)")
        + (f"\n📋 Ожидание: {waitlist} чел." if waitlist > 0 else "")
        + player_status
    )


# ---------- Список ближайших игр ----------

@router.callback_query(F.data == "next_game")
@router.message(Command("game"))
async def show_next_game(event, session: AsyncSession, player: Player | None):
    is_callback = isinstance(event, CallbackQuery)
    if is_callback:
        await event.answer()
        msg = event.message
    else:
        msg = event

    lang = getattr(player, 'language', None) or 'ru' if player else 'ru'
    league_id = player.league_id if player else None

    query = (
        select(GameDay)
        .options(selectinload(GameDay.attendances))
        .where(GameDay.status.in_([
            GameDayStatus.ANNOUNCED, GameDayStatus.CLOSED, GameDayStatus.IN_PROGRESS,
        ]))
        .order_by(GameDay.scheduled_at)
    )
    if league_id is not None:
        query = query.where(GameDay.league_id == league_id)

    result = await session.execute(query)
    game_days = result.scalars().all()

    if not game_days:
        text = "📅 Активных игр пока нет. Следи за анонсами!"
        kb_builder = InlineKeyboardBuilder()
        kb_builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="main_menu"))
        if is_callback:
            await msg.edit_text(text, reply_markup=kb_builder.as_markup())
        else:
            await msg.answer(text, reply_markup=kb_builder.as_markup())
        return

    # Если одна игра — сразу показать детали
    if len(game_days) == 1:
        gd = game_days[0]
        player_atts: dict[int, Attendance] = {}
        if player:
            att_res = await session.execute(
                select(Attendance).where(
                    Attendance.game_day_id == gd.id,
                    Attendance.player_id == player.id,
                )
            )
            for att in att_res.scalars().all():
                player_atts[att.game_day_id] = att
        text = _game_card_text(gd, player, player_atts)
        kb = join_game_kb(gd.id, gd.is_open, lang,
                          webapp_url=settings.WEBAPP_URL,
                          share_url=_make_share_url(gd))
        if is_callback:
            await msg.edit_text(text, reply_markup=kb, parse_mode="HTML")
        else:
            await msg.answer(text, reply_markup=kb, parse_mode="HTML")
        return

    # Несколько игр — показать список
    text = "📅 <b>Ближайшие игры:</b>\n\nВыбери игру, чтобы посмотреть подробности и записаться."
    kb_builder = InlineKeyboardBuilder()
    for gd in game_days:
        registered = sum(1 for a in gd.attendances if a.response == AttendanceResponse.YES)
        status_icon = "🔴" if gd.status == GameDayStatus.IN_PROGRESS else ("🔒" if not gd.is_open else "✅")
        label = f"{status_icon} {gd.display_name} — {gd.scheduled_at.strftime('%d.%m')} ({registered}/{gd.player_limit})"
        kb_builder.row(InlineKeyboardButton(text=label, callback_data=f"game_detail:{gd.id}"))
    kb_builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="main_menu"))

    if is_callback:
        await msg.edit_text(text, reply_markup=kb_builder.as_markup(), parse_mode="HTML")
    else:
        await msg.answer(text, reply_markup=kb_builder.as_markup(), parse_mode="HTML")


# ---------- Детали одной игры (из списка или deep link) ----------

@router.callback_query(F.data.startswith("game_detail:"))
async def game_detail(call: CallbackQuery, session: AsyncSession, player: Player | None):
    await call.answer()
    game_day_id = int(call.data.split(":")[1])
    lang = getattr(player, 'language', None) or 'ru' if player else 'ru'

    gd = await session.get(GameDay, game_day_id, options=[selectinload(GameDay.attendances)])
    if not gd:
        await call.message.edit_text("❌ Игра не найдена.")
        return

    player_atts: dict[int, Attendance] = {}
    if player:
        att_res = await session.execute(
            select(Attendance).where(
                Attendance.game_day_id == game_day_id,
                Attendance.player_id == player.id,
            )
        )
        for att in att_res.scalars().all():
            player_atts[att.game_day_id] = att

    text = _game_card_text(gd, player, player_atts)
    kb = join_game_kb(gd.id, gd.is_open, lang,
                      webapp_url=settings.WEBAPP_URL,
                      share_url=_make_share_url(gd),
                      back_to_list=True)
    await call.message.edit_text(text, reply_markup=kb, parse_mode="HTML")


# ---------- Таблица турнира (для игроков) ----------

@router.callback_query(F.data.startswith("gd_standings:"))
async def gd_standings(call: CallbackQuery, session: AsyncSession,
                       player: Player | None):
    await call.answer()
    game_day_id = int(call.data.split(":")[1])

    from collections import Counter
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    from aiogram.types import InlineKeyboardButton

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

    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(
        text="🖼 Картинка таблицы",
        callback_data=f"gd_standings_img:{game_day_id}"
    ))
    builder.row(InlineKeyboardButton(
        text="🔙 Назад",
        callback_data="next_game"
    ))

    if not all_matches:
        await call.message.edit_text(
            "📊 <b>Таблица турнира</b>\n\nМатчей ещё нет.",
            reply_markup=builder.as_markup()
        )
        return

    # ── Подсчёт очков (только групповой этап) ──
    stats: dict[int, dict] = {}
    for match in all_matches:
        if match.status != MatchStatus.FINISHED:
            continue
        stage = match.match_stage or "group"
        if stage != "group":
            continue
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
            s["GP"] += 1; s["GF"] += gf; s["GA"] += ga
            if gf > ga: s["W"] += 1
            elif gf == ga: s["D"] += 1
            else: s["L"] += 1
    for s in stats.values():
        s["Pts"] = s["W"] * 3 + s["D"]
    standings = sorted(stats.values(), key=lambda x: (-x["Pts"], -(x["GF"] - x["GA"]), -x["GF"]))

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

    # ── Матчи по стадиям ──
    stage_order = ["group", "semifinal", "third_place", "final"]
    stage_buckets: dict[str, list] = {s: [] for s in stage_order}
    for m in all_matches:
        stage_key = m.match_stage or "group"
        stage_buckets.setdefault(stage_key, []).append(m)

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
            icon = "✅" if m.status == MatchStatus.FINISHED else (
                "▶️" if m.status == MatchStatus.IN_PROGRESS else "⏳"
            )
            lines.append(
                f"{icon} {m.team_home.name} "
                f"<b>{m.score_home}:{m.score_away}</b> "
                f"{m.team_away.name}"
            )

    # ── Бомбардиры ──
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


# ---------- Предварительный экран — согласие с Регламентом ----------

@router.callback_query(F.data.startswith("join_pre:"))
async def join_pre(call: CallbackQuery, player: Player | None, session: AsyncSession):
    await call.answer()
    game_day_id = int(call.data.split(":")[1])

    if not player:
        await call.message.answer("❌ Сначала зарегистрируйся: /register")
        return

    # Проверить — не записан ли уже
    existing = await session.execute(
        select(Attendance).where(
            Attendance.game_day_id == game_day_id,
            Attendance.player_id == player.id,
        )
    )
    att = existing.scalar_one_or_none()
    if att and att.response == AttendanceResponse.YES:
        await call.answer("✅ Ты уже записан на эту игру!", show_alert=True)
        return
    if att and att.response == AttendanceResponse.WAITLIST:
        await call.answer("⏳ Ты уже в листе ожидания!", show_alert=True)
        return

    lang = getattr(player, 'language', None) or 'ru'
    agreement = REGLAMENT_AGREEMENT_EN if lang == 'en' else REGLAMENT_AGREEMENT
    await call.message.edit_text(
        f"⚽ <b>Регистрация на игру</b>\n\n"
        f"{agreement}",
        reply_markup=join_confirm_kb(game_day_id, lang)
    )


@router.callback_query(F.data.startswith("decline_pre:"))
async def decline_pre(call: CallbackQuery):
    await call.answer("Отменено")
    await call.message.delete()


@router.callback_query(F.data == "closed")
async def closed_registration(call: CallbackQuery):
    await call.answer("🔒 Запись закрыта. Следи за анонсами!", show_alert=True)


# ---------- Записаться ----------

@router.callback_query(F.data.startswith("join:"))
async def join_game(call: CallbackQuery, session: AsyncSession, player: Player | None):
    await call.answer()
    game_day_id = int(call.data.split(":")[1])

    if not player:
        await call.message.answer("❌ Сначала зарегистрируйся: /register")
        return

    game_day = await session.get(
        GameDay, game_day_id,
        options=[selectinload(GameDay.attendances)]
    )
    if not game_day:
        await call.message.answer("❌ Игровой день не найден.")
        return

    if player.balance < 0 and settings.DEBUG is False:
        await call.message.answer(
            f"⚠️ У тебя долг {abs(player.balance)} сум.\n"
            "Сначала погаси долг — свяжись с организатором."
        )
        return

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

    registered = sum(1 for a in game_day.attendances if a.response == AttendanceResponse.YES)
    is_full = registered >= game_day.player_limit

    if is_full:
        # Уже в листе ожидания — не добавлять повторно
        if existing and existing.response == AttendanceResponse.WAITLIST:
            waitlist_list = [
                a for a in game_day.attendances
                if a.response == AttendanceResponse.WAITLIST
            ]
            waitlist_list.sort(key=lambda a: a.responded_at or datetime.min)
            pos = next(
                (i + 1 for i, a in enumerate(waitlist_list) if a.player_id == player.id), "?"
            )
            await call.answer(f"Ты уже в листе ожидания (#{pos})!", show_alert=True)
            return

        # Добавить в лист ожидания
        waitlist_count = sum(
            1 for a in game_day.attendances
            if a.response == AttendanceResponse.WAITLIST
        )
        my_position = waitlist_count + 1

        if existing:
            existing.response = AttendanceResponse.WAITLIST
            existing.responded_at = datetime.now()
        else:
            session.add(Attendance(
                game_day_id=game_day_id,
                player_id=player.id,
                response=AttendanceResponse.WAITLIST,
                responded_at=datetime.now()
            ))
        await session.commit()

        lang = getattr(player, 'language', None) or 'ru'
        gender = getattr(player, 'gender', 'm') or 'm'
        await call.message.edit_text(
            t_g('join_waitlist', lang, gender, position=my_position)
        )
        return

    if not game_day.is_open:
        await call.message.answer("❌ Запись закрыта.")
        return

    if existing:
        existing.response = AttendanceResponse.YES
        existing.responded_at = datetime.now()
    else:
        session.add(Attendance(
            game_day_id=game_day_id,
            player_id=player.id,
            response=AttendanceResponse.YES,
            responded_at=datetime.now()
        ))

    await session.commit()

    lang = getattr(player, 'language', None) or 'ru'
    gender = getattr(player, 'gender', 'm') or 'm'
    await call.message.edit_text(
        t_g('join_success', lang, gender,
            date=game_day.scheduled_at.strftime('%d.%m.%Y %H:%M'),
            location=game_day.location)
    )


# ---------- Отказ от игры ----------

@router.callback_query(F.data.startswith("decline:"))
async def decline_game(call: CallbackQuery, session: AsyncSession,
                       player: Player | None, bot: Bot):
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
    was_confirmed = existing and existing.response == AttendanceResponse.YES

    if existing:
        existing.response = AttendanceResponse.NO
        existing.responded_at = datetime.now()
    else:
        session.add(Attendance(
            game_day_id=game_day_id,
            player_id=player.id,
            response=AttendanceResponse.NO,
            responded_at=datetime.now()
        ))

    await session.commit()
    lang = getattr(player, 'language', None) or 'ru'
    gender = getattr(player, 'gender', 'm') or 'm'
    await call.message.edit_text(t_g('join_declined', lang, gender))

    if was_confirmed:
        await _notify_first_waitlist(session, game_day_id, bot)


async def _notify_first_waitlist(session: AsyncSession, game_day_id: int, bot: Bot):
    result = await session.execute(
        select(Attendance)
        .options(selectinload(Attendance.player))
        .where(
            Attendance.game_day_id == game_day_id,
            Attendance.response == AttendanceResponse.WAITLIST,
        )
        .order_by(Attendance.responded_at)
        .limit(1)
    )
    first = result.scalar_one_or_none()
    if not first:
        return

    game_day = await session.get(GameDay, game_day_id)
    if not game_day:
        return

    try:
        lang = getattr(first.player, 'language', None) or 'ru'
        gender = getattr(first.player, 'gender', 'm') or 'm'
        await bot.send_message(
            first.player.telegram_id,
            t_g('waitlist_promoted', lang, gender,
                date=game_day.scheduled_at.strftime('%d.%m.%Y %H:%M'),
                location=game_day.location),
            reply_markup=join_game_kb(game_day_id, game_day.is_open, lang)
        )
    except Exception as e:
        logger.warning(f"Cannot notify waitlist player {first.player.telegram_id}: {e}")


# ---------- Создание игрового дня ----------

@router.callback_query(F.data == "admin_create_gameday")
async def admin_create_gameday_start(call: CallbackQuery, state: FSMContext):
    if not settings.is_admin(call.from_user.id):
        await call.answer("⛔ Нет доступа", show_alert=True)
        return
    await call.answer()
    from aiogram.types import InlineKeyboardButton
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    cancel_kb = InlineKeyboardBuilder()
    cancel_kb.row(InlineKeyboardButton(text="❌ Отмена", callback_data="admin_back"))
    await call.message.edit_text(
        "📅 <b>Создание игрового дня</b>\n\n"
        "Введи дату и время игры в формате:\n"
        "<code>ДД.ММ.ГГГГ ЧЧ:ММ</code>\n\n"
        "Например: <code>28.04.2026 19:00</code>",
        reply_markup=cancel_kb.as_markup()
    )
    await state.set_state(CreateGameDayFSM.waiting_date)


@router.message(CreateGameDayFSM.waiting_date)
async def create_gd_date(message: Message, state: FSMContext):
    try:
        dt = datetime.strptime(message.text.strip(), "%d.%m.%Y %H:%M")
    except ValueError:
        await message.answer("❌ Неверный формат. Попробуй: <code>25.04.2026 18:00</code>")
        return

    await state.update_data(scheduled_at=dt.isoformat())
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
async def create_gd_limit(message: Message, state: FSMContext,
                          session: AsyncSession, bot: Bot):
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

    data = await state.get_data()
    scheduled_at = datetime.fromisoformat(data["scheduled_at"])
    deadline = scheduled_at - timedelta(hours=settings.REGISTRATION_DEADLINE_HOURS)

    # Получить league_id из профиля создающего
    player_result = await session.execute(
        select(Player).where(Player.telegram_id == message.from_user.id)
    )
    creator = player_result.scalar_one_or_none()
    league_id = creator.league_id if creator else None

    # Вычислить следующий порядковый номер турнира (минимальный свободный)
    tournament_number = await _next_tournament_number(session, league_id)

    # Анонс за 48 часов до игры
    now = datetime.now()
    announce_at = scheduled_at - timedelta(hours=48)
    # Если игра уже через <48ч — анонс немедленно, иначе по расписанию
    announce_immediately = announce_at <= now

    game_day = GameDay(
        scheduled_at=scheduled_at,
        location=data["location"],
        player_limit=limit,
        cost_per_player=0,
        registration_deadline=deadline,
        status=GameDayStatus.ANNOUNCED,
        league_id=league_id,
        tournament_number=tournament_number,
        announce_at=announce_at,
        registration_open=announce_immediately,
    )
    session.add(game_day)
    await session.commit()
    await session.refresh(game_day)
    await state.clear()

    schedule_reminders(game_day)

    if announce_immediately:
        # Игра через <48ч — анонс сразу
        await _auto_announce(session, bot, game_day, league_id)
        status_text = "📢 Анонс разослан всем игрокам лиги (игра через менее 48ч)"
    else:
        # Запланировать анонс на 48ч до игры
        schedule_announcement(game_day)
        status_text = (
            f"📣 Анонс будет разослан автоматически\n"
            f"🗓 {announce_at.strftime('%d.%m.%Y в %H:%M')} (за 48ч до игры)"
        )

    from app.keyboards.main_menu import admin_menu_kb
    await message.answer(
        f"✅ <b>{game_day.display_name} создан!</b>\n\n"
        f"📅 {game_day.scheduled_at.strftime('%d.%m.%Y %H:%M')}\n"
        f"📍 {game_day.location}\n"
        f"👥 Лимит: {game_day.player_limit} игроков\n"
        f"🔒 Запись закрывается: {deadline.strftime('%d.%m %H:%M')}\n\n"
        + status_text,
        reply_markup=game_day_action_kb(game_day.id)
    )


async def _next_tournament_number(session: AsyncSession, league_id) -> int:
    """Возвращает наименьший свободный номер турнира для лиги."""
    from sqlalchemy import select as sa_select
    from app.database.models import GameDayStatus as GDS

    query = sa_select(GameDay.tournament_number).where(
        GameDay.status != GDS.CANCELLED,
        GameDay.tournament_number.is_not(None),
    )
    if league_id is not None:
        query = query.where(GameDay.league_id == league_id)

    result = await session.execute(query)
    used = {row[0] for row in result.all() if row[0] is not None}

    n = 1
    while n in used:
        n += 1
    return n


# ---------- Подтверждение участия (кнопки из напоминаний) ----------

@router.callback_query(F.data.startswith("confirm_yes:"))
async def confirm_attendance_yes(call: CallbackQuery, session: AsyncSession, player: Player | None):
    await call.answer()
    if not player:
        return

    game_day_id = int(call.data.split(":")[1])
    result = await session.execute(
        select(Attendance).where(
            Attendance.game_day_id == game_day_id,
            Attendance.player_id == player.id,
        )
    )
    att = result.scalar_one_or_none()

    if att and att.response == AttendanceResponse.YES:
        att.confirmed_final = True
        await session.commit()

    lang = getattr(player, 'language', None) or 'ru'
    await call.message.edit_text(t('confirm_yes_response', lang), parse_mode="HTML")


@router.callback_query(F.data.startswith("confirm_no:"))
async def confirm_attendance_no(call: CallbackQuery, session: AsyncSession,
                                player: Player | None, bot: Bot):
    await call.answer()
    if not player:
        return

    game_day_id = int(call.data.split(":")[1])
    result = await session.execute(
        select(Attendance).where(
            Attendance.game_day_id == game_day_id,
            Attendance.player_id == player.id,
        )
    )
    att = result.scalar_one_or_none()

    was_yes = att and att.response == AttendanceResponse.YES
    if att:
        att.response = AttendanceResponse.NO
        att.confirmed_final = False
        att.responded_at = datetime.now()
        await session.commit()

    lang = getattr(player, 'language', None) or 'ru'
    await call.message.edit_text(t('confirm_no_response', lang), parse_mode="HTML")

    if was_yes:
        await _notify_first_waitlist(session, game_day_id, bot)


async def _auto_announce(session: AsyncSession, bot: Bot,
                         game_day: GameDay, league_id) -> None:
    """Авторассылка анонса всем активным игрокам лиги через PlayerLeague."""
    if league_id is not None:
        result = await session.execute(
            select(Player)
            .join(PlayerLeague, PlayerLeague.player_id == Player.id)
            .where(
                PlayerLeague.league_id == league_id,
                Player.status == PlayerStatus.ACTIVE,
            )
        )
    else:
        result = await session.execute(
            select(Player).where(Player.status == PlayerStatus.ACTIVE)
        )
    players = result.scalars().all()

    text = (
        f"⚽ <b>Анонс игры — {game_day.display_name}!</b>\n\n"
        f"📅 {game_day.scheduled_at.strftime('%d.%m.%Y %H:%M')}\n"
        f"📍 {game_day.location}\n"
        f"👥 Мест: {game_day.player_limit}\n\n"
        "Успей записаться! 👇"
    )

    for p in players:
        try:
            lang = getattr(p, "language", None) or "ru"
            await bot.send_message(
                p.telegram_id,
                text,
                reply_markup=join_game_kb(game_day.id, game_day.is_open, lang, webapp_url=settings.WEBAPP_URL),
                parse_mode="HTML",
            )
            await asyncio.sleep(0.05)
        except Exception as e:
            logger.warning(f"Cannot send announce to {p.telegram_id}: {e}")


async def _notify_tournament_created(session: AsyncSession, bot: Bot,
                                     game_day: GameDay, league_id) -> None:
    """T-024: Рассылка уведомления о создании турнира (без кнопок записи)."""
    from app.database.models import PlayerLeague, PlayerStatus
    if league_id is not None:
        result = await session.execute(
            select(Player)
            .join(PlayerLeague, PlayerLeague.player_id == Player.id)
            .where(
                PlayerLeague.league_id == league_id,
                Player.status == PlayerStatus.ACTIVE,
            )
        )
    else:
        result = await session.execute(
            select(Player).where(Player.status == PlayerStatus.ACTIVE)
        )
    players = result.scalars().all()

    announce_str = game_day.announce_at.strftime("%d.%m.%Y в %H:%M") if game_day.announce_at else "—"
    text = (
        f"📣 <b>Новый турнир запланирован!</b>\n\n"
        f"🏆 {game_day.display_name}\n"
        f"📅 {game_day.scheduled_at.strftime('%d.%m.%Y %H:%M')}\n"
        f"📍 {game_day.location}\n"
        f"👥 Мест: {game_day.player_limit}\n\n"
        f"⏳ <b>Регистрация откроется {announce_str}</b>\n"
        "Следи за уведомлениями! 🔔"
    )

    for p in players:
        try:
            await bot.send_message(p.telegram_id, text, parse_mode="HTML")
            await asyncio.sleep(0.05)
        except Exception as e:
            logger.warning(f"Cannot send tournament_created to {p.telegram_id}: {e}")


# ---------- T-013: Подтверждение «Опаздываю» ----------

@router.callback_query(F.data.startswith("confirm_late:"))
async def confirm_attendance_late(call: CallbackQuery, session: AsyncSession,
                                  player: Player | None):
    await call.answer()
    if not player:
        return

    game_day_id = int(call.data.split(":")[1])
    result = await session.execute(
        select(Attendance).where(
            Attendance.game_day_id == game_day_id,
            Attendance.player_id == player.id,
        )
    )
    att = result.scalar_one_or_none()

    if att and att.response == AttendanceResponse.YES:
        att.confirmed_final = True
        att.is_late = True
        await session.commit()

    lang = getattr(player, 'language', None) or 'ru'
    late_responses = {
        "ru": "⏰ <b>Понял, опаздываешь!</b>\n\nПостарайся прийти как можно скорее. Команда ждёт! ⚽",
        "en": "⏰ <b>Got it, you're running late!</b>\n\nTry to get there as soon as you can. The team is waiting! ⚽",
        "uz": "⏰ <b>Tushunarli, kechikasiz!</b>\n\nImkon qadar tezroq kelishga harakat qiling. Jamoa kutmoqda! ⚽",
        "de": "⏰ <b>Verstanden, du kommst später!</b>\n\nKomm so schnell wie möglich. Das Team wartet! ⚽",
    }
    await call.message.edit_text(
        late_responses.get(lang, late_responses["ru"]),
        parse_mode="HTML"
    )


# ---------- Картинка таблицы (доступна всем) ----------

@router.callback_query(F.data.startswith("gd_standings_img:"))
async def gd_standings_image(call: CallbackQuery, session: AsyncSession):
    """Генерирует PNG с турнирной таблицей — доступно игрокам и админу."""
    from collections import Counter
    from aiogram.types import BufferedInputFile
    from app.utils.standings_image import generate_standings_image
    from app.database.models import Team, TeamPlayer

    await call.answer("🖼 Генерирую картинку...")

    game_day_id = int(call.data.split(":")[1])
    game_day = await session.get(GameDay, game_day_id)
    if not game_day:
        return

    # Групповая таблица
    matches_res = await session.execute(
        select(Match)
        .options(
            selectinload(Match.team_home),
            selectinload(Match.team_away),
            selectinload(Match.goals).selectinload(Goal.player),
        )
        .where(Match.game_day_id == game_day_id)
        .order_by(Match.id)
    )
    all_matches = matches_res.scalars().all()

    stats: dict[int, dict] = {}
    for m in all_matches:
        if m.status != MatchStatus.FINISHED:
            continue
        if (m.match_stage or "group") != "group":
            continue
        for team, gf, ga in [
            (m.team_home, m.score_home, m.score_away),
            (m.team_away, m.score_away, m.score_home),
        ]:
            if team.id not in stats:
                stats[team.id] = {
                    "name": team.name, "emoji": team.color_emoji or "",
                    "W": 0, "D": 0, "L": 0, "GF": 0, "GA": 0, "GP": 0,
                }
            s = stats[team.id]
            s["GP"] += 1; s["GF"] += gf; s["GA"] += ga
            if gf > ga: s["W"] += 1
            elif gf == ga: s["D"] += 1
            else: s["L"] += 1
    for s in stats.values():
        s["Pts"] = s["W"] * 3 + s["D"]
    standings = sorted(stats.values(), key=lambda x: (-x["Pts"], -(x["GF"] - x["GA"]), -x["GF"]))

    # Плей-офф матчи
    playoff_stage_order = ["semifinal", "third_place", "final"]
    playoff_matches = []
    for m in all_matches:
        stage = m.match_stage or "group"
        if stage in playoff_stage_order:
            playoff_matches.append({
                "stage": stage,
                "home": m.team_home.name[:12],
                "away": m.team_away.name[:12],
                "home_emoji": getattr(m.team_home, "color_emoji", ""),
                "away_emoji": getattr(m.team_away, "color_emoji", ""),
                "score_h": m.score_home,
                "score_a": m.score_away,
                "finished": m.status == MatchStatus.FINISHED,
            })
    playoff_matches.sort(key=lambda x: playoff_stage_order.index(x["stage"]))

    # Бомбардиры
    goal_counts: Counter = Counter()
    for m in all_matches:
        for g in m.goals:
            if g.goal_type != GoalType.OWN_GOAL and g.player:
                goal_counts[g.player.name] += 1
    top_scorers = goal_counts.most_common(5)

    date_str = game_day.scheduled_at.strftime("%d.%m.%Y")

    loop = asyncio.get_event_loop()
    img_bytes = await loop.run_in_executor(
        None,
        generate_standings_image,
        game_day.display_name,
        date_str,
        standings,
        playoff_matches,
        top_scorers,
    )

    await call.message.answer_photo(
        BufferedInputFile(img_bytes, filename="standings.png"),
        caption=f"📊 {game_day.display_name} — {date_str}"
    )

from aiogram import Router, F
from aiogram.filters import CommandStart, Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database.models import (
    Player, POSITION_LABELS,
    GameDay, GameDayStatus, Match, MatchStatus, Team, League,
)
from app.keyboards.main_menu import main_menu_kb, admin_menu_kb, language_kb
from app.locales.texts import t

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
async def cmd_start(message: Message, player: Player | None, state: FSMContext,
                    session: AsyncSession, command: CommandObject = None):
    await state.clear()

    lang = (getattr(player, 'language', None) or 'ru') if player else 'ru'

    # deep link: t.me/bot?start=rules
    if command and command.args == "rules":
        await _send_reglament(message, player)
        return

    # deep link: t.me/bot?start=join_XXXXXXXX  (приглашение в лигу)
    if command and command.args and command.args.startswith("join_"):
        invite_code = command.args[5:]  # strip "join_"
        await _handle_invite_link(message, player, state, session, invite_code)
        return

    if player is None:
        await message.answer(t('reg_welcome', 'ru'))
        return

    pos_label = POSITION_LABELS.get(player.position, str(player.position))
    provisional = t('provisional_label', lang) if player.rating_provisional else ""
    hint = t('no_league_hint', lang) if not player.league_id else ""

    text = t('main_menu_greeting', lang,
             name=player.name,
             position=pos_label,
             rating=f"{player.rating:.1f}",
             provisional=provisional,
             balance=player.balance)
    text += hint

    await message.answer(text, reply_markup=main_menu_kb(lang))


async def _handle_invite_link(
    message: Message,
    player: Player | None,
    state: FSMContext,
    session: AsyncSession,
    invite_code: str,
):
    """Обрабатывает приглашение в лигу по ссылке /start join_XXXXXXXX."""
    league_res = await session.execute(
        select(League).where(League.invite_code == invite_code, League.is_active == True)
    )
    league = league_res.scalar_one_or_none()

    if not league:
        await message.answer(
            "❌ Ссылка недействительна или лига не найдена.\n\n"
            "Обратись к организатору за новой ссылкой."
        )
        return

    lang = (getattr(player, 'language', None) or 'ru') if player else 'ru'

    if player is not None:
        # Уже зарегистрирован — просто привязать к лиге
        if player.league_id == league.id:
            await message.answer(
                f"✅ Ты уже в лиге <b>{league.name}</b>!",
                reply_markup=main_menu_kb(lang)
            )
        else:
            player.league_id = league.id
            await session.commit()
            await message.answer(
                f"🎉 Ты вступил в лигу <b>{league.name}</b>!\n\n"
                f"📍 {league.city or ''}\n\n"
                "Теперь ты видишь игры и статистику своей лиги.",
                reply_markup=main_menu_kb(lang)
            )
    else:
        # Не зарегистрирован — сохранить код и попросить зарегистрироваться
        await state.update_data(pending_invite_code=invite_code)
        await message.answer(
            f"👋 Тебя приглашают в лигу <b>{league.name}</b>!\n\n"
            "Чтобы присоединиться, сначала нужно создать профиль игрока.\n\n"
            "Нажми /register и после регистрации ты автоматически попадёшь в эту лигу."
        )


async def _send_reglament(target, player=None):
    """Отправить Регламент двумя сообщениями (обходим лимит 4096 символов)."""
    lang = (getattr(player, 'language', None) or 'ru') if player else 'ru'
    if isinstance(target, CallbackQuery):
        send = target.message.answer
    else:
        send = target.answer
    from app.data.reglament import REGLAMENT_PART1, REGLAMENT_PART2, REGLAMENT_PART1_EN, REGLAMENT_PART2_EN
    if lang == 'en':
        await send(REGLAMENT_PART1_EN, disable_web_page_preview=True)
        await send(REGLAMENT_PART2_EN)
    else:
        await send(REGLAMENT_PART1, disable_web_page_preview=True)
        await send(REGLAMENT_PART2)


@router.message(Command("rules"))
async def cmd_rules(message: Message, player: Player | None):
    await _send_reglament(message, player)


@router.callback_query(lambda c: c.data == "reglament")
async def cb_reglament(call: CallbackQuery, player: Player | None):
    await call.answer()
    await _send_reglament(call, player)


@router.message(Command("admin"))
async def cmd_admin(message: Message, player: Player | None, state: FSMContext,
                    session: AsyncSession):
    await state.clear()  # Сбросить любой активный FSM

    is_super = settings.is_admin(message.from_user.id)

    # Проверить — является ли пользователь администратором лиги
    is_league_admin = False
    if not is_super:
        league_res = await session.execute(
            select(League).where(
                League.admin_telegram_id == message.from_user.id,
                League.is_active == True
            )
        )
        is_league_admin = league_res.scalar_one_or_none() is not None

    if not is_super and not is_league_admin:
        await message.answer(
            "⛔ У тебя нет доступа к Админке.\n\n"
            "Создай свою лигу командой /create_league и стань администратором."
        )
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

    lang = getattr(player, 'language', None) or 'ru'
    await call.message.edit_text(
        f"⚽ Главное меню, <b>{player.name}</b>:",
        reply_markup=main_menu_kb(lang)
    )


@router.callback_query(lambda c: c.data == "my_profile")
async def cb_my_profile(call: CallbackQuery, player: Player | None):
    await call.answer()
    if not player:
        await call.message.answer("Ты не зарегистрирован. Нажми /register")
        return

    lang = getattr(player, 'language', None) or 'ru'
    pos_label = POSITION_LABELS.get(player.position, player.position)
    provisional = t('provisional_label', lang) if player.rating_provisional else ""

    from aiogram.utils.keyboard import InlineKeyboardBuilder as IKB
    from aiogram.types import InlineKeyboardButton as IKBBtn

    text = t('profile_title', lang,
             name=player.name,
             position=pos_label,
             rating=f"{player.rating:.1f}",
             provisional=provisional,
             reliability=f"{player.reliability_pct:.0f}",
             games=player.games_played,
             balance=player.balance)

    kb = IKB()
    kb.row(IKBBtn(
        text="✏️ Редактировать профиль" if lang == "ru" else "✏️ Edit Profile",
        callback_data="edit_profile"
    ))
    for row in main_menu_kb(lang).inline_keyboard:
        kb.row(*row)

    await call.message.edit_text(text, reply_markup=kb.as_markup())


@router.callback_query(lambda c: c.data == "players_list")
async def cb_players_list(call: CallbackQuery, session: AsyncSession, player: Player | None):
    await call.answer()
    from sqlalchemy import select
    from app.database.models import PlayerStatus, POSITION_LABELS

    lang = getattr(player, 'language', None) or 'ru' if player else 'ru'

    result = await session.execute(
        select(Player)
        .where(Player.status == PlayerStatus.ACTIVE)
        .order_by(Player.rating.desc())
    )
    players = result.scalars().all()

    if not players:
        await call.message.edit_text(t('no_players', lang), reply_markup=main_menu_kb(lang))
        return

    lines = [t('players_title', lang)]
    for i, p in enumerate(players, 1):
        pos = POSITION_LABELS.get(p.position, p.position)
        provisional = " <i>(пров.)</i>" if p.rating_provisional else ""
        if p.username:
            name_part = f'<a href="https://t.me/{p.username}">{p.name}</a>'
        else:
            name_part = f'<b>{p.name}</b>'
        lines.append(f"{i}. {name_part} — {pos}, ⭐{p.rating:.1f}{provisional}")

    await call.message.edit_text("\n".join(lines), reply_markup=main_menu_kb(lang))


@router.callback_query(lambda c: c.data == "match_results")
async def cb_match_results(call: CallbackQuery, session: AsyncSession, player: Player | None):
    await call.answer()
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload
    from app.database.models import Match, MatchStatus, Team, Goal, Card, CardType, GoalType

    lang = getattr(player, 'language', None) or 'ru' if player else 'ru'

    result = await session.execute(
        select(Match)
        .options(
            selectinload(Match.team_home),
            selectinload(Match.team_away),
            selectinload(Match.goals).selectinload(Goal.player),
            selectinload(Match.cards).selectinload(Card.player),
        )
        .where(Match.status == MatchStatus.FINISHED)
        .order_by(Match.finished_at.desc())
        .limit(10)
    )
    matches = result.scalars().all()

    if not matches:
        await call.message.edit_text(t('results_empty', lang), reply_markup=main_menu_kb(lang))
        return

    lines = [t('results_title', lang)]
    for match in matches:
        home = match.team_home.name
        away = match.team_away.name
        date = match.finished_at.strftime("%d.%m") if match.finished_at else "—"
        lines.append(f"\n⚽ <b>{home} {match.score_home}:{match.score_away} {away}</b> ({date})")

        for goal in sorted(match.goals, key=lambda g: g.scored_at):
            marker = "⚽" if goal.goal_type == GoalType.GOAL else "🥅"
            team_name = home if goal.team_id == match.team_home_id else away
            own = " (авт.)" if goal.goal_type == GoalType.OWN_GOAL else ""
            lines.append(f"  {marker} {goal.player.name}{own} [{team_name}]")

        for card in sorted(match.cards, key=lambda c: c.issued_at):
            emoji = "🟨" if card.card_type == CardType.YELLOW else "🟥"
            lines.append(f"  {emoji} {card.player.name}")

    await call.message.edit_text("\n".join(lines), reply_markup=main_menu_kb(lang))


@router.callback_query(lambda c: c.data == "my_stats")
async def cb_my_stats(call: CallbackQuery, player: Player | None, session: AsyncSession):
    await call.answer()
    if not player:
        await call.message.answer("Ты не зарегистрирован.")
        return

    lang = getattr(player, 'language', None) or 'ru'

    from sqlalchemy import select, func
    from app.database.models import Goal

    # Голы
    goals_result = await session.execute(
        select(func.count(Goal.id)).where(Goal.player_id == player.id)
    )
    total_goals = goals_result.scalar() or 0

    text = t('my_stats_title', lang,
             name=player.name,
             games=player.games_played,
             goals=total_goals,
             reliability=f"{player.reliability_pct:.0f}",
             rating=f"{player.rating:.1f}")
    await call.message.edit_text(text, reply_markup=main_menu_kb(lang))


@router.callback_query(lambda c: c.data == "tournament_standings")
async def cb_tournament_standings(call: CallbackQuery, session: AsyncSession, player: Player | None):
    await call.answer()

    lang = getattr(player, 'language', None) or 'ru' if player else 'ru'

    # Найти активный или последний игровой день
    result = await session.execute(
        select(GameDay)
        .where(GameDay.status.in_([
            GameDayStatus.ANNOUNCED,
            GameDayStatus.CLOSED,
            GameDayStatus.IN_PROGRESS,
            GameDayStatus.FINISHED,
        ]))
        .order_by(GameDay.scheduled_at.desc())
        .limit(1)
    )
    game_day = result.scalar_one_or_none()

    if not game_day:
        await call.message.edit_text(
            t('standings_empty', lang),
            reply_markup=main_menu_kb(lang)
        )
        return

    # Подсчёт очков из завершённых матчей
    matches_result = await session.execute(
        select(Match)
        .options(selectinload(Match.team_home), selectinload(Match.team_away))
        .where(Match.game_day_id == game_day.id, Match.status == MatchStatus.FINISHED)
    )
    matches = matches_result.scalars().all()

    stats: dict[int, dict] = {}
    for match in matches:
        for team, gf, ga in [
            (match.team_home, match.score_home, match.score_away),
            (match.team_away, match.score_away, match.score_home),
        ]:
            if team.id not in stats:
                stats[team.id] = {
                    "name": team.name, "emoji": team.color_emoji,
                    "GP": 0, "W": 0, "D": 0, "L": 0, "GF": 0, "GA": 0,
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

    table = sorted(stats.values(), key=lambda x: (-x["Pts"], -(x["GF"] - x["GA"]), -x["GF"]))

    date_str = game_day.scheduled_at.strftime("%d.%m.%Y")
    lines = [t('standings_title', lang, date=date_str)]

    if not table:
        lines.append(t('standings_no_matches', lang))
    else:
        lines.append("<code>№  Команда          И  В  Н  П  ГЗ ГП  О</code>")
        lines.append("<code>" + "─" * 42 + "</code>")
        for i, s in enumerate(table, 1):
            name = (s["emoji"] + " " + s["name"])[:15].ljust(15)
            row = (
                f"{i:<3}{name}"
                f"{s['GP']:<3}{s['W']:<3}{s['D']:<3}{s['L']:<3}"
                f"{s['GF']:<3}{s['GA']:<3}{s['Pts']}"
            )
            lines.append(f"<code>{row}</code>")

    # Последние результаты
    all_finished = [m for m in matches]
    if all_finished:
        lines.append(t('standings_recent', lang))
        for m in all_finished[-5:]:
            lines.append(
                f"  {m.team_home.name} <b>{m.score_home}:{m.score_away}</b> {m.team_away.name}"
            )

    # Предстоящие матчи
    upcoming_result = await session.execute(
        select(Match)
        .options(selectinload(Match.team_home), selectinload(Match.team_away))
        .where(Match.game_day_id == game_day.id, Match.status == MatchStatus.SCHEDULED)
    )
    upcoming = upcoming_result.scalars().all()
    if upcoming:
        lines.append(t('standings_upcoming', lang))
        for m in upcoming[:5]:
            lines.append(f"  ⏳ {m.team_home.name} vs {m.team_away.name}")

    await call.message.edit_text("\n".join(lines), reply_markup=main_menu_kb(lang))


# ── Language handlers ────────────────────────────────────────────────────────

@router.callback_query(lambda c: c.data == "language_menu")
async def cb_language_menu(call: CallbackQuery, player: Player | None):
    await call.answer()
    lang = (getattr(player, 'language', None) or 'ru') if player else 'ru'
    await call.message.answer(t('choose_language', lang), reply_markup=language_kb(lang))


@router.callback_query(F.data.startswith("set_lang:"))
async def cb_set_language(call: CallbackQuery, player: Player | None, session: AsyncSession):
    await call.answer()
    new_lang = call.data.split(":")[1]
    if new_lang not in ('ru', 'en'):
        return
    if player:
        player.language = new_lang
        await session.commit()
    key = 'lang_set_ru' if new_lang == 'ru' else 'lang_set_en'
    await call.message.answer(t(key, new_lang), reply_markup=main_menu_kb(new_lang))

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder


def referee_gamedays_kb(game_days: list) -> InlineKeyboardMarkup:
    """Список активных игровых дней для выбора"""
    builder = InlineKeyboardBuilder()
    for gd in game_days:
        builder.row(InlineKeyboardButton(
            text=f"📅 {gd.scheduled_at.strftime('%d.%m.%Y %H:%M')} — {gd.location}",
            callback_data=f"ref_gd:{gd.id}"
        ))
    return builder.as_markup()


def referee_gd_kb(game_day_id: int, matches: list) -> InlineKeyboardMarkup:
    """Панель игрового дня для судьи"""
    builder = InlineKeyboardBuilder()
    for match in matches:
        status_icon = "⏸" if match.status.value == "scheduled" else ("▶️" if match.status.value == "in_progress" else "✅")
        text = (
            f"{status_icon} {match.team_home.name} "
            f"{match.score_home}:{match.score_away} "
            f"{match.team_away.name}"
        )
        # Stage prefix for non-group matches
        stage = getattr(match, "match_stage", "group") or "group"
        stage_prefix = {
            "semifinal": "🏆 ",
            "third_place": "🥉 ",
            "final": "🏆🏆 ",
        }.get(stage, "")
        builder.row(InlineKeyboardButton(
            text=stage_prefix + text,
            callback_data=f"ref_match:{match.id}"
        ))
    builder.row(InlineKeyboardButton(
        text="➕ Новый матч",
        callback_data=f"ref_new_match:{game_day_id}"
    ))
    builder.row(
        InlineKeyboardButton(
            text="👥 Составы команд",
            callback_data=f"ref_setup_teams:{game_day_id}"
        ),
        InlineKeyboardButton(
            text="📊 Таблица",
            callback_data=f"ref_standings:{game_day_id}"
        ),
    )
    return builder.as_markup()


def referee_match_kb(match_id: int, is_started: bool, is_finished: bool) -> InlineKeyboardMarkup:
    """Панель управления матчем"""
    builder = InlineKeyboardBuilder()
    if is_finished:
        builder.row(InlineKeyboardButton(text="✅ Матч завершён", callback_data="noop"))
        # Постфактум: добавить события после финального свистка
        builder.row(
            InlineKeyboardButton(text="🥅 +Гол", callback_data=f"ref_goal:{match_id}"),
            InlineKeyboardButton(text="🟨 +ЖК", callback_data=f"ref_yellow:{match_id}"),
            InlineKeyboardButton(text="🟥 +КК", callback_data=f"ref_red:{match_id}"),
        )
    elif not is_started:
        builder.row(InlineKeyboardButton(
            text="▶️ Старт таймера",
            callback_data=f"ref_start:{match_id}"
        ))
    else:
        builder.row(InlineKeyboardButton(
            text="⏱ Статус таймера",
            callback_data=f"ref_timer:{match_id}"
        ))

    if not is_finished:
        builder.row(
            InlineKeyboardButton(text="🥅 Гол", callback_data=f"ref_goal:{match_id}"),
            InlineKeyboardButton(text="🟨 ЖК", callback_data=f"ref_yellow:{match_id}"),
            InlineKeyboardButton(text="🟥 КК", callback_data=f"ref_red:{match_id}"),
        )
        if is_started:
            builder.row(InlineKeyboardButton(
                text="🔄 Замена",
                callback_data=f"ref_sub:{match_id}"
            ))
        builder.row(InlineKeyboardButton(
            text="🏁 Завершить матч",
            callback_data=f"ref_finish:{match_id}"
        ))
    return builder.as_markup()


def select_team_kb(match_id: int, action: str, home_id: int, home_name: str,
                   away_id: int, away_name: str) -> InlineKeyboardMarkup:
    """Выбор команды (для гола / карточки)"""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text=home_name, callback_data=f"{action}:{match_id}:{home_id}"),
        InlineKeyboardButton(text=away_name, callback_data=f"{action}:{match_id}:{away_id}"),
    )
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data=f"ref_match:{match_id}"))
    return builder.as_markup()


def select_player_kb(match_id: int, action: str, team_id: int,
                     players: list) -> InlineKeyboardMarkup:
    """Выбор игрока из списка"""
    builder = InlineKeyboardBuilder()
    for player in players:
        builder.button(
            text=player.name,
            callback_data=f"{action}:{match_id}:{player.id}:{team_id}"
        )
    builder.adjust(2)
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data=f"ref_match:{match_id}"))
    return builder.as_markup()


def confirm_finish_kb(match_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="✅ Да, завершить", callback_data=f"ref_finish_ok:{match_id}"),
        InlineKeyboardButton(text="❌ Отмена", callback_data=f"ref_match:{match_id}"),
    )
    return builder.as_markup()


def team_players_select_kb(
    players: list[dict],   # [{"id": int, "name": str}, ...]
    selected_ids: list[int],
    team_name: str,
) -> InlineKeyboardMarkup:
    """Мультивыбор игроков для команды во время создания матча."""
    builder = InlineKeyboardBuilder()
    for p in players:
        tick = "✅" if p["id"] in selected_ids else "◻️"
        builder.button(
            text=f"{tick} {p['name']}",
            callback_data=f"ref_toggle_player:{p['id']}",
        )
    builder.adjust(2)
    count = len(selected_ids)
    if count > 0:
        builder.row(InlineKeyboardButton(
            text=f"✅ Готово — {count} чел. в «{team_name}»",
            callback_data="ref_team_players_done",
        ))
    else:
        builder.row(InlineKeyboardButton(
            text="⚠️ Выбери хотя бы одного игрока",
            callback_data="noop",
        ))
    return builder.as_markup()


def teams_list_kb(game_day_id: int, teams: list) -> InlineKeyboardMarkup:
    """Список команд игрового дня с кнопкой добавить."""
    builder = InlineKeyboardBuilder()
    for team in teams:
        builder.row(InlineKeyboardButton(
            text=f"{team.color_emoji} {team.name}",
            callback_data=f"ref_team_detail:{game_day_id}:{team.id}"
        ))
    builder.row(InlineKeyboardButton(
        text="➕ Добавить команду",
        callback_data=f"ref_add_team:{game_day_id}"
    ))
    builder.row(InlineKeyboardButton(
        text="🔙 К игровому дню",
        callback_data=f"ref_gd:{game_day_id}"
    ))
    return builder.as_markup()


def pick_team_kb(action: str, ref_id: int, teams: list, exclude_id: int = 0) -> InlineKeyboardMarkup:
    """Выбор команды из существующих (для создания матча или другого действия)."""
    builder = InlineKeyboardBuilder()
    for team in teams:
        if team.id == exclude_id:
            continue
        builder.row(InlineKeyboardButton(
            text=f"{team.color_emoji} {team.name}",
            callback_data=f"{action}:{ref_id}:{team.id}"
        ))
    return builder.as_markup()


def sub_player_out_kb(match_id: int, team_id: int, players: list) -> InlineKeyboardMarkup:
    """Выбор игрока, которого заменяют (выходит)."""
    builder = InlineKeyboardBuilder()
    for p in players:
        builder.button(
            text=p.name,
            callback_data=f"ref_sub_out:{match_id}:{team_id}:{p.id}"
        )
    builder.adjust(2)
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data=f"ref_match:{match_id}"))
    return builder.as_markup()


def sub_player_in_kb(match_id: int, team_id: int, player_out_id: int,
                     players: list, other_team_ids: set = None) -> InlineKeyboardMarkup:
    """Выбор замены (выходит на поле). * — игрок из другой команды."""
    builder = InlineKeyboardBuilder()
    other_team_ids = other_team_ids or set()
    for p in players:
        mark = " *" if p.id in other_team_ids else ""
        builder.button(
            text=f"{p.name}{mark}",
            callback_data=f"ref_sub_in:{match_id}:{team_id}:{player_out_id}:{p.id}"
        )
    builder.adjust(2)
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data=f"ref_match:{match_id}"))
    return builder.as_markup()


def pick_format_kb() -> InlineKeyboardMarkup:
    """Выбор формата матча: по времени или до N голов."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="⏱ По времени", callback_data="ref_fmt:time"),
        InlineKeyboardButton(text="🥅 До N голов", callback_data="ref_fmt:goals"),
    )
    return builder.as_markup()


def pick_stage_kb() -> InlineKeyboardMarkup:
    """Выбор стадии матча (групповой / плей-офф)."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="📋 Групповой этап", callback_data="ref_stage:group"),
        InlineKeyboardButton(text="🏆 Полуфинал", callback_data="ref_stage:semifinal"),
    )
    builder.row(
        InlineKeyboardButton(text="🥉 Матч за 3 место", callback_data="ref_stage:third_place"),
        InlineKeyboardButton(text="🏆🏆 Финал", callback_data="ref_stage:final"),
    )
    return builder.as_markup()

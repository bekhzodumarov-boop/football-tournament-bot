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
        builder.row(InlineKeyboardButton(
            text=text,
            callback_data=f"ref_match:{match.id}"
        ))
    builder.row(InlineKeyboardButton(
        text="➕ Новый матч",
        callback_data=f"ref_new_match:{game_day_id}"
    ))
    return builder.as_markup()


def referee_match_kb(match_id: int, is_started: bool, is_finished: bool) -> InlineKeyboardMarkup:
    """Панель управления матчем"""
    builder = InlineKeyboardBuilder()
    if is_finished:
        builder.row(InlineKeyboardButton(text="✅ Матч завершён", callback_data="noop"))
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
            InlineKeyboardButton(text="🟡 ЖК", callback_data=f"ref_yellow:{match_id}"),
            InlineKeyboardButton(text="🔴 КК", callback_data=f"ref_red:{match_id}"),
        )
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

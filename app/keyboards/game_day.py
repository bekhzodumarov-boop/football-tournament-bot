from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from app.database.models import GameDay


def join_game_kb(game_day_id: int, is_open: bool) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if is_open:
        builder.row(
            InlineKeyboardButton(text="✅ Записаться", callback_data=f"join:{game_day_id}"),
            InlineKeyboardButton(text="❌ Не пойду", callback_data=f"decline:{game_day_id}"),
        )
    else:
        builder.row(
            InlineKeyboardButton(text="🔒 Набор закрыт", callback_data="closed"),
        )
    return builder.as_markup()


def confirm_attendance_kb(game_day_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="✅ Да, иду!", callback_data=f"confirm_yes:{game_day_id}"),
        InlineKeyboardButton(text="❌ Не смогу", callback_data=f"confirm_no:{game_day_id}"),
    )
    builder.row(
        InlineKeyboardButton(text="⏰ Опаздываю", callback_data=f"late:{game_day_id}"),
    )
    return builder.as_markup()


def game_day_action_kb(game_day_id: int) -> InlineKeyboardMarkup:
    """Кнопки управления игровым днём для Админа"""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="👥 Список игроков", callback_data=f"gd_players:{game_day_id}"),
        InlineKeyboardButton(text="🔀 Сформировать команды", callback_data=f"gd_teams:{game_day_id}"),
    )
    builder.row(
        InlineKeyboardButton(text="💰 Отметить оплату", callback_data=f"gd_payment:{game_day_id}"),
        InlineKeyboardButton(text="📢 Разослать анонс", callback_data=f"gd_announce:{game_day_id}"),
    )
    builder.row(
        InlineKeyboardButton(text="🔒 Закрыть запись", callback_data=f"gd_close:{game_day_id}"),
        InlineKeyboardButton(text="❌ Отменить игру", callback_data=f"gd_cancel:{game_day_id}"),
    )
    return builder.as_markup()

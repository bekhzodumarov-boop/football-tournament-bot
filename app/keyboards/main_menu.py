from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder


def main_menu_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="⚽ Ближайшая игра", callback_data="next_game"),
    )
    builder.row(
        InlineKeyboardButton(text="📊 Моя статистика", callback_data="my_stats"),
        InlineKeyboardButton(text="👥 Игроки", callback_data="players_list"),
    )
    builder.row(
        InlineKeyboardButton(text="📋 Результаты игр", callback_data="match_results"),
        InlineKeyboardButton(text="ℹ️ Мой профиль", callback_data="my_profile"),
    )
    return builder.as_markup()


def admin_menu_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="📅 Создать игровой день", callback_data="admin_create_gameday"),
    )
    builder.row(
        InlineKeyboardButton(text="👥 Управление игроками", callback_data="admin_players"),
        InlineKeyboardButton(text="💳 Оплата", callback_data="admin_payments"),
    )
    builder.row(
        InlineKeyboardButton(text="⭐ Рейтинг-голосование", callback_data="admin_rating_round"),
        InlineKeyboardButton(text="📢 Рассылка", callback_data="admin_broadcast"),
    )
    builder.row(
        InlineKeyboardButton(text="🔙 Главное меню", callback_data="main_menu"),
    )
    return builder.as_markup()

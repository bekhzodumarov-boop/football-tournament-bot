from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.config import settings
from app.locales.texts import t


def main_menu_kb(lang: str = "ru") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text=t("btn_upcoming_game", lang), callback_data="next_game"),
    )
    builder.row(
        InlineKeyboardButton(text=t("btn_my_stats", lang), callback_data="my_stats"),
        InlineKeyboardButton(text=t("btn_players_list", lang), callback_data="players_list"),
    )
    builder.row(
        InlineKeyboardButton(text=t("btn_results", lang), callback_data="match_results"),
        InlineKeyboardButton(text=t("btn_profile", lang), callback_data="my_profile"),
    )
    # Таблица: WebApp если URL задан, иначе обычная текстовая
    if settings.WEBAPP_URL:
        builder.row(
            InlineKeyboardButton(text=t("btn_standings", lang), callback_data="tournament_standings"),
            InlineKeyboardButton(
                text="🌐 Живая таблица",
                web_app=WebAppInfo(url=f"{settings.WEBAPP_URL.rstrip('/')}/")
            ),
        )
    else:
        builder.row(
            InlineKeyboardButton(text=t("btn_standings", lang), callback_data="tournament_standings"),
        )
    builder.row(
        InlineKeyboardButton(text=t("btn_rules", lang), callback_data="reglament"),
    )
    builder.row(
        InlineKeyboardButton(text=t("btn_language", lang), callback_data="language_menu"),
    )
    return builder.as_markup()


def language_kb(current_lang: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="🇷🇺 Русский" + (" ✅" if current_lang == "ru" else ""),
            callback_data="set_lang:ru"
        ),
        InlineKeyboardButton(
            text="🇬🇧 English" + (" ✅" if current_lang == "en" else ""),
            callback_data="set_lang:en"
        ),
    )
    return builder.as_markup()


def admin_menu_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="📅 Создать игровой день", callback_data="admin_create_gameday"),
    )
    builder.row(
        InlineKeyboardButton(text="📋 Активные игры", callback_data="admin_active_games"),
        InlineKeyboardButton(text="📁 Прошедшие игры", callback_data="admin_past_games"),
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
        InlineKeyboardButton(text="🌐 Моя лига", callback_data="admin_league_info"),
        InlineKeyboardButton(text="📤 Экспорт в Sheets", callback_data="admin_export_sheets"),
    )
    builder.row(
        InlineKeyboardButton(text="🔙 Главное меню", callback_data="main_menu"),
    )
    return builder.as_markup()

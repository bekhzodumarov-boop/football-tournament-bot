from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.config import settings
from app.locales.texts import t


def main_menu_kb(
    lang: str = "ru",
    is_admin: bool = False,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if settings.WEBAPP_URL:
        builder.row(
            InlineKeyboardButton(
                text="🌐 Открыть приложение",
                web_app=WebAppInfo(url=settings.WEBAPP_URL),
            )
        )
    builder.row(
        InlineKeyboardButton(text=t("btn_upcoming_game", lang), callback_data="next_game"),
    )
    builder.row(
        InlineKeyboardButton(text=t("btn_my_team", lang), callback_data="my_team"),
        InlineKeyboardButton(text=t("btn_results", lang), callback_data="match_results"),
    )
    builder.row(
        InlineKeyboardButton(text=t("btn_my_stats", lang), callback_data="my_stats"),
        InlineKeyboardButton(text=t("btn_profile", lang), callback_data="my_profile"),
    )
    builder.row(
        InlineKeyboardButton(text=t("btn_top_scorers", lang), callback_data="top_scorers"),
        InlineKeyboardButton(text=t("btn_players_list", lang), callback_data="players_list"),
    )
    builder.row(
        InlineKeyboardButton(text=t("btn_rules", lang), callback_data="reglament"),
        InlineKeyboardButton(text="📖 Инструкция", callback_data="instructions"),
    )
    builder.row(
        InlineKeyboardButton(text="🏆 Мои лиги", callback_data="my_leagues"),
        InlineKeyboardButton(text=t("btn_language", lang), callback_data="language_menu"),
    )
    if is_admin:
        builder.row(
            InlineKeyboardButton(text="🔧 Панель администратора", callback_data="admin_back"),
        )
    return builder.as_markup()


def instructions_kb(is_admin: bool = False, is_referee: bool = False) -> InlineKeyboardMarkup:
    """Меню выбора инструкции."""
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="👤 Для игрока", callback_data="instr_player"))
    if is_referee:
        builder.row(InlineKeyboardButton(text="🦺 Для рефери", callback_data="instr_referee"))
    if is_admin:
        builder.row(InlineKeyboardButton(text="🔧 Для администратора", callback_data="instr_admin"))
    if not is_referee and not is_admin:
        builder.row(InlineKeyboardButton(text="🦺 Для рефери", callback_data="instr_referee"))
        builder.row(InlineKeyboardButton(text="🔧 Для администратора", callback_data="instr_admin"))
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="main_menu"))
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
    builder.row(
        InlineKeyboardButton(
            text="🇺🇿 O'zbekcha" + (" ✅" if current_lang == "uz" else ""),
            callback_data="set_lang:uz"
        ),
        InlineKeyboardButton(
            text="🇩🇪 Deutsch" + (" ✅" if current_lang == "de" else ""),
            callback_data="set_lang:de"
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
        InlineKeyboardButton(text="📢 Опрос лиге", callback_data="admin_poll"),
        InlineKeyboardButton(text="💳 Карта для оплаты", callback_data="admin_card"),
    )
    builder.row(
        InlineKeyboardButton(text="📋 История рассылок", callback_data="admin_broadcast_history"),
    )
    builder.row(
        InlineKeyboardButton(text="🔙 Главное меню", callback_data="main_menu"),
    )
    return builder.as_markup()

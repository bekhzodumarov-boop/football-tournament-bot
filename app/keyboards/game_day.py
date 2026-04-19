from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from app.database.models import GameDay
from app.locales.texts import t


def join_game_kb(game_day_id: int, is_open: bool, lang: str = "ru") -> InlineKeyboardMarkup:
    """Кнопки анонса игры."""
    builder = InlineKeyboardBuilder()
    if is_open:
        builder.row(
            InlineKeyboardButton(
                text=t("btn_join", lang),
                callback_data=f"join_pre:{game_day_id}"
            ),
            InlineKeyboardButton(text=t("btn_decline", lang), callback_data=f"decline:{game_day_id}"),
        )
    else:
        builder.row(
            InlineKeyboardButton(text="🔒 Набор закрыт", callback_data="closed"),
        )
    builder.row(
        InlineKeyboardButton(text="🔙 Назад", callback_data="main_menu"),
    )
    return builder.as_markup()


def join_confirm_kb(game_day_id: int, lang: str = "ru") -> InlineKeyboardMarkup:
    """Подтверждение регистрации + ссылка на Регламент."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text=t("btn_read_rules", lang),
            url="https://t.me/football_manager_uz_bot?start=rules"
        ),
    )
    builder.row(
        InlineKeyboardButton(text=t("btn_register", lang), callback_data=f"join:{game_day_id}"),
        InlineKeyboardButton(text=t("btn_cancel_reg", lang), callback_data=f"decline_pre:{game_day_id}"),
    )
    return builder.as_markup()


def confirm_attendance_kb(game_day_id: int, lang: str = "ru") -> InlineKeyboardMarkup:
    """Кнопки финального подтверждения участия."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text=t("btn_confirm_yes", lang), callback_data=f"confirm_yes:{game_day_id}"),
        InlineKeyboardButton(text=t("btn_confirm_no", lang), callback_data=f"confirm_no:{game_day_id}"),
    )
    return builder.as_markup()


def game_day_action_kb(game_day_id: int) -> InlineKeyboardMarkup:
    """Кнопки управления игровым днём для Админа."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="👥 Список игроков", callback_data=f"gd_players:{game_day_id}"),
        InlineKeyboardButton(text="💰 Отметить оплату", callback_data=f"gd_payment:{game_day_id}"),
    )
    builder.row(
        InlineKeyboardButton(text="📢 Разослать анонс", callback_data=f"gd_announce:{game_day_id}"),
        InlineKeyboardButton(text="💸 Финансовый итог", callback_data=f"gd_finance:{game_day_id}"),
    )
    builder.row(
        InlineKeyboardButton(text="📅 Напомнить (за день)", callback_data=f"gd_remind_before:{game_day_id}"),
        InlineKeyboardButton(text="⏰ Напомнить (сегодня)", callback_data=f"gd_remind_today:{game_day_id}"),
    )
    builder.row(
        InlineKeyboardButton(text="🎲 Авто-команды", callback_data=f"gd_auto_teams:{game_day_id}"),
        InlineKeyboardButton(text="✋ Вручную", callback_data=f"ref_setup_teams:{game_day_id}"),
    )
    builder.row(
        InlineKeyboardButton(text="✏️ Переименовать команды", callback_data=f"gd_rename_teams:{game_day_id}"),
    )
    builder.row(
        InlineKeyboardButton(text="📢 Запустить опрос", callback_data=f"gd_poll:{game_day_id}"),
    )
    builder.row(
        InlineKeyboardButton(text="📅 Расписание матчей", callback_data=f"gd_schedule:{game_day_id}"),
    )
    builder.row(
        InlineKeyboardButton(text="🏆 Итоги турнира", callback_data=f"gd_tournament_results:{game_day_id}"),
    )
    builder.row(
        InlineKeyboardButton(text="📢 Разослать итоги", callback_data=f"gd_post_results:{game_day_id}"),
        InlineKeyboardButton(text="📣 В канал", callback_data=f"gd_to_channel:{game_day_id}"),
    )
    builder.row(
        InlineKeyboardButton(text="❌ Отменить игру", callback_data=f"gd_cancel:{game_day_id}"),
        InlineKeyboardButton(text="🗑 Удалить игру", callback_data=f"gd_delete:{game_day_id}"),
    )
    builder.row(
        InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back"),
    )
    return builder.as_markup()


def delete_confirm_kb(game_day_id: int) -> InlineKeyboardMarkup:
    """Подтверждение удаления игрового дня."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="🗑 Да, удалить навсегда", callback_data=f"gd_delete_ok:{game_day_id}"),
    )
    builder.row(
        InlineKeyboardButton(text="↩️ Отмена", callback_data=f"gd_players:{game_day_id}"),
    )
    return builder.as_markup()

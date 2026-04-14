from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from app.database.models import Position, POSITION_LABELS


def position_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for pos, label in POSITION_LABELS.items():
        builder.button(text=label, callback_data=f"pos:{pos.value}")
    builder.adjust(2)
    return builder.as_markup()


def self_rating_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for i in range(1, 11):
        builder.button(text=str(i), callback_data=f"selfrating:{i}")
    builder.adjust(5)
    return builder.as_markup()

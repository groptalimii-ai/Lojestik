from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def main_menu() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="🚚 أريد نقل حمولة", callback_data="menu:newload")
    builder.button(text="🚛 لدي شاحنة", callback_data="menu:registercarrier")
    builder.button(text="🔎 البحث عن حمولة", callback_data="menu:findload")
    builder.button(text="📦 طلباتي", callback_data="menu:myloads")
    builder.button(text="💰 أرباحي", callback_data="menu:mydeals")
    builder.button(text="📞 الدعم", callback_data="menu:support")
    builder.adjust(1)
    return builder.as_markup()


def confirm_extraction_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ تأكيد الحمولة", callback_data="load:confirm")
    builder.button(text="✏️ تعديل", callback_data="load:edit")
    builder.button(text="❌ إلغاء", callback_data="load:cancel")
    builder.adjust(1)
    return builder.as_markup()


def match_response_kb(match_id: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ قبول", callback_data=f"match:accept:{match_id}")
    builder.button(text="❌ رفض", callback_data=f"match:reject:{match_id}")
    builder.button(text="💬 تفاوض", callback_data=f"match:negotiate:{match_id}")
    builder.adjust(3)
    return builder.as_markup()


def yes_no_kb(yes_data: str, no_data: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="نعم", callback_data=yes_data)
    builder.button(text="لا", callback_data=no_data)
    builder.adjust(2)
    return builder.as_markup()

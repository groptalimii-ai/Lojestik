"""
Global error handler for the bot.

Previously, an unhandled exception inside any handler (a backend timeout,
an unexpected 500, a bad index into `data`) would just crash that update's
processing -- aiogram logs it to stderr, but the driver sees nothing at
all and is left stuck mid-FSM with no way forward except /start. This
middleware wraps every update so:

1. The user always gets a reply, even on failure.
2. The FSM state is cleared, so a stuck flow doesn't silently block every
   future message (aiogram FSM handlers only match their own state).
3. The real exception is logged with enough context to debug it.
"""
import logging

from aiogram import BaseMiddleware
from aiogram.fsm.context import FSMContext
from aiogram.types import TelegramObject

logger = logging.getLogger("freightai.bot")

GENERIC_ERROR_MESSAGE = (
    "⚠️ حدث خطأ غير متوقع أثناء تنفيذ طلبك. تمت إعادة تعيين المحادثة، "
    "الرجاء المحاولة مرة أخرى من /start أو التواصل مع الدعم /support."
)


class ErrorHandlingMiddleware(BaseMiddleware):
    async def __call__(self, handler, event: TelegramObject, data: dict):
        try:
            return await handler(event, data)
        except Exception:
            logger.exception("Unhandled exception while processing update: %s", event)

            state: FSMContext | None = data.get("state")
            if state is not None:
                try:
                    await state.clear()
                except Exception:
                    logger.exception("Failed to clear FSM state after error")

            message = getattr(event, "message", None) or event
            try:
                if hasattr(message, "answer"):
                    await message.answer(GENERIC_ERROR_MESSAGE)
            except Exception:
                logger.exception("Failed to notify user about the error")

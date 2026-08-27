import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from bot.config import BOT_SERVICE_SECRET, TELEGRAM_BOT_TOKEN
from bot.handlers import carrier, intake, newload, pricing, start, truck
from bot.keepalive import keepalive_loop
from bot.middlewares import ErrorHandlingMiddleware

logging.basicConfig(level=logging.INFO)


async def main():
    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not set. Add it to your .env file.")
    if not BOT_SERVICE_SECRET:
        raise RuntimeError(
            "BOT_SERVICE_SECRET is not set. It must match the backend's "
            "BOT_SERVICE_SECRET or /auth/telegram will reject every request."
        )

    bot = Bot(token=TELEGRAM_BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())
    dp.update.outer_middleware(ErrorHandlingMiddleware())

    dp.include_router(start.router)
    dp.include_router(newload.router)
    dp.include_router(carrier.router)
    dp.include_router(truck.router)
    dp.include_router(pricing.router)
    dp.include_router(intake.router)  # catch-all for the admin channel -- keep last

    # Runs alongside polling, never awaited directly -- see keepalive.py
    # for why this exists (Supabase free-tier project pause prevention).
    # Reference kept in a variable deliberately: asyncio only holds a WEAK
    # reference to tasks created via create_task(), so a fire-and-forget
    # call with no kept reference can be garbage-collected mid-run --
    # a real, documented asyncio pitfall, not a hypothetical one.
    _keepalive_task = asyncio.create_task(keepalive_loop())

    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())

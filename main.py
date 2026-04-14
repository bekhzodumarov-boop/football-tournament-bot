import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.memory import MemoryStorage

from app.config import settings
from app.database.engine import create_db_and_tables
from app.handlers import register_all_handlers
from app.middlewares.auth import AuthMiddleware

logging.basicConfig(
    level=logging.DEBUG if settings.DEBUG else logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def get_storage():
    """Redis если доступен, иначе Memory (для локальной разработки)"""
    if settings.REDIS_URL and not settings.REDIS_URL.startswith("memory"):
        try:
            from aiogram.fsm.storage.redis import RedisStorage
            return RedisStorage.from_url(settings.REDIS_URL)
        except Exception:
            pass
    logger.warning("Redis недоступен — используется MemoryStorage (FSM сбрасывается при рестарте)")
    return MemoryStorage()


async def main():
    bot = Bot(
        token=settings.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=get_storage())

    # Middlewares
    dp.message.middleware(AuthMiddleware())
    dp.callback_query.middleware(AuthMiddleware())

    # Handlers
    register_all_handlers(dp)

    # Создать таблицы в БД
    await create_db_and_tables()
    logger.info("Database ready")

    # Уведомить Админа о запуске
    for admin_id in settings.ADMIN_IDS:
        try:
            await bot.send_message(admin_id, "✅ Бот запущен и готов к работе!")
        except Exception as e:
            logger.warning(f"Не удалось уведомить Админа {admin_id}: {e}")

    logger.info("Bot started: @football_manager_2026_bot")

    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await bot.session.close()
        logger.info("Bot stopped")


if __name__ == "__main__":
    asyncio.run(main())

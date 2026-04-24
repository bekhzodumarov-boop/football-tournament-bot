import asyncio
import logging
import os

from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.memory import MemoryStorage

from app.config import settings
from app.database.engine import create_db_and_tables
from app.handlers import register_all_handlers
from app.middlewares.auth import AuthMiddleware
from app.scheduler import scheduler
from app.reminders import set_bot, reschedule_all_reminders
from app.webapp import create_webapp

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

    # Сбросить webhook и завершить конкурирующие getUpdates сессии
    logger.info("Clearing webhook...")
    try:
        await bot.delete_webhook(drop_pending_updates=False)
        logger.info("Webhook cleared")
    except Exception as e:
        logger.error(f"delete_webhook failed: {e}", exc_info=True)

    # Создать таблицы в БД
    logger.info("Initializing database...")
    await create_db_and_tables()
    logger.info("Database ready")

    # Запустить веб-сервер (WebApp + API)
    port = int(os.getenv("PORT", 8080))
    logger.info(f"Starting WebApp on port {port}...")
    webapp = create_webapp()
    runner = web.AppRunner(webapp)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info(f"WebApp server started on port {port}")

    # Запустить планировщик (таймеры матчей + напоминания)
    scheduler.start()
    logger.info("Scheduler started")

    # Передать бота модулю напоминаний и восстановить jobs после рестарта
    set_bot(bot)
    try:
        await reschedule_all_reminders()
        logger.info("Reminders rescheduled")
    except Exception as e:
        logger.warning(f"reschedule_all_reminders warning: {e}")

    # Уведомить Админа о запуске
    for admin_id in settings.ADMIN_IDS:
        try:
            await bot.send_message(admin_id, "✅ Бот запущен и готов к работе!")
        except Exception as e:
            logger.warning(f"Не удалось уведомить Админа {admin_id}: {e}")

    logger.info("Bot started: @football_manager_uz_bot")

    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        scheduler.shutdown(wait=False)
        await runner.cleanup()
        await bot.session.close()
        logger.info("Bot stopped")


if __name__ == "__main__":
    asyncio.run(main())

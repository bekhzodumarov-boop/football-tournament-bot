import logging
from typing import Callable, Dict, Any, Awaitable
from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject
from sqlalchemy import select
from app.database.engine import AsyncSessionFactory
from app.database.models import Player

logger = logging.getLogger(__name__)


class AuthMiddleware(BaseMiddleware):
    """
    Прокидывает в handler:
      - data['player']  — объект Player если зарегистрирован, иначе None
      - data['session'] — AsyncSession
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        try:
            async with AsyncSessionFactory() as session:
                data["session"] = session

                user = data.get("event_from_user")
                if user:
                    result = await session.execute(
                        select(Player).where(Player.telegram_id == user.id)
                    )
                    data["player"] = result.scalar_one_or_none()
                else:
                    data["player"] = None

                return await handler(event, data)
        except Exception as e:
            user = data.get("event_from_user")
            uid = user.id if user else "unknown"
            logger.error(f"AuthMiddleware crashed for user {uid}: {type(e).__name__}: {e}", exc_info=True)
            # Попробовать ответить пользователю об ошибке
            try:
                if isinstance(event, Message):
                    await event.answer("⚠️ Внутренняя ошибка. Попробуй ещё раз.")
            except Exception:
                pass
            raise

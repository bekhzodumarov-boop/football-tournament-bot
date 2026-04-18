import logging
from datetime import date
from typing import Callable, Dict, Any, Awaitable
from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from app.database.engine import AsyncSessionFactory
from app.database.models import Player, UserActivity

logger = logging.getLogger(__name__)


class AuthMiddleware(BaseMiddleware):
    """
    Прокидывает в handler:
      - data['player']  — объект Player если зарегистрирован, иначе None
      - data['session'] — AsyncSession
    Также логирует ежедневную активность для DAU/WAU/MAU.
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

                    # Логируем активность (один раз в день на пользователя)
                    try:
                        today = date.today()
                        stmt = pg_insert(UserActivity).values(
                            telegram_id=user.id,
                            activity_date=today,
                        ).on_conflict_do_nothing(
                            constraint="uq_user_activity_day"
                        )
                        await session.execute(stmt)
                        await session.commit()
                    except Exception:
                        # Не блокируем работу бота при ошибке трекинга
                        pass
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

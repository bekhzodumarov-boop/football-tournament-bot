from pydantic_settings import BaseSettings
from pydantic import field_validator
from typing import List

# Рантайм-кэш ID создателей лиг (грузится при старте + обновляется при создании лиги)
_league_admin_ids: set[int] = set()


def register_league_admin(user_id: int) -> None:
    """Добавить создателя лиги в рантайм-кэш админов."""
    _league_admin_ids.add(user_id)


def load_league_admins(ids: list[int]) -> None:
    """Загрузить всех создателей лиг из БД при старте."""
    _league_admin_ids.update(ids)


class Settings(BaseSettings):
    BOT_TOKEN: str
    ADMIN_IDS: List[int] = []
    DEVELOPER_IDS: List[int] = []  # Telegram ID разработчиков бота

    DATABASE_URL: str
    REDIS_URL: str = "memory://"

    TIMEZONE: str = "Asia/Tashkent"
    DEBUG: bool = False

    DEFAULT_PLAYER_LIMIT: int = 20
    DEFAULT_COST: int = 0
    REGISTRATION_DEADLINE_HOURS: int = 3

    # Telegram WebApp — публичный URL этого Railway-сервиса
    # Пример: https://football-bot-production.railway.app
    WEBAPP_URL: str = ""

    # Telegram username бота (без @) — нужен для генерации инвайт-ссылок
    BOT_USERNAME: str = "football_manager_uz_bot"

    # Telegram channel ID для публикации итогов (например: @mychannel или -1001234567890)
    CHANNEL_ID: str = ""

    # Google Sheets — JSON-строка сервисного аккаунта и ID таблицы
    GOOGLE_CREDENTIALS_JSON: str = ""
    GOOGLE_SHEET_ID: str = ""

    @field_validator("ADMIN_IDS", "DEVELOPER_IDS", mode="before")
    @classmethod
    def parse_admin_ids(cls, v):
        if isinstance(v, str):
            return [int(x.strip()) for x in v.split(",") if x.strip()]
        if isinstance(v, int):
            return [v]
        return v

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"   # игнорировать лишние поля из .env

    def is_admin(self, user_id: int) -> bool:
        return user_id in self.ADMIN_IDS or user_id in _league_admin_ids

    def is_developer(self, user_id: int) -> bool:
        """Разработчик бота — доступ к глобальной аналитике."""
        return user_id in self.DEVELOPER_IDS or user_id in self.ADMIN_IDS


settings = Settings()

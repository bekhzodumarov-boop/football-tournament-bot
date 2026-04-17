from pydantic_settings import BaseSettings
from pydantic import field_validator
from typing import List


class Settings(BaseSettings):
    BOT_TOKEN: str
    ADMIN_IDS: List[int] = []

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
    BOT_USERNAME: str = "football_manager_2026_bot"

    # Telegram channel ID для публикации итогов (например: @mychannel или -1001234567890)
    CHANNEL_ID: str = ""

    # Google Sheets — JSON-строка сервисного аккаунта и ID таблицы
    GOOGLE_CREDENTIALS_JSON: str = ""
    GOOGLE_SHEET_ID: str = ""

    @field_validator("ADMIN_IDS", mode="before")
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
        return user_id in self.ADMIN_IDS


settings = Settings()

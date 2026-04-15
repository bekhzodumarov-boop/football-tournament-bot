from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from app.config import settings
from app.database.models import Base


def _fix_db_url(url: str) -> str:
    """
    Railway даёт postgresql:// — SQLAlchemy async требует postgresql+asyncpg://
    SQLite оставляем как есть.
    """
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+asyncpg://", 1)
    return url


db_url = _fix_db_url(settings.DATABASE_URL)

connect_args = {}
if db_url.startswith("sqlite"):
    connect_args = {"check_same_thread": False}

engine = create_async_engine(
    db_url,
    echo=settings.DEBUG,
    connect_args=connect_args,
)

AsyncSessionFactory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def create_db_and_tables():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _run_migrations(conn)


async def _run_migrations(conn):
    """
    Простые ALTER TABLE миграции — добавляем колонки если их нет.
    Безопасно запускать при каждом старте (IF NOT EXISTS / IF EXISTS).
    """
    is_sqlite = db_url.startswith("sqlite")

    if is_sqlite:
        # SQLite не поддерживает IF NOT EXISTS в ALTER TABLE
        # Проверяем через PRAGMA
        result = await conn.execute(text("PRAGMA table_info(players)"))
        columns = [row[1] for row in result.fetchall()]
        if "is_referee" not in columns:
            await conn.execute(text(
                "ALTER TABLE players ADD COLUMN is_referee BOOLEAN NOT NULL DEFAULT 0"
            ))
    else:
        # PostgreSQL поддерживает IF NOT EXISTS
        await conn.execute(text(
            "ALTER TABLE players ADD COLUMN IF NOT EXISTS is_referee BOOLEAN NOT NULL DEFAULT FALSE"
        ))


async def get_session() -> AsyncSession:
    async with AsyncSessionFactory() as session:
        yield session

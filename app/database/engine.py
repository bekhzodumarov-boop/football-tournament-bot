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
    # CREATE TABLE / ALTER TABLE — внутри транзакции (обычный режим)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _run_migrations(conn)

    # ALTER TYPE ... ADD VALUE нельзя запускать внутри транзакции в PostgreSQL
    # Запускаем отдельно в режиме AUTOCOMMIT
    if not db_url.startswith("sqlite"):
        async with engine.connect() as conn:
            await conn.execution_options(isolation_level="AUTOCOMMIT")
            await _run_enum_migrations(conn)


async def _run_migrations(conn):
    """
    Простые ALTER TABLE миграции — добавляем колонки если их нет.
    Безопасно запускать при каждом старте (IF NOT EXISTS / IF EXISTS).
    """
    is_sqlite = db_url.startswith("sqlite")

    if is_sqlite:
        # SQLite не поддерживает IF NOT EXISTS в ALTER TABLE — проверяем через PRAGMA
        result = await conn.execute(text("PRAGMA table_info(players)"))
        columns = [row[1] for row in result.fetchall()]
        if "is_referee" not in columns:
            await conn.execute(text(
                "ALTER TABLE players ADD COLUMN is_referee BOOLEAN NOT NULL DEFAULT 0"
            ))
        if "photo_file_id" not in columns:
            await conn.execute(text(
                "ALTER TABLE players ADD COLUMN photo_file_id VARCHAR(200)"
            ))
        result2 = await conn.execute(text("PRAGMA table_info(matches)"))
        match_cols = [row[1] for row in result2.fetchall()]
        if "duration_min" not in match_cols:
            await conn.execute(text(
                "ALTER TABLE matches ADD COLUMN duration_min INTEGER NOT NULL DEFAULT 20"
            ))
        if "goals_to_win" not in match_cols:
            await conn.execute(text(
                "ALTER TABLE matches ADD COLUMN goals_to_win INTEGER NOT NULL DEFAULT 3"
            ))
    else:
        # PostgreSQL поддерживает IF NOT EXISTS
        await conn.execute(text(
            "ALTER TABLE players ADD COLUMN IF NOT EXISTS is_referee BOOLEAN NOT NULL DEFAULT FALSE"
        ))
        await conn.execute(text(
            "ALTER TABLE players ADD COLUMN IF NOT EXISTS photo_file_id VARCHAR(200)"
        ))
        await conn.execute(text(
            "ALTER TABLE matches ADD COLUMN IF NOT EXISTS duration_min INTEGER NOT NULL DEFAULT 20"
        ))
        await conn.execute(text(
            "ALTER TABLE matches ADD COLUMN IF NOT EXISTS goals_to_win INTEGER NOT NULL DEFAULT 3"
        ))


async def _run_enum_migrations(conn) -> None:
    """
    ALTER TYPE ... ADD VALUE нельзя запускать внутри транзакции в PostgreSQL.
    Эта функция вызывается отдельно в режиме AUTOCOMMIT.
    """
    await conn.execute(text(
        "ALTER TYPE attendanceresponse ADD VALUE IF NOT EXISTS 'waitlist'"
    ))


async def get_session() -> AsyncSession:
    async with AsyncSessionFactory() as session:
        yield session

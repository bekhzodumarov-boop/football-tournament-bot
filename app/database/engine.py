from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from app.config import settings
from app.database.models import Base


def _fix_db_url(url: str) -> str:
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
    # CREATE TABLE — внутри транзакции
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _run_migrations(conn)

    # ALTER TYPE нельзя внутри транзакции в PostgreSQL
    if not db_url.startswith("sqlite"):
        async with engine.connect() as conn:
            await conn.execution_options(isolation_level="AUTOCOMMIT")
            await _run_enum_migrations(conn)

    # Создать лигу по умолчанию и привязать существующие данные
    await _ensure_default_league()

    # Заполнить player_leagues из существующих player.league_id
    await _migrate_player_leagues()

    # Загрузить ID создателей лиг в рантайм-кэш
    await _load_league_admins()


async def _run_migrations(conn):
    """ALTER TABLE миграции — добавляем колонки если их нет."""
    is_sqlite = db_url.startswith("sqlite")

    if is_sqlite:
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
        if "league_id" not in columns:
            await conn.execute(text(
                "ALTER TABLE players ADD COLUMN league_id INTEGER"
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

        result3 = await conn.execute(text("PRAGMA table_info(game_days)"))
        gd_cols = [row[1] for row in result3.fetchall()]
        if "league_id" not in gd_cols:
            await conn.execute(text(
                "ALTER TABLE game_days ADD COLUMN league_id INTEGER"
            ))
        if "tournament_number" not in gd_cols:
            await conn.execute(text(
                "ALTER TABLE game_days ADD COLUMN tournament_number INTEGER"
            ))

        result4 = await conn.execute(text("PRAGMA table_info(rating_rounds)"))
        rr_cols = [row[1] for row in result4.fetchall()]
        if "game_day_id" not in rr_cols:
            await conn.execute(text(
                "ALTER TABLE rating_rounds ADD COLUMN game_day_id INTEGER"
            ))

        result5 = await conn.execute(text("PRAGMA table_info(matches)"))
        match_cols2 = [row[1] for row in result5.fetchall()]
        if "match_stage" not in match_cols2:
            await conn.execute(text(
                "ALTER TABLE matches ADD COLUMN match_stage VARCHAR(20) DEFAULT 'group'"
            ))

        result6 = await conn.execute(text("PRAGMA table_info(players)"))
        player_cols2 = [row[1] for row in result6.fetchall()]
        if "language" not in player_cols2:
            await conn.execute(text(
                "ALTER TABLE players ADD COLUMN language VARCHAR(5) NOT NULL DEFAULT 'ru'"
            ))
        if "gender" not in player_cols2:
            await conn.execute(text(
                "ALTER TABLE players ADD COLUMN gender VARCHAR(1) NOT NULL DEFAULT 'm'"
            ))
        if "match_order" not in match_cols2:
            await conn.execute(text(
                "ALTER TABLE matches ADD COLUMN match_order INTEGER DEFAULT 0"
            ))

        result7 = await conn.execute(text("PRAGMA table_info(leagues)"))
        league_cols = [row[1] for row in result7.fetchall()]
        if "card_number" not in league_cols:
            await conn.execute(text(
                "ALTER TABLE leagues ADD COLUMN card_number VARCHAR(50)"
            ))
    else:
        # PostgreSQL
        await conn.execute(text(
            "ALTER TABLE players ADD COLUMN IF NOT EXISTS is_referee BOOLEAN NOT NULL DEFAULT FALSE"
        ))
        await conn.execute(text(
            "ALTER TABLE players ADD COLUMN IF NOT EXISTS photo_file_id VARCHAR(200)"
        ))
        await conn.execute(text(
            "ALTER TABLE players ADD COLUMN IF NOT EXISTS league_id INTEGER REFERENCES leagues(id)"
        ))
        await conn.execute(text(
            "ALTER TABLE matches ADD COLUMN IF NOT EXISTS duration_min INTEGER NOT NULL DEFAULT 20"
        ))
        await conn.execute(text(
            "ALTER TABLE matches ADD COLUMN IF NOT EXISTS goals_to_win INTEGER NOT NULL DEFAULT 3"
        ))
        await conn.execute(text(
            "ALTER TABLE game_days ADD COLUMN IF NOT EXISTS league_id INTEGER REFERENCES leagues(id)"
        ))
        await conn.execute(text(
            "ALTER TABLE game_days ADD COLUMN IF NOT EXISTS tournament_number INTEGER"
        ))
        await conn.execute(text(
            "ALTER TABLE players ADD COLUMN IF NOT EXISTS phone VARCHAR(30)"
        ))
        await conn.execute(text(
            "ALTER TABLE rating_rounds ADD COLUMN IF NOT EXISTS game_day_id INTEGER REFERENCES game_days(id)"
        ))
        await conn.execute(text(
            "ALTER TABLE matches ADD COLUMN IF NOT EXISTS match_stage VARCHAR(20) DEFAULT 'group'"
        ))
        await conn.execute(text(
            "ALTER TABLE players ADD COLUMN IF NOT EXISTS language VARCHAR(5) DEFAULT 'ru' NOT NULL"
        ))
        await conn.execute(text(
            "ALTER TABLE players ADD COLUMN IF NOT EXISTS gender VARCHAR(1) DEFAULT 'm' NOT NULL"
        ))
        await conn.execute(text(
            "ALTER TABLE matches ADD COLUMN IF NOT EXISTS match_order INTEGER DEFAULT 0"
        ))
        await conn.execute(text(
            "ALTER TABLE leagues ADD COLUMN IF NOT EXISTS card_number VARCHAR(50)"
        ))
        await conn.execute(text(
            "ALTER TABLE leagues ADD COLUMN IF NOT EXISTS password VARCHAR(100)"
        ))
        await conn.execute(text(
            "ALTER TABLE leagues ADD COLUMN IF NOT EXISTS default_player_limit INTEGER DEFAULT 20"
        ))
        # user_activity создаётся через Base.metadata.create_all — дополнительных миграций не требуется


async def _run_enum_migrations(conn) -> None:
    """ALTER TYPE ... ADD VALUE нельзя запускать внутри транзакции."""
    # PostgreSQL хранит enum как uppercase-имена (YES, NO, ...),
    # поэтому добавляем WAITLIST в uppercase
    await conn.execute(text(
        "ALTER TYPE attendanceresponse ADD VALUE IF NOT EXISTS 'WAITLIST'"
    ))
    # Создать тип league_role_type если его нет
    await conn.execute(text(
        "DO $$ BEGIN "
        "  CREATE TYPE league_role_type AS ENUM ('admin', 'player'); "
        "EXCEPTION WHEN duplicate_object THEN NULL; "
        "END $$;"
    ))


async def _migrate_player_leagues() -> None:
    """
    Заполняет таблицу player_leagues из существующих player.league_id.
    Создаёт записи для всех игроков, у которых есть league_id, но нет записи в player_leagues.
    Роль admin — для создателей лиг, иначе player.
    """
    from app.database.models import PlayerLeague, Player, League, LeagueRole
    from sqlalchemy import select, insert

    async with AsyncSessionFactory() as session:
        # Получить всех игроков с league_id
        players_result = await session.execute(
            select(Player).where(Player.league_id.is_not(None))
        )
        players = players_result.scalars().all()

        # Получить все лиги (для проверки admin_telegram_id)
        leagues_result = await session.execute(select(League))
        leagues = {lg.id: lg for lg in leagues_result.scalars().all()}

        for player in players:
            # Проверить, нет ли уже записи
            existing = await session.execute(
                select(PlayerLeague).where(
                    PlayerLeague.player_id == player.id,
                    PlayerLeague.league_id == player.league_id,
                )
            )
            if existing.scalar_one_or_none() is not None:
                continue

            league = leagues.get(player.league_id)
            if not league:
                continue

            role = (
                LeagueRole.ADMIN
                if league.admin_telegram_id == player.telegram_id
                else LeagueRole.PLAYER
            )
            session.add(PlayerLeague(
                player_id=player.id,
                league_id=player.league_id,
                role=role,
            ))

        await session.commit()


async def _ensure_default_league() -> None:
    """
    При первом запуске создаёт лигу по умолчанию и привязывает к ней
    всех существующих игроков и игровые дни без league_id.
    """
    from app.database.models import League, Player, GameDay
    from app.database.models import _gen_invite_code
    from sqlalchemy import select, update

    async with AsyncSessionFactory() as session:
        # Проверить есть ли хоть одна лига
        result = await session.execute(select(League).limit(1))
        existing = result.scalar_one_or_none()

        if not existing:
            # Создать лигу по умолчанию
            default_league = League(
                name="Football Manager",
                invite_code=_gen_invite_code(),
                admin_telegram_id=settings.ADMIN_IDS[0] if settings.ADMIN_IDS else 0,
                city="Default",
            )
            session.add(default_league)
            await session.flush()  # получить id

            # Привязать всех существующих игроков
            await session.execute(
                update(Player)
                .where(Player.league_id.is_(None))
                .values(league_id=default_league.id)
            )
            # Привязать все существующие игровые дни
            await session.execute(
                update(GameDay)
                .where(GameDay.league_id.is_(None))
                .values(league_id=default_league.id)
            )
            await session.commit()
        else:
            # Лига есть — привязать новых игроков/дни без league_id к первой лиге
            await session.execute(
                update(Player)
                .where(Player.league_id.is_(None))
                .values(league_id=existing.id)
            )
            await session.execute(
                update(GameDay)
                .where(GameDay.league_id.is_(None))
                .values(league_id=existing.id)
            )
            await session.commit()


async def _load_league_admins() -> None:
    """Загрузить ID создателей всех активных лиг в рантайм-кэш."""
    from app.config import load_league_admins
    from app.database.models import League
    from sqlalchemy import select

    async with AsyncSessionFactory() as session:
        result = await session.execute(
            select(League.admin_telegram_id).where(League.is_active == True)
        )
        ids = [row[0] for row in result.fetchall() if row[0]]
        load_league_admins(ids)


async def get_session() -> AsyncSession:
    async with AsyncSessionFactory() as session:
        yield session

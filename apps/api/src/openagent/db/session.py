from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from openagent.core.config import get_settings
from openagent.db.models.base import Base


engine = None
async_session_maker = None


def init_db() -> None:
    global engine, async_session_maker
    settings = get_settings()
    engine = create_async_engine(
        settings.DATABASE_URL,
        echo=settings.is_development,
        pool_pre_ping=True,
        pool_size=10,
        max_overflow=20,
    )
    async_session_maker = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )


async def get_db() -> AsyncSession:
    if async_session_maker is None:
        init_db()
    async with async_session_maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def close_db() -> None:
    global engine
    if engine:
        await engine.dispose()
        engine = None
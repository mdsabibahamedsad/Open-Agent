import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.pool import StaticPool

from openagent.db.session import Base
from openagent.core.config import get_settings


# Use the application's database URL for testing
# In CI/CD, this should point to a PostgreSQL test database
# For local development without PostgreSQL, SQLite can be used but ENUM tests will be skipped
TEST_DATABASE_URL = get_settings().DATABASE_URL


@pytest_asyncio.fixture(scope="session")
async def test_engine():
    # Use StaticPool for SQLite, regular pool for PostgreSQL
    connect_args = {}
    poolclass = None
    
    if TEST_DATABASE_URL.startswith("sqlite"):
        connect_args = {"check_same_thread": False}
        poolclass = StaticPool
    
    engine = create_async_engine(
        TEST_DATABASE_URL,
        echo=False,
        poolclass=poolclass,
        connect_args=connect_args,
    )
    
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    yield engine
    
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(test_engine) -> AsyncSession:
    async_session_maker = async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False
    )
    
    async with async_session_maker() as session:
        yield session
        await session.rollback()
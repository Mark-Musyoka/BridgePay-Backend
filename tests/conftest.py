import os

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.pool import NullPool
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.limiter import limiter
from app.db.base import Base
from app.db.session import get_db
from app.main import app

# Uses a dedicated test database, never the dev one — tests create and drop
# tables freely, which would be destructive against real data.
TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost/bridgepay_test",
)

# NullPool: pytest-asyncio gives each test function its own event loop by
# default. A pooled connection created under one test's loop is invalid when
# reused under the next test's loop ("another operation is in progress" /
# "attached to a different loop") — NullPool opens a fresh connection per
# use instead of reusing one across loops.
test_engine = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)
TestSessionLocal = async_sessionmaker(bind=test_engine, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture(autouse=True)
async def setup_db():
    """Fresh schema for every test — simplest way to guarantee isolation
    given the ledger logic depends heavily on exact starting state.
    Also resets the in-memory rate limiter, which is otherwise shared
    global state across the whole test run and would make tests interfere
    with each other's request counts."""
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    limiter.reset()
    yield


async def _override_get_db():
    async with TestSessionLocal() as session:
        yield session


app.dependency_overrides[get_db] = _override_get_db


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
async def db_session():
    async with TestSessionLocal() as session:
        yield session

"""Test fixtures and utilities."""

import os

# Set required env vars BEFORE importing app code (some read at import time)
os.environ.setdefault("API_KEY_MASTER_KEY", "test-master-key-32bytes-long!!!")
os.environ.setdefault("SECRET_KEY", "test-secret-key-32bytes-long!!!")

from collections.abc import AsyncIterator
from typing import AsyncGenerator
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.db.session import Base, get_db
from app.main import app
from tests.database_safety import resolve_test_database

# Allow override via env var; default to in-memory SQLite for fast tests
TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL",
)


@pytest.fixture(autouse=True)
def isolate_interview_demo_settings(monkeypatch):
    """默认测试普通模式，避免新控制模块连接运行中的业务数据库。

    演示控制测试自行替换该会话，以验证开启、额度及失败场景。
    """
    from app.services import interview_demo
    from unittest.mock import AsyncMock
    @asynccontextmanager
    async def session():
        yield SimpleNamespace(scalars=AsyncMock(return_value=SimpleNamespace(all=lambda: [])))
    monkeypatch.setattr(interview_demo, 'AsyncSessionLocal', session)


@pytest_asyncio.fixture(scope="session")
async def test_engine():
    """Create a test database engine and tables."""
    target = resolve_test_database(os.environ)
    print(
        "\nTest database target: "
        f"{target.backend} / {target.host or 'in-memory'} / {target.database}"
    )
    engine = create_async_engine(
        TEST_DATABASE_URL or "",
        echo=False,
        poolclass=NullPool,
        pool_pre_ping=True,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(test_engine) -> AsyncGenerator[AsyncSession, None]:
    """Create a fresh database session for each test (auto-rollback + cleanup)."""
    async_session = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as session:
        yield session
        await session.rollback()
        # Clean up committed test data so tests don't leak
        from app.models.config import LLMProviderConfig, SystemSetting
        await session.execute(delete(SystemSetting))
        await session.execute(delete(LLMProviderConfig))
        await session.commit()


@pytest_asyncio.fixture
async def client(db_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    """Create an async test client with overridden DB dependency."""
    async def override_get_db() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_db] = override_get_db

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()

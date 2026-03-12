from __future__ import annotations

import os
from collections.abc import AsyncGenerator

import asyncpg
import pytest
import pytest_asyncio

from voxagent.config import Config
from voxagent.models import TenantConfig


@pytest_asyncio.fixture(scope="session")
async def db_pool() -> AsyncGenerator[asyncpg.Pool, None]:
    """Create and yield an asyncpg connection pool to test database.

    Requires TEST_DATABASE_URL environment variable to be set.
    Raises RuntimeError if TEST_DATABASE_URL is missing.
    """
    database_url = os.environ.get("TEST_DATABASE_URL")
    if database_url is None:
        raise RuntimeError("Required environment variable 'TEST_DATABASE_URL' is not set")

    pool = await asyncpg.create_pool(
        database_url,
        min_size=1,
        max_size=10,
        command_timeout=60,
    )
    if pool is None:
        raise RuntimeError("asyncpg.create_pool returned None")

    yield pool

    await pool.close()


@pytest_asyncio.fixture
async def db_conn(db_pool: asyncpg.Pool) -> AsyncGenerator[asyncpg.pool.PoolConnectionProxy, None]:
    async with db_pool.acquire() as conn:
        tx = conn.transaction()
        await tx.start()
        yield conn
        await tx.rollback()


@pytest.fixture
def app_config() -> Config:
    """Return a Config instance with test values.

    Sets required environment variables temporarily and creates Config().
    """
    test_env_vars = {
        "DATABASE_URL": "postgresql://test:test@localhost/voxagent_test",
        "LIVEKIT_URL": "ws://localhost:7880",
        "LIVEKIT_API_KEY": "test-api-key",
        "LIVEKIT_API_SECRET": "test-api-secret",
        "OLLAMA_BASE_URL": "http://localhost:11434",
        "SERVER_HOST": "127.0.0.1",
        "SERVER_PORT": "8000",
        "LOG_LEVEL": "DEBUG",
    }

    original_env = {}
    for key, value in test_env_vars.items():
        original_env[key] = os.environ.get(key)
        os.environ[key] = value

    try:
        config = Config()
    finally:
        for key, value in original_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    return config


@pytest.fixture
def sample_tenant() -> TenantConfig:
    """Return a TenantConfig instance with test data."""
    return TenantConfig(
        name="Test Tenant",
        domain="test.example.com",
        greeting="Welcome to the test assistant!",
        widget_color="#3b82f6",
        widget_position="bottom-left",
        allowed_origins=["https://test.example.com", "http://localhost:3000"],
    )

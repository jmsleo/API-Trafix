"""Shared fixtures for the test suite.

DB-backed tests run against a dedicated Postgres database (``trafix_test`` by
default, overridable with ``TEST_DATABASE_URL``). The session fixture creates
the database if missing, builds the schema from the SQLAlchemy models, then
applies the gate-cycle migration SQL as an idempotent no-op to prove the file
is valid against the current models.
"""

from __future__ import annotations

import os
from urllib.parse import urlparse, unquote

import asyncpg
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

import api_trafix.models  # noqa: F401  (registers every model on Base.metadata)
from api_trafix.config.database import Base

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://trafix:trafix@localhost:5432/trafix_test",
)

MIGRATION_SQL = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "migrations",
    "2026_08_14_gate_cycle_schema.sql",
)

MIGRATION_FEE_FIELDS_SQL = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "migrations",
    "2026_08_14_gate_cycle_fee_fields.sql",
)

MIGRATION_VEHICLE_PRICE_SQL = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "migrations",
    "2026_08_23_vehicle_type_price.sql",
)

with open(MIGRATION_SQL, encoding="utf-8") as _handle:
    MIGRATION_STATEMENTS = _handle.read()

with open(MIGRATION_FEE_FIELDS_SQL, encoding="utf-8") as _handle:
    MIGRATION_STATEMENTS += "\n" + _handle.read()

with open(MIGRATION_VEHICLE_PRICE_SQL, encoding="utf-8") as _handle:
    MIGRATION_STATEMENTS += "\n" + _handle.read()


def _pg_params() -> dict:
    parsed = urlparse(TEST_DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://", 1))
    return {
        "user": unquote(parsed.username or ""),
        "password": unquote(parsed.password or ""),
        "host": parsed.hostname or "localhost",
        "port": parsed.port or 5432,
        "database": parsed.path.lstrip("/"),
    }


async def _create_database_if_missing() -> None:
    params = _pg_params()
    dbname = params.pop("database")
    admin = await asyncpg.connect(**params, database="postgres")
    try:
        exists = await admin.fetchval(
            "SELECT 1 FROM pg_database WHERE datname = $1", dbname
        )
        if not exists:
            await admin.execute(f'CREATE DATABASE "{dbname}"')
    finally:
        await admin.close()


async def _apply_migration() -> None:
    """Run the gate-cycle migration SQL via raw asyncpg.

    ``asyncpg.Connection.execute`` handles multi-statement scripts (including
    ``--`` comments), which SQLAlchemy's ``text()`` does not.
    """
    params = _pg_params()
    conn = await asyncpg.connect(**params)
    try:
        await conn.execute(MIGRATION_STATEMENTS)
    finally:
        await conn.close()


@pytest_asyncio.fixture(scope="session")
async def db_engine():
    """An engine bound to a throwaway test database with the full schema."""
    await _create_database_if_missing()

    engine = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # The migration must already be a no-op on a freshly created schema; running
    # it here catches syntax errors / missing tables early.
    await _apply_migration()

    yield engine
    await engine.dispose()


@pytest_asyncio.fixture(scope="session")
async def db_sessionmaker(db_engine):
    return async_sessionmaker(db_engine, expire_on_commit=False)


@pytest_asyncio.fixture(autouse=True)
async def _close_redis_after_each_test():
    """Tear down the module-level Redis client per test.

    ``api_trafix.config.redis.redis_client`` is a lazy singleton whose socket
    is bound to the event loop that first used it. pytest-asyncio runs every
    test on a fresh loop, so a client created in one test must be closed before
    the next one starts, or awaits hit "Future attached to a different loop".
    """
    yield
    from api_trafix.config.redis import close_redis

    await close_redis()

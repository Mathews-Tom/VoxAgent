from __future__ import annotations

from pathlib import Path

import asyncpg


MIGRATIONS_DIR = Path(__file__).parent.parent / "migrations"


async def init_pool(database_url: str) -> asyncpg.Pool:
    pool = await asyncpg.create_pool(database_url)
    if pool is None:
        raise RuntimeError("asyncpg.create_pool returned None")
    return pool


async def close_pool(pool: asyncpg.Pool) -> None:
    await pool.close()


async def run_migrations(pool: asyncpg.Pool) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS _migrations (
                filename TEXT PRIMARY KEY,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )

        applied: set[str] = {
            row["filename"]
            for row in await conn.fetch("SELECT filename FROM _migrations")
        }

        sql_files = sorted(MIGRATIONS_DIR.glob("*.sql"))

        for sql_file in sql_files:
            if sql_file.name in applied:
                continue

            sql = sql_file.read_text(encoding="utf-8")

            async with conn.transaction():
                await conn.execute(sql)
                await conn.execute(
                    "INSERT INTO _migrations (filename) VALUES ($1)",
                    sql_file.name,
                )

"""Postgres connection pool, schema init, and seed data for the local order-to-cash MCP server."""

import os

from dotenv import load_dotenv
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

load_dotenv()

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL environment variable is not set")

pool = AsyncConnectionPool(
    conninfo=DATABASE_URL,
    open=False,
    min_size=1,
    max_size=5,
    kwargs={"row_factory": dict_row},
)

SCHEMA_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS clients (
        client_name TEXT PRIMARY KEY,
        credit_limit NUMERIC NOT NULL,
        credit_used NUMERIC NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS inventory (
        product_name TEXT PRIMARY KEY,
        available_stock INTEGER NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS orders (
        order_id SERIAL PRIMARY KEY,
        client_name TEXT NOT NULL,
        product TEXT NOT NULL,
        quantity INTEGER NOT NULL,
        order_value NUMERIC NOT NULL,
        status TEXT NOT NULL,
        reason TEXT,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
]

SEED_CLIENTS = [
    ("Acme Traders", 100000, 20000),
    ("Blue Horizon Pvt Ltd", 150000, 140000),
    ("Zenith Corp", 200000, 10000),
]

SEED_INVENTORY = [
    ("Wireless Mouse", 200),
    ("Laptop Stand", 50),
    ("USB-C Hub", 30),
]


async def init_pool() -> None:
    """Open the pool, create tables if missing, and seed them if empty."""
    await pool.open(wait=True)
    async with pool.connection() as conn:
        async with conn.cursor() as cur, conn.transaction():
            for statement in SCHEMA_STATEMENTS:
                await cur.execute(statement)

            await cur.execute("SELECT COUNT(*) AS count FROM clients")
            row = await cur.fetchone()
            if row["count"] == 0:
                await cur.executemany(
                    "INSERT INTO clients (client_name, credit_limit, credit_used) VALUES (%s, %s, %s)",
                    SEED_CLIENTS,
                )

            await cur.execute("SELECT COUNT(*) AS count FROM inventory")
            row = await cur.fetchone()
            if row["count"] == 0:
                await cur.executemany(
                    "INSERT INTO inventory (product_name, available_stock) VALUES (%s, %s)",
                    SEED_INVENTORY,
                )


async def close_pool() -> None:
    await pool.close()

"""Local MCP server (stdio transport) exposing the same 4 order-to-cash tools
as mcp-server/, for adding directly to Claude Desktop against your local
Postgres instance. No HTTP, no API key: Claude Desktop launches this as a
trusted local subprocess, so there's no network boundary to authenticate.
"""

import asyncio
import sys
from contextlib import asynccontextmanager

from mcp.server.fastmcp import FastMCP

from db import close_pool, init_pool, pool

VALID_STATUSES = {
    "approved",
    "pending_credit_review",
    "pending_inventory",
    "pending_credit_and_inventory",
}


@asynccontextmanager
async def lifespan(server: FastMCP):
    await init_pool()
    try:
        yield {}
    finally:
        await close_pool()


mcp = FastMCP("order-to-cash-local", lifespan=lifespan)


@mcp.tool()
async def check_credit(client_name: str, order_value: float) -> dict:
    """Check whether a client has enough remaining credit for a proposed order value."""
    if not client_name or not isinstance(client_name, str):
        return {"ok": False, "error": "invalid_client_name"}
    if order_value is None or order_value < 0:
        return {"ok": False, "error": "invalid_order_value"}

    async with pool.connection() as conn:
        cur = await conn.execute(
            "SELECT client_name, credit_limit, credit_used FROM clients WHERE client_name = %s",
            (client_name,),
        )
        row = await cur.fetchone()

    if row is None:
        return {"ok": False, "error": "client_not_found"}

    credit_limit = float(row["credit_limit"])
    credit_used = float(row["credit_used"])
    would_exceed = (credit_used + float(order_value)) > credit_limit

    return {
        "ok": True,
        "client_name": row["client_name"],
        "credit_limit": credit_limit,
        "credit_used": credit_used,
        "would_exceed": would_exceed,
    }


@mcp.tool()
async def check_inventory(product_name: str, quantity: int) -> dict:
    """Check whether enough stock is available for a proposed order quantity."""
    if not product_name or not isinstance(product_name, str):
        return {"ok": False, "error": "invalid_product_name"}
    if not isinstance(quantity, int) or quantity <= 0:
        return {"ok": False, "error": "invalid_quantity"}

    async with pool.connection() as conn:
        cur = await conn.execute(
            "SELECT product_name, available_stock FROM inventory WHERE product_name = %s",
            (product_name,),
        )
        row = await cur.fetchone()

    if row is None:
        return {"ok": False, "error": "product_not_found"}

    available_stock = row["available_stock"]
    sufficient = available_stock >= quantity

    return {
        "ok": True,
        "product_name": row["product_name"],
        "available_stock": available_stock,
        "sufficient": sufficient,
    }


@mcp.tool()
async def create_order(
    client_name: str,
    product: str,
    quantity: int,
    order_value: float,
    status: str,
    reason: str = "",
) -> dict:
    """Create an order row, applying inventory/credit deltas atomically when approved."""
    if status not in VALID_STATUSES:
        return {"ok": False, "error": "invalid_status"}
    if not client_name or not isinstance(client_name, str):
        return {"ok": False, "error": "invalid_client_name"}
    if not product or not isinstance(product, str):
        return {"ok": False, "error": "invalid_product"}
    if not isinstance(quantity, int) or quantity <= 0:
        return {"ok": False, "error": "invalid_quantity"}
    if order_value is None or order_value < 0:
        return {"ok": False, "error": "invalid_order_value"}

    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT 1 FROM clients WHERE client_name = %s", (client_name,))
            if await cur.fetchone() is None:
                return {"ok": False, "error": "client_not_found"}

            await cur.execute("SELECT 1 FROM inventory WHERE product_name = %s", (product,))
            if await cur.fetchone() is None:
                return {"ok": False, "error": "product_not_found"}

            async with conn.transaction():
                await cur.execute(
                    """
                    INSERT INTO orders (client_name, product, quantity, order_value, status, reason)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    RETURNING order_id
                    """,
                    (client_name, product, quantity, order_value, status, reason),
                )
                row = await cur.fetchone()
                order_id = row["order_id"]

                if status == "approved":
                    await cur.execute(
                        "UPDATE inventory SET available_stock = available_stock - %s WHERE product_name = %s",
                        (quantity, product),
                    )
                    await cur.execute(
                        "UPDATE clients SET credit_used = credit_used + %s WHERE client_name = %s",
                        (order_value, client_name),
                    )

    return {"ok": True, "order_id": order_id, "status": status}


@mcp.tool()
async def list_recent_orders(limit: int = 10) -> dict:
    """List the most recent orders, newest first (capped at 50)."""
    if not isinstance(limit, int) or limit <= 0:
        limit = 10
    limit = min(limit, 50)

    async with pool.connection() as conn:
        cur = await conn.execute(
            """
            SELECT order_id, client_name, product, status, created_at
            FROM orders
            ORDER BY created_at DESC
            LIMIT %s
            """,
            (limit,),
        )
        rows = await cur.fetchall()

    orders = [
        {
            "order_id": r["order_id"],
            "client_name": r["client_name"],
            "product": r["product"],
            "status": r["status"],
            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
        }
        for r in rows
    ]
    return {"ok": True, "orders": orders}


if __name__ == "__main__":
    # psycopg's async mode requires a selector event loop; Windows defaults to
    # the incompatible ProactorEventLoop.
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    mcp.run(transport="stdio")

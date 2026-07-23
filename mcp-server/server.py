"""MCP server exposing 4 narrow, validated order-to-cash tools over streamable HTTP.

This replaces raw folder/CSV access for Claude Cowork: instead of reading and
writing data/*.csv directly, Cowork calls check_credit / check_inventory /
create_order / list_recent_orders, each of which validates its inputs and
touches only the rows it needs.
"""

import asyncio
import os
import sys

import uvicorn
from mcp.server.fastmcp import FastMCP
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from db import close_pool, init_pool, pool

MCP_API_KEY = os.environ.get("MCP_API_KEY")
if not MCP_API_KEY:
    raise RuntimeError("MCP_API_KEY environment variable is not set")

VALID_STATUSES = {
    "approved",
    "pending_credit_review",
    "pending_inventory",
    "pending_credit_and_inventory",
}

# FastMCP's streamable_http_app() hardcodes its own Starlette lifespan (it just
# runs the MCP session manager) and does not invoke a `lifespan=` passed into
# the FastMCP constructor for this transport, so the DB pool is opened/closed
# explicitly around uvicorn's serve loop below instead of via ASGI lifespan.
#
# host="0.0.0.0" also matters beyond just matching the real bind address:
# FastMCP auto-enables a localhost-only DNS-rebinding Host-header check when
# host defaults to "127.0.0.1", which would reject every request once this is
# actually reachable at a real hostname (e.g. Render). X-API-Key is our real
# access control here, so this is left disabled rather than allowlisting the
# specific public hostname.
mcp = FastMCP("order-to-cash-mcp", host="0.0.0.0")


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


class APIKeyMiddleware(BaseHTTPMiddleware):
    """Rejects any request that doesn't present the correct X-API-Key header.

    Runs in front of every MCP protocol request (initialize, list_tools,
    call_tool, ...), so it covers every tool call. /health is exempt so
    Render's health checker doesn't need the key.
    """

    async def dispatch(self, request: Request, call_next):
        if request.url.path == "/health":
            return await call_next(request)
        if request.headers.get("x-api-key") != MCP_API_KEY:
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        return await call_next(request)


async def health(request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok"})


app = mcp.streamable_http_app()
app.add_middleware(APIKeyMiddleware)
app.add_route("/health", health, methods=["GET"])


async def run() -> None:
    await init_pool()
    try:
        port = int(os.environ.get("PORT", 8000))
        config = uvicorn.Config(app, host="0.0.0.0", port=port, log_level="info")
        await uvicorn.Server(config).serve()
    finally:
        await close_pool()


if __name__ == "__main__":
    # psycopg's async mode requires a selector event loop; Windows defaults to
    # the incompatible ProactorEventLoop (Linux/Render is unaffected by this).
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(run())

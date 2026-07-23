"""Local stdio-to-HTTP bridge for the order-to-cash remote MCP server.

Claude Desktop only launches local (stdio) MCP servers via claude_desktop_config.json
in this environment -- it doesn't recognize a url/headers remote-server entry there.
This bridge is a normal local stdio server that Claude Desktop CAN launch; each tool
call it receives is forwarded over the network to the real remote server
(mcp-server/, deployed on Render) and the result is passed straight back.

No business logic lives here -- the actual credit/inventory/order logic and the
database are entirely on the remote server. This is purely a protocol adapter.
"""

import json
import os
import sys

from dotenv import load_dotenv
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from mcp.server.fastmcp import FastMCP

load_dotenv()

REMOTE_URL = os.environ.get("REMOTE_URL")
if not REMOTE_URL:
    raise RuntimeError("REMOTE_URL environment variable is not set")

REMOTE_API_KEY = os.environ.get("REMOTE_API_KEY")
if not REMOTE_API_KEY:
    raise RuntimeError("REMOTE_API_KEY environment variable is not set")

mcp = FastMCP("order-to-cash-bridge")


async def _call_remote_tool(tool_name: str, arguments: dict) -> dict:
    """Open a fresh connection to the remote server, call one tool, return its result."""
    async with streamablehttp_client(REMOTE_URL, headers={"X-API-Key": REMOTE_API_KEY}) as (
        read,
        write,
        _get_session_id,
    ):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(tool_name, arguments)

    if result.isError:
        text = result.content[0].text if result.content else "unknown error"
        return {"ok": False, "error": f"remote_error: {text}"}

    return json.loads(result.content[0].text)


@mcp.tool()
async def check_credit(client_name: str, order_value: float) -> dict:
    """Check whether a client has enough remaining credit for a proposed order value."""
    return await _call_remote_tool("check_credit", {"client_name": client_name, "order_value": order_value})


@mcp.tool()
async def check_inventory(product_name: str, quantity: int) -> dict:
    """Check whether enough stock is available for a proposed order quantity."""
    return await _call_remote_tool("check_inventory", {"product_name": product_name, "quantity": quantity})


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
    return await _call_remote_tool(
        "create_order",
        {
            "client_name": client_name,
            "product": product,
            "quantity": quantity,
            "order_value": order_value,
            "status": status,
            "reason": reason,
        },
    )


@mcp.tool()
async def list_recent_orders(limit: int = 10) -> dict:
    """List the most recent orders, newest first (capped at 50)."""
    return await _call_remote_tool("list_recent_orders", {"limit": limit})


if __name__ == "__main__":
    mcp.run(transport="stdio")

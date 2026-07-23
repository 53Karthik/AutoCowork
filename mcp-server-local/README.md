# Order-to-Cash Local MCP Server

A **local** Model Context Protocol server exposing the same 4 order-to-cash
tools as [`../mcp-server/`](../mcp-server/) — but over stdio, launched directly
by Claude Desktop as a subprocess against your local Postgres instance,
instead of over a remote HTTPS connector.

Use this for local testing/dev without deploying anything to Render. There's
no API key and no HTTP server here: Claude Desktop starts and stops the
process itself, so there's no network boundary to authenticate.

## The 4 tools

Identical contract to the remote server — see [`../mcp-server/README.md`](../mcp-server/README.md#the-4-tools)
for the full table. In short: `check_credit`, `check_inventory`, `create_order`,
`list_recent_orders`. Same validation, same atomic inventory/credit update on
`create_order` when `status == "approved"`.

## Setup

1. You need a local Postgres instance running (already true if you followed
   the main project setup). Create a database for this server:
   ```
   createdb -U postgres order_to_cash
   ```
2. Copy `.env.example` to `.env` and fill in your real local connection string:
   ```
   DATABASE_URL=postgresql://postgres:<your_password>@127.0.0.1:5432/order_to_cash
   ```
3. Create a venv and install dependencies:
   ```bash
   python -m venv venv
   ./venv/Scripts/python.exe -m pip install -r requirements.txt
   ```
4. Sanity-check it runs standalone (it will block waiting for stdio input —
   Ctrl+C to stop):
   ```bash
   ./venv/Scripts/python.exe server.py
   ```
   On first run it creates the `clients`/`inventory`/`orders` tables and seeds
   `clients`/`inventory` with the demo data if they're empty.

## Adding to Claude Desktop

Open Claude Desktop → **Settings → Developer → Edit Config** (this opens
`claude_desktop_config.json`). Add an `mcpServers` entry — merge it alongside
whatever's already in the file, don't replace the whole file:

```json
{
  "mcpServers": {
    "order-to-cash-local": {
      "command": "C:\\path\\to\\order-to-cash-demo\\mcp-server-local\\venv\\Scripts\\python.exe",
      "args": [
        "C:\\path\\to\\order-to-cash-demo\\mcp-server-local\\server.py"
      ],
      "env": {
        "DATABASE_URL": "postgresql://postgres:<your_password>@127.0.0.1:5432/order_to_cash"
      }
    }
  }
}
```

Use absolute paths for both `command` and `args` — Claude Desktop launches
this as a subprocess outside your shell, so a bare `python` won't reliably
resolve to this project's venv. Passing `DATABASE_URL` explicitly via `env`
(rather than relying on `.env` file discovery) avoids depending on whatever
working directory Claude Desktop happens to launch the subprocess from.

Restart Claude Desktop after editing the config for it to pick up the new
server.

## Verified locally

This exact server was smoke-tested end-to-end with a real MCP stdio client
against a live local Postgres 17 database before being called done: server
startup (schema creation + seeding), `check_credit`, `check_inventory`, an
`approved` `create_order` (confirmed both the inventory deduction and the
credit-used increase landed atomically), an invalid-status `create_order`
(confirmed it wrote nothing), and `list_recent_orders`.

# Order-to-Cash MCP Server

A Model Context Protocol (MCP) server that gives Claude Cowork **scoped, validated
access** to the order-to-cash data — instead of raw read/write access to the CSV
files in [`../data/`](../data/), Cowork calls one of 4 narrow business-logic tools
over a remote, persistent Postgres-backed API.

This is a separate component from [`../backend/`](../backend/) and
[`../frontend/`](../frontend/) (the read-only dashboard viewer). Those are
untouched by this folder — this is a new piece aimed specifically at replacing
Cowork's local folder access with a hosted MCP connector.

## The 4 tools

| Tool | Purpose | Returns |
|---|---|---|
| `check_credit(client_name, order_value)` | Check a client's remaining credit against a proposed order | `{"ok": true, "client_name", "credit_limit", "credit_used", "would_exceed"}` or `{"ok": false, "error": "client_not_found"}` |
| `check_inventory(product_name, quantity)` | Check stock availability for a proposed quantity | `{"ok": true, "product_name", "available_stock", "sufficient"}` or `{"ok": false, "error": "product_not_found"}` |
| `create_order(client_name, product, quantity, order_value, status, reason="")` | Insert an order row; if `status == "approved"`, atomically deducts inventory and increases credit used | `{"ok": true, "order_id", "status"}` or `{"ok": false, "error": "..."}` |
| `list_recent_orders(limit=10)` | List the most recent orders (max 50) | `{"ok": true, "orders": [{"order_id", "client_name", "product", "status", "created_at"}, ...]}` |

`status` for `create_order` must be one of: `approved`, `pending_credit_review`,
`pending_inventory`, `pending_credit_and_inventory`.

None of these tools ever return a full table dump, run arbitrary SQL, or read
files — they're intentionally narrow. All queries are parameterized (no string
interpolation into SQL). Every request must include a valid `X-API-Key` header
matching the `MCP_API_KEY` environment variable, checked before any tool runs.

## Running locally

1. You need a Postgres instance reachable from your machine — either a local
   install, or a Render Postgres instance (see below) with its external
   connection string.
2. Copy `.env.example` to `.env` and fill in real values:
   ```
   DATABASE_URL=postgresql://user:password@localhost:5432/order_to_cash
   MCP_API_KEY=some-long-random-secret
   ```
3. Install dependencies and run:
   ```bash
   pip install -r requirements.txt
   python server.py
   ```
   On startup the server creates the `clients`, `inventory`, and `orders` tables
   if they don't exist, and seeds `clients`/`inventory` with the demo data if
   those tables are empty. It listens on `http://localhost:8000` (or `$PORT` if
   set), with the MCP endpoint mounted at `/mcp` and a plain health check at
   `/health` (no API key required for `/health`).
4. Every MCP request (including `/mcp`) needs the header `X-API-Key: <your MCP_API_KEY>`.

**Windows-only note:** psycopg's async mode isn't compatible with Windows'
default `ProactorEventLoop`. `server.py` already switches to
`WindowsSelectorEventLoopPolicy` automatically when run on Windows, so this
only matters if you're debugging low-level asyncio behavior yourself. Linux
(including the Render container) is unaffected.

This whole flow — schema creation, seeding, the auth middleware rejecting bad
keys, and `create_order`'s atomic inventory/credit update — was verified live
against a local Postgres 17 instance before being called done.

## Deploying to Render

1. Push the whole `order-to-cash-demo/` repo to GitHub — `render.yaml` lives at
   the repo root (not inside `mcp-server/`) and points at `mcp-server/Dockerfile`
   with `dockerContext: .` (the whole repo), and the `Dockerfile` itself `COPY`s
   from the `mcp-server/` subfolder explicitly. `backend/`, `frontend/`, and
   `mcp-server-local/` ride along in the same repo without affecting this build.
2. In the Render dashboard: **New → Blueprint**, point it at the repo, and let
   it read `render.yaml`. This provisions two resources in one step:
   - a Docker-based web service (`order-to-cash-mcp`) built from the `Dockerfile`
   - a Render-managed Postgres database (`order-to-cash-mcp-db`), with its
     connection string wired into the web service's `DATABASE_URL` automatically
     via Render's `fromDatabase` linking — no manual copy-pasting of credentials.
3. `MCP_API_KEY` is deliberately **not** set in `render.yaml` (`sync: false`) —
   set it yourself in the Render dashboard under the web service's
   **Environment** tab after the blueprint deploys, so the secret never lives in
   the repo.
4. Once deployed, your server is reachable at:
   ```
   https://<service-name>.onrender.com
   ```
   with the MCP endpoint at `https://<service-name>.onrender.com/mcp`. Add that
   URL as a custom connector in **Claude Desktop → Settings → Connectors**
   (or the equivalent Cowork connector settings), supplying the `X-API-Key`
   header value you set in step 3.

## Demo-only limitations (flagging clearly, not production-hardened)

- **Render's free Postgres tier expires after 30 days** unless upgraded to a
  paid plan — after that, the database (and this demo's data) is deleted. Fine
  for a demo; not a place to keep anything you care about long-term.
- **The free web service tier spins down after inactivity**, so the first
  request after a period of idleness will take roughly 30–60 seconds while
  Render cold-starts the container. Postgres itself keeps running independently
  of this — only the MCP server process spins down, not the data.

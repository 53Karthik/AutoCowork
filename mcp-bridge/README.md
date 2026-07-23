# Order-to-Cash MCP Bridge

A local stdio↔HTTP bridge for the remote order-to-cash MCP server.

## Why this exists

Claude Desktop (this build, at least) only recognizes local `command`/`args`
(stdio) entries in `claude_desktop_config.json` — a `url`/`headers` entry for
a remote HTTP MCP server gets silently rejected as "not a valid MCP server
configuration". This bridge is a normal local stdio server (which the app
*does* support), and every tool call it receives is immediately forwarded
over the network to the real remote server at
[`../mcp-server/`](../mcp-server/) (deployed on Render), with the result
passed straight back.

**There is no business logic here.** No database, no validation, no state.
It's a pure protocol adapter — 4 tool functions that each open a connection
to the remote server, call the same-named tool there, and return whatever it
returns. If the remote server's logic ever changes, this bridge doesn't need
to change at all.

## Setup

1. Copy `.env.example` to `.env` and fill in the real values:
   ```
   REMOTE_URL=https://order-to-cash-mcp.onrender.com/mcp
   REMOTE_API_KEY=<the real MCP_API_KEY value>
   ```
2. Create a venv and install dependencies:
   ```bash
   python -m venv venv
   ./venv/Scripts/python.exe -m pip install -r requirements.txt
   ```

## Adding to Claude Desktop

Same `mcpServers` object as the other two servers — this replaces the
`order-to-cash-remote` entry that used `url`/`headers` directly (which this
app rejects) with one using `command`/`args` like the local server:

```json
{
  "mcpServers": {
    "order-to-cash-remote": {
      "command": "C:\\path\\to\\order-to-cash-demo\\mcp-bridge\\venv\\Scripts\\python.exe",
      "args": [
        "C:\\path\\to\\order-to-cash-demo\\mcp-bridge\\server.py"
      ],
      "env": {
        "REMOTE_URL": "https://order-to-cash-mcp.onrender.com/mcp",
        "REMOTE_API_KEY": "<the real MCP_API_KEY value>"
      }
    }
  }
}
```

Restart Claude Desktop after editing for it to pick up the change.

## Verified

Tested end-to-end with a real MCP stdio client, spawning this exact bridge
and confirming every call actually round-trips to the live Render deployment:
`check_credit`, `check_inventory` (both real data), an unknown-client error
round-tripping correctly, an invalid-status `create_order` call proving the
write path routes through without committing anything, and
`list_recent_orders` confirming no stray test data was left behind on the
real remote database.

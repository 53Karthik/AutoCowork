# Order-to-Cash Demo Viewer

This is a **live viewer** for a Claude Cowork automation demo of an Order-to-Cash workflow.

## What this app does (and doesn't do)

- Claude Cowork independently reads Slack messages, runs the credit-limit and inventory
  checks, and writes the results as rows in the CSV files under [`data/`](data/).
- This app **does not** perform any of that logic. It is a read-only dashboard that
  displays whatever is currently in `data/clients.csv`, `data/inventory.csv`, and
  `data/orders.csv`.
- Both Cowork and this app read/write the same CSV files — the CSVs are the single
  source of truth. There is no database and no message passing between them.

## Project structure

```
order-to-cash-demo/
├── data/
│   ├── clients.csv       (client_name, credit_limit, credit_used)
│   ├── inventory.csv     (product_name, available_stock)
│   └── orders.csv        (order_id, client_name, product, quantity, order_value, status, reason, created_at)
├── backend/              FastAPI app that reads the CSVs fresh on every request
├── frontend/             Plain HTML/JS dashboard (no build step required)
└── README.md
```

## Running the backend

```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

Endpoints (all read-only, CORS enabled for local use):

- `GET /clients`
- `GET /inventory`
- `GET /orders` (sorted by `created_at` descending)

Each endpoint reads its CSV file fresh on every request — nothing is cached — so
updates made by Cowork show up immediately on the next fetch/refresh.

## Running the frontend

No build tooling needed — it's a single static HTML file.

```bash
cd frontend
python -m http.server 5500
```

Then open http://localhost:5500 in your browser. Alternatively just double-click
`frontend/index.html` to open it directly (the backend must still be running at
`http://localhost:8000` for it to fetch data — see the `API_BASE` constant near the
top of the `<script>` block in `index.html` if you need to change the backend URL).

The dashboard has:

1. **Orders table** — order id, client, product, qty, value, color-coded status badge
   (green = approved, yellow = pending_credit_review / pending_inventory /
   pending_credit_and_inventory), reason, created_at.
2. **Clients table** — name, credit limit, credit used, and a progress bar showing
   % of credit used.
3. **Inventory table** — product name and available stock (highlighted red when
   stock is below 40).

A manual **Refresh** button re-fetches all three endpoints, and the page also
auto-refreshes every 10 seconds.

## Important: shared data folder

For the live demo to work, **both this app's backend and the Cowork task must point
at the same `data/` folder**. If Cowork is configured to write CSVs to a different
path, either point Cowork at this `data/` directory or update `DATA_DIR` in
`backend/main.py` to match wherever Cowork is writing.

import csv
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

app = FastAPI(title="Order-to-Cash Demo Viewer")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def read_csv(filename: str) -> list[dict]:
    path = DATA_DIR / filename
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


@app.get("/clients")
def get_clients():
    return read_csv("clients.csv")


@app.get("/inventory")
def get_inventory():
    return read_csv("inventory.csv")


@app.get("/orders")
def get_orders():
    orders = read_csv("orders.csv")
    orders.sort(key=lambda o: o.get("created_at", ""), reverse=True)
    return orders

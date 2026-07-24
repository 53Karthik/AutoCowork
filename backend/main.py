import os

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

load_dotenv()

REMOTE_URL = os.environ.get("REMOTE_URL")
if not REMOTE_URL:
    raise RuntimeError("REMOTE_URL environment variable is not set")

REMOTE_API_KEY = os.environ.get("REMOTE_API_KEY")
if not REMOTE_API_KEY:
    raise RuntimeError("REMOTE_API_KEY environment variable is not set")

app = FastAPI(title="Order-to-Cash Demo Viewer")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


async def fetch_remote(path: str):
    async with httpx.AsyncClient(timeout=30) as client:
        res = await client.get(f"{REMOTE_URL}{path}", headers={"X-API-Key": REMOTE_API_KEY})
    if not res.is_success:
        raise HTTPException(status_code=502, detail=f"Remote server returned {res.status_code} for {path}")
    return res.json()


@app.get("/clients")
async def get_clients():
    return await fetch_remote("/clients")


@app.get("/inventory")
async def get_inventory():
    return await fetch_remote("/inventory")


@app.get("/orders")
async def get_orders():
    return await fetch_remote("/orders")

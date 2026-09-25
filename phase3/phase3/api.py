"""Authenticated HTTP API for the OTC Intelligence admin dashboard."""
from __future__ import annotations

import hmac
import os
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from config.settings import get_settings
from ..data.storage import DataStorage
from .market_scanner import scanner
from src.signals.engine import SignalEngine

settings = get_settings(require_token=False)

app = FastAPI(title="OTC Intelligence Admin API", version="1.0.0")

origins = [
    item.strip()
    for item in os.getenv("DASHBOARD_CORS_ORIGINS", "http://localhost:3000").split(",")
    if item.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "X-Dashboard-Key"],
)

storage = DataStorage()

signal_engine = SignalEngine(settings)


def require_dashboard_key(x_dashboard_key: Optional[str] = Header(default=None)) -> None:
    expected = os.getenv("DASHBOARD_ADMIN_KEY")
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="DASHBOARD_ADMIN_KEY is not configured on the server",
        )
    if not x_dashboard_key or not hmac.compare_digest(x_dashboard_key, expected):
        raise HTTPException(status_code=401, detail="Invalid dashboard credentials")


class UserCreate(BaseModel):
    telegram_id: int = Field(gt=0)
    username: Optional[str] = Field(default=None, max_length=100)
    first_name: Optional[str] = Field(default=None, max_length=100)
    last_name: Optional[str] = Field(default=None, max_length=100)


class UserUpdate(BaseModel):
    username: Optional[str] = Field(default=None, max_length=100)
    first_name: Optional[str] = Field(default=None, max_length=100)
    last_name: Optional[str] = Field(default=None, max_length=100)


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "otc-intelligence-admin-api"}


@app.get("/api/admin/users", dependencies=[Depends(require_dashboard_key)])
def list_users(limit: int = Query(default=100, ge=1, le=500)) -> dict:
    users = storage.list_all_users(limit=limit)
    return {"users": users, "count": len(users)}


@app.post("/api/admin/users", status_code=201, dependencies=[Depends(require_dashboard_key)])
def create_user(payload: UserCreate) -> dict:
    try:
        user = storage.create_user(
            telegram_id=payload.telegram_id,
            username=payload.username,
            first_name=payload.first_name,
            last_name=payload.last_name,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"user": user}


@app.get("/api/admin/users/{telegram_id}", dependencies=[Depends(require_dashboard_key)])
def get_user(telegram_id: str) -> dict:
    user = storage.get_user(telegram_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return {"user": user}


@app.patch("/api/admin/users/{telegram_id}", dependencies=[Depends(require_dashboard_key)])
def update_user(telegram_id: str, payload: UserUpdate) -> dict:
    user = storage.update_user(
        telegram_id,
        username=payload.username,
        first_name=payload.first_name,
        last_name=payload.last_name,
    )
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return {"user": user}


@app.delete("/api/admin/users/{telegram_id}", dependencies=[Depends(require_dashboard_key)])
def delete_user(telegram_id: str) -> dict:
    deleted = storage.delete_user(telegram_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="User not found")
    return {"deleted": True, "telegram_id": telegram_id}

@app.get("/api/market/status", dependencies=[Depends(require_dashboard_key)])
async def market_status() -> dict:
    connected = bool(scanner.client is not None and getattr(scanner.client, "is_connected", False))
    from datetime import datetime, timezone
    return {
        "status": "LIVE" if connected else "DATA_UNAVAILABLE",
        "connected": connected,
        "assets_tracked": len(scanner.assets()),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }

@app.get("/api/market/assets", dependencies=[Depends(require_dashboard_key)])
async def market_assets() -> dict:
    assets = scanner.assets()
    return {"assets": assets, "count": len(assets)}

@app.get("/api/market/scanner", dependencies=[Depends(require_dashboard_key)])
async def market_scanner(timeframe: str = Query(default="1m")) -> dict:
    try:
        return await scanner.scan(timeframe)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

@app.get("/api/market/assets/{asset}", dependencies=[Depends(require_dashboard_key)])
async def market_asset(asset: str, timeframe: str = Query(default="1m")) -> dict:
    try:
        return await scanner.detail(asset, timeframe)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
@app.post("/api/market/signal", dependencies=[Depends(require_dashboard_key)])
async def market_signal(asset: str = Query(..., min_length=1), timeframe: str = Query(default="1m")) -> dict:
    """Generate a read-only signal for the explicitly selected asset/timeframe.

    This endpoint never places a trade. It reuses the live scanner broker connection
    and the production SignalEngine so dashboard analysis stays consistent with the bot.
    """
    timeframe = timeframe.lower().strip()
    try:
        await scanner.ensure_connected()
        if scanner.fetcher is None:
            raise RuntimeError("market data fetcher is unavailable")
        if asset not in scanner.assets():
            raise ValueError(f"Unknown OTC asset: {asset}")
        if timeframe not in {"1m", "2m", "5m", "15m", "30m", "1h"}:
            raise ValueError(f"Unsupported timeframe: {timeframe}")

        candles = await scanner.fetcher.get_historical_data(
            asset, timeframe=timeframe, count=200
        )
        signal_engine.data_fetcher = scanner.fetcher
        result = await signal_engine.generate_signal(
            asset=asset, timeframe=timeframe, candles=candles
        )
        return {
            "status": "SIGNAL_READY" if result.get("action") in {"CALL", "PUT"} else "WAIT",
            "asset": asset,
            "timeframe": timeframe,
            "signal": result,
            "generated_at": result.get("timestamp"),
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Signal engine unavailable: {exc}") from exc


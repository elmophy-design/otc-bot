"""Authenticated HTTP API for the OTC Intelligence admin dashboard."""
from __future__ import annotations

import asyncio
import hmac
import os
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from config.settings import get_settings
from src.data.storage import DataStorage
from .market_scanner import scanner
from src.signals.engine import SignalEngine
from src.services.risk_manager import RiskManager

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


class TradePreviewRequest(BaseModel):
    asset: str = Field(min_length=1, max_length=100)
    timeframe: str = Field(default="1m", min_length=2, max_length=5)
    amount: float = Field(gt=0)
    duration: int = Field(default=60, ge=30, le=3600)


class TradeExecuteRequest(TradePreviewRequest):
    confirm: bool = False


_EXECUTION_LOCK = asyncio.Lock()
_LAST_EXECUTIONS: dict[str, float] = {}
_EXECUTION_DEDUP_SECONDS = 10.0


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


def _dashboard_operator_id() -> int:
    raw = os.getenv("DASHBOARD_OPERATOR_ID", "").strip()
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = 0
    if value <= 0:
        raise HTTPException(status_code=503, detail="DASHBOARD_OPERATOR_ID is not configured on the server")
    return value


async def _fresh_trade_signal(asset: str, timeframe: str) -> dict:
    timeframe = timeframe.lower().strip()
    if timeframe not in {"1m", "2m", "5m", "15m", "30m", "1h"}:
        raise HTTPException(status_code=400, detail=f"Unsupported timeframe: {timeframe}")
    if asset not in scanner.assets():
        raise HTTPException(status_code=400, detail=f"Unknown OTC asset: {asset}")
    await scanner.ensure_connected()
    if scanner.fetcher is None or scanner.client is None:
        raise HTTPException(status_code=503, detail="Broker market connection unavailable")
    candles = await scanner.fetcher.get_historical_data(asset, timeframe=timeframe, count=200)
    signal_engine.data_fetcher = scanner.fetcher
    result = await signal_engine.generate_signal(asset=asset, timeframe=timeframe, candles=candles)
    return {"asset": asset, "timeframe": timeframe, "signal": result}


async def _trade_validation(payload: TradePreviewRequest) -> dict:
    settings = get_settings(require_token=False)
    amount = float(payload.amount)
    duration = int(payload.duration)
    minimum = float(getattr(settings, "MIN_TRADE_AMOUNT", 0.0))
    maximum = float(getattr(settings, "MAX_TRADE_AMOUNT", 0.0))
    if amount < minimum:
        raise HTTPException(status_code=400, detail=f"Trade amount must be at least {minimum:.2f}")
    if maximum > 0 and amount > maximum:
        raise HTTPException(status_code=400, detail=f"Trade amount cannot exceed {maximum:.2f}")
    if duration not in {30, 60, 120, 300, 600}:
        raise HTTPException(status_code=400, detail="Unsupported duration. Use 30, 60, 120, 300 or 600 seconds.")

    fresh = await _fresh_trade_signal(payload.asset, payload.timeframe)
    signal = fresh["signal"]
    action = str(signal.get("action") or "NO_SIGNAL").upper()
    confidence = float(signal.get("confidence") or 0.0)
    balance = None
    get_balance = getattr(scanner.client, "get_balance", None)
    if callable(get_balance):
        try:
            balance = await get_balance()
        except Exception:
            balance = None
    if balance is not None:
        balance = float(balance)

    reasons = []
    if action not in {"CALL", "PUT"}: reasons.append("Signal is not executable.")
    if confidence < float(getattr(settings, "MIN_CONFIDENCE", 70)): reasons.append("Signal confidence is below the configured minimum.")
    if balance is None: reasons.append("Broker balance is unavailable.")
    elif amount > balance: reasons.append("Trade amount exceeds available balance.")
    if balance is not None:
        risk = RiskManager(account_balance=balance, max_risk_per_trade=0.02)
        if risk.should_block(amount, confidence): reasons.append("Risk manager rejected the requested amount/confidence.")

    return {"allowed": not reasons, "reasons": reasons, "asset": fresh["asset"], "timeframe": fresh["timeframe"], "signal": signal, "amount": amount, "duration": duration, "balance": balance, "min_amount": minimum, "max_amount": maximum, "demo_mode": bool(getattr(settings, "DEMO_MODE", True))}


@app.post("/api/market/trade/preview", dependencies=[Depends(require_dashboard_key)])
async def market_trade_preview(payload: TradePreviewRequest) -> dict:
    try:
        return await _trade_validation(payload)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Trade preview unavailable: {exc}") from exc


@app.post("/api/market/trade/execute", dependencies=[Depends(require_dashboard_key)])
async def market_trade_execute(payload: TradeExecuteRequest) -> dict:
    if not payload.confirm:
        raise HTTPException(status_code=400, detail="Explicit trade confirmation is required")
    operator_id = _dashboard_operator_id()
    async with _EXECUTION_LOCK:
        preview = await _trade_validation(payload)
        if not preview["allowed"]:
            raise HTTPException(status_code=409, detail="Trade blocked: " + " ".join(preview["reasons"]))
        signal = preview["signal"]
        direction = str(signal.get("action") or "").upper()
        amount = float(preview["amount"])
        duration = int(preview["duration"])
        asset = preview["asset"]
        import time as _time
        dedup_key = f"{asset}|{direction}|{amount:.8f}|{duration}"
        now_mono = _time.monotonic()
        previous = _LAST_EXECUTIONS.get(dedup_key)
        if previous is not None and (now_mono - previous) < _EXECUTION_DEDUP_SECONDS:
            raise HTTPException(status_code=409, detail="Duplicate execution blocked. Wait a few seconds before submitting the same trade again.")
        place_trade = getattr(scanner.client, "place_trade", None)
        if not callable(place_trade):
            raise HTTPException(status_code=503, detail="Connected broker does not support trade execution")
        try:
            result = await place_trade(asset=asset, direction=direction, amount=amount, duration=duration)
        except TypeError:
            result = await place_trade(asset, direction, amount, duration)
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Broker execution failed: {exc}") from exc
        if not isinstance(result, dict) or not result.get("success") or not result.get("trade_id"):
            error = result.get("error") if isinstance(result, dict) else "Unknown broker response"
            raise HTTPException(status_code=502, detail=f"Broker rejected trade: {error}")
        trade_id = str(result["trade_id"])
        trade_row_id = DataStorage().save_trade(user_id=operator_id, chat_id=operator_id, asset=asset, direction=direction, amount=amount, duration_secs=duration, order_id=trade_id, entry_price=signal.get("entry_price"))
        if trade_row_id is None:
            raise HTTPException(status_code=500, detail="Broker accepted the trade, but local audit recording failed. Reconciliation is required.")
        _LAST_EXECUTIONS[dedup_key] = now_mono
        return {"status": "EXECUTED", "trade_id": trade_id, "trade_history_id": trade_row_id, "operator_id": operator_id, "asset": asset, "direction": direction, "amount": amount, "duration": duration, "entry_price": signal.get("entry_price"), "signal_confidence": signal.get("confidence"), "signal_timestamp": signal.get("timestamp"), "demo_mode": preview["demo_mode"]}


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


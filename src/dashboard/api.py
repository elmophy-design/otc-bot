from __future__ import annotations

import hmac
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Query, status
from pydantic import BaseModel, Field

from src.dashboard.scanner import SharedMarketScanner
from src.data.storage import DataStorage

app = FastAPI(
    title="OTC Intelligence Dashboard API",
    version="2.0.0",
    docs_url=None,
    redoc_url=None,
)

_runtime: dict[str, Any] = {
    "settings": None,
    "api_client": None,
    "data_fetcher": None,
    "signal_engine": None,
    "storage": None,
    "scanner": None,
}


def configure_runtime(*, settings: Any, api_client: Any, data_fetcher: Any,
                      signal_engine: Any, storage: DataStorage) -> None:
    """Bind the API to the bot's already-running runtime.

    No broker client is created here. This is the key architectural rule that
    prevents Railway's dashboard API from opening a second BotV2 session.
    """
    _runtime.update({
        "settings": settings,
        "api_client": api_client,
        "data_fetcher": data_fetcher,
        "signal_engine": signal_engine,
        "storage": storage,
        "scanner": SharedMarketScanner(settings, data_fetcher),
    })


class TradePreviewRequest(BaseModel):
    asset: str = Field(min_length=1, max_length=100)
    timeframe: str = Field(default="1m", min_length=2, max_length=5)
    amount: float = Field(gt=0)
    duration: int = Field(default=60, ge=30, le=3600)


class ExecuteTradeRequest(TradePreviewRequest):
    direction: str = Field(min_length=3, max_length=4)
    confirm: bool = False


def _require_runtime() -> dict[str, Any]:
    if not _runtime["api_client"] or not _runtime["data_fetcher"] or not _runtime["signal_engine"]:
        raise HTTPException(status_code=503, detail="Trading runtime is not ready")
    return _runtime


def require_dashboard_key(x_dashboard_key: Optional[str] = Header(default=None)) -> None:
    expected = os.getenv("DASHBOARD_ADMIN_KEY", "").strip()
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="DASHBOARD_ADMIN_KEY is not configured on Railway",
        )
    if not x_dashboard_key or not hmac.compare_digest(x_dashboard_key, expected):
        raise HTTPException(status_code=401, detail="Invalid dashboard credentials")


@app.get("/health")
async def public_health() -> dict[str, str]:
    # Railway health checks must not require the dashboard secret. This endpoint
    # intentionally exposes no broker/session/account information.
    return {"status": "ok"}


@app.get("/dashboard/health", dependencies=[Depends(require_dashboard_key)])
async def dashboard_health() -> dict[str, Any]:
    rt = _require_runtime()
    client = rt["api_client"]
    return {
        "status": "ok",
        "service": "otc-intelligence-dashboard-api",
        "broker_connected": bool(getattr(client, "is_connected", False)),
        "demo_mode": bool(getattr(rt["settings"], "DEMO_MODE", True)),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/dashboard/market/status", dependencies=[Depends(require_dashboard_key)])
async def market_status() -> dict[str, Any]:
    rt = _require_runtime()
    client = rt["api_client"]
    scanner = rt["scanner"]
    return {
        "status": "LIVE" if getattr(client, "is_connected", False) else "OFFLINE",
        "connected": bool(getattr(client, "is_connected", False)),
        "assets_tracked": len(scanner.assets()),
        "demo_mode": bool(getattr(rt["settings"], "DEMO_MODE", True)),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/dashboard/market/assets", dependencies=[Depends(require_dashboard_key)])
async def market_assets() -> dict[str, Any]:
    scanner = _require_runtime()["scanner"]
    assets = scanner.assets()
    return {"assets": assets, "count": len(assets)}


@app.get("/dashboard/market/scanner", dependencies=[Depends(require_dashboard_key)])
async def market_scanner(timeframe: str = Query(default="1m")) -> dict[str, Any]:
    try:
        return await _require_runtime()["scanner"].scan(timeframe)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/dashboard/market/assets/{asset}", dependencies=[Depends(require_dashboard_key)])
async def market_asset(asset: str, timeframe: str = Query(default="1m")) -> dict[str, Any]:
    try:
        return await _require_runtime()["scanner"].detail(asset, timeframe)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


async def _fresh_signal(asset: str, timeframe: str) -> dict[str, Any]:
    rt = _require_runtime()
    scanner = rt["scanner"]
    if asset not in scanner.assets():
        raise ValueError(f"Unknown OTC asset: {asset}")
    candles = await rt["data_fetcher"].get_historical_data(
        asset, timeframe=timeframe, count=200
    )
    if candles is None or candles.empty:
        raise RuntimeError("No live market candles returned")
    return await rt["signal_engine"].generate_signal(
        asset=asset, timeframe=timeframe, candles=candles
    )


@app.post("/dashboard/market/signal", dependencies=[Depends(require_dashboard_key)])
async def market_signal(
    asset: str = Query(..., min_length=1),
    timeframe: str = Query(default="1m"),
) -> dict[str, Any]:
    try:
        signal = await _fresh_signal(asset, timeframe.lower().strip())
        return {
            "status": "SIGNAL_READY" if signal.get("action") in {"CALL", "PUT"} else "WAIT",
            "asset": asset,
            "timeframe": timeframe,
            "signal": signal,
            "generated_at": signal.get("timestamp"),
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Signal engine unavailable: {exc}") from exc


@app.post("/dashboard/trades/preview", dependencies=[Depends(require_dashboard_key)])
async def preview_trade(payload: TradePreviewRequest) -> dict[str, Any]:
    rt = _require_runtime()
    settings = rt["settings"]
    reasons: list[str] = []

    if payload.amount < float(getattr(settings, "MIN_TRADE_AMOUNT", 1.0)):
        reasons.append("Amount is below MIN_TRADE_AMOUNT.")
    if payload.amount > float(getattr(settings, "MAX_TRADE_AMOUNT", 10.0)):
        reasons.append("Amount exceeds MAX_TRADE_AMOUNT.")

    scanner = rt["scanner"]
    if payload.asset not in scanner.assets():
        reasons.append("Asset is not in the configured OTC asset list.")

    signal: dict[str, Any] | None = None
    try:
        signal = await _fresh_signal(payload.asset, payload.timeframe)
    except Exception as exc:
        reasons.append(f"Fresh signal check failed: {exc}")

    if signal and signal.get("action") not in {"CALL", "PUT"}:
        reasons.append("The fresh signal engine returned WAIT/NO_SIGNAL.")

    confidence = float(signal.get("confidence") or 0) if signal else 0.0
    min_confidence = float(getattr(settings, "MIN_CONFIDENCE", 70))
    if signal and confidence < min_confidence:
        reasons.append(f"Signal confidence {confidence:.1f}% is below {min_confidence:.1f}%.")

    client = rt["api_client"]
    balance = None
    for name in ("get_balance", "balance"):
        try:
            value = getattr(client, name, None)
            if callable(value):
                value = value()
                if hasattr(value, "__await__"):
                    value = await value
            if value is not None:
                balance = float(value)
                break
        except Exception:
            continue

    if balance is not None and payload.amount > balance:
        reasons.append("Stake exceeds the currently available broker balance.")

    return {
        "allowed": not reasons,
        "reasons": reasons,
        "asset": payload.asset,
        "timeframe": payload.timeframe,
        "amount": payload.amount,
        "duration": payload.duration,
        "balance": balance,
        "signal": signal,
        "demo_mode": bool(getattr(settings, "DEMO_MODE", True)),
    }


@app.post("/dashboard/trades/execute", dependencies=[Depends(require_dashboard_key)])
async def execute_trade(payload: ExecuteTradeRequest) -> dict[str, Any]:
    if not payload.confirm:
        raise HTTPException(status_code=400, detail="Explicit trade confirmation is required")

    rt = _require_runtime()
    settings = rt["settings"]
    direction = payload.direction.upper().strip()
    if direction not in {"CALL", "PUT"}:
        raise HTTPException(status_code=400, detail="Direction must be CALL or PUT")

    # Re-run the signal immediately before execution. The dashboard must never
    # execute a stale signal from the browser.
    try:
        signal = await _fresh_signal(payload.asset, payload.timeframe)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Fresh signal unavailable: {exc}") from exc

    if signal.get("action") != direction:
        raise HTTPException(
            status_code=409,
            detail=f"Fresh signal is {signal.get('action')}; requested {direction} was blocked",
        )

    confidence = float(signal.get("confidence") or 0)
    min_confidence = float(getattr(settings, "MIN_CONFIDENCE", 70))
    if confidence < min_confidence:
        raise HTTPException(status_code=409, detail="Fresh signal confidence is below the configured threshold")

    if payload.amount < float(getattr(settings, "MIN_TRADE_AMOUNT", 1.0)):
        raise HTTPException(status_code=400, detail="Amount is below MIN_TRADE_AMOUNT")
    if payload.amount > float(getattr(settings, "MAX_TRADE_AMOUNT", 10.0)):
        raise HTTPException(status_code=400, detail="Amount exceeds MAX_TRADE_AMOUNT")

    client = rt["api_client"]
    if not getattr(client, "is_connected", False):
        raise HTTPException(status_code=503, detail="Broker connection is not active")

    try:
        result = await client.place_trade(
            payload.asset, direction, payload.amount, payload.duration
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Broker execution failed: {exc}") from exc

    if not result.get("success"):
        raise HTTPException(status_code=503, detail=str(result.get("error") or "Trade was rejected"))

    order_id = result.get("order_id") or result.get("trade_id")
    if not order_id:
        raise HTTPException(status_code=502, detail="Broker did not return a trade ID; execution cannot be audited safely")

    # Dashboard trades are audited through the same TradeHistory table used by
    # Telegram. Configure the dashboard operator identity and optional chat ID
    # in Railway environment variables.
    dashboard_user_id = int(os.getenv("DASHBOARD_OPERATOR_ID", "0") or 0)
    dashboard_chat_id = int(os.getenv("DASHBOARD_TELEGRAM_CHAT_ID", "0") or 0)
    if dashboard_user_id <= 0:
        raise HTTPException(status_code=503, detail="DASHBOARD_OPERATOR_ID is not configured")

    entry_price = signal.get("entry_price")
    storage: DataStorage = rt["storage"]
    trade_history_id = storage.save_trade(
        user_id=dashboard_user_id,
        chat_id=dashboard_chat_id or dashboard_user_id,
        asset=payload.asset,
        direction=direction,
        amount=payload.amount,
        duration_secs=payload.duration,
        order_id=str(order_id),
        entry_price=float(entry_price) if entry_price is not None else None,
    )
    if trade_history_id is None:
        raise HTTPException(status_code=500, detail="Broker trade placed but audit record could not be created")

    return {
        "success": True,
        "trade_id": str(order_id),
        "trade_history_id": trade_history_id,
        "asset": payload.asset,
        "direction": direction,
        "amount": payload.amount,
        "duration": payload.duration,
        "entry_price": entry_price,
        "confidence": confidence,
        "demo_mode": bool(getattr(settings, "DEMO_MODE", True)),
        "placed_at": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/dashboard/analytics/report", dependencies=[Depends(require_dashboard_key)])
async def analytics_report(period: str = Query(default="daily")) -> dict[str, Any]:
    rt = _require_runtime()
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    value = period.lower().strip()
    if value == "daily":
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    elif value == "weekly":
        start = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    elif value == "monthly":
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    else:
        raise HTTPException(status_code=400, detail="period must be daily, weekly, or monthly")
    report = rt["storage"].get_trade_report(start, now)
    return {"period": value, "start": start.isoformat(), "end": now.isoformat(), "report": report}


@app.get("/dashboard/trades/recent", dependencies=[Depends(require_dashboard_key)])
async def recent_trades(limit: int = Query(default=25, ge=1, le=100)) -> dict[str, Any]:
    # Reuse the authoritative reporting path rather than introducing another
    # trade-history implementation.
    rt = _require_runtime()
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    start = now - timedelta(days=30)
    report = rt["storage"].get_trade_report(start, now)
    return {"trades": report.get("trades", [])[-limit:]}

"""Authenticated dashboard API backed by the bot's existing runtime."""
from __future__ import annotations

import asyncio
import hmac
import os
from collections import deque
from datetime import datetime, timedelta, timezone
from typing import Optional, Any
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from fastapi import Depends, FastAPI, Header, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from config.settings import get_settings
from src.services.risk_manager import RiskManager
from .market_scanner import scanner
from .runtime import get_runtime, bind_runtime
from .decision_engine import ProfessionalDecisionEngine

settings = get_settings(require_token=False)
app = FastAPI(title="OTC Intelligence Dashboard API", version="2.0.0")

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

storage_fallback = None
_EXECUTION_LOCK = asyncio.Lock()
_LAST_EXECUTIONS: dict[str, float] = {}
_EXECUTION_DEDUP_SECONDS = 10.0
_SIGNAL_HISTORY: deque[dict[str, Any]] = deque(maxlen=100)
_DECISION_ENGINE = ProfessionalDecisionEngine()


def attach_bot_runtime(*, bot) -> None:
    """Bind the already-initialized bot runtime to this API."""
    runtime = bind_runtime(
        settings=bot.settings,
        api_client=bot.api_client,
        data_fetcher=bot.data_fetcher,
        signal_engine=bot.signal_engine,
        storage=bot.application.bot_data["storage"],
        application=bot.application,
    )
    scanner.bind_runtime(runtime.api_client, runtime.data_fetcher)


def require_dashboard_key(x_dashboard_key: Optional[str] = Header(default=None)) -> None:
    expected = os.getenv("DASHBOARD_ADMIN_KEY", "").strip()
    if not expected:
        raise HTTPException(status_code=503, detail="DASHBOARD_ADMIN_KEY is not configured on the server")
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


class TradePreviewRequest(BaseModel):
    asset: str = Field(min_length=1, max_length=100)
    timeframe: str = Field(default="1m", min_length=2, max_length=5)
    amount: float = Field(gt=0)
    duration: int = Field(default=60, ge=30, le=3600)


class TradeExecuteRequest(TradePreviewRequest):
    confirm: bool = False


def _runtime():
    try:
        return get_runtime()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


def _periods() -> dict[str, tuple[datetime, datetime]]:
    rt = _runtime()
    tz = ZoneInfo(getattr(rt.settings, "DISPLAY_TIMEZONE", "Africa/Lagos"))
    now_local = datetime.now(tz)
    today_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    week_local = today_local - timedelta(days=today_local.weekday())
    month_local = today_local.replace(day=1)

    def utc_pair(start_local: datetime, end_local: datetime):
        return start_local.astimezone(timezone.utc), end_local.astimezone(timezone.utc)

    return {
        "daily": utc_pair(today_local, now_local),
        "weekly": utc_pair(week_local, now_local),
        "monthly": utc_pair(month_local, now_local),
    }


@app.get("/health")
def health() -> dict:
    connected = False
    try:
        rt = get_runtime()
        connected = bool(getattr(rt.api_client, "is_connected", False))
    except RuntimeError:
        pass
    return {
        "status": "ok" if connected else "degraded",
        "service": "otc-intelligence-dashboard-api",
        "broker_connected": connected,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/api/dashboard/overview", dependencies=[Depends(require_dashboard_key)])
def dashboard_overview() -> dict:
    rt = _runtime()
    periods = _periods()
    reports = {
        name: rt.storage.get_trade_report(start, end)
        for name, (start, end) in periods.items()
    }
    users = rt.storage.list_all_users(limit=500)
    return {
        "mode": "DEMO" if bool(getattr(rt.settings, "DEMO_MODE", True)) else "LIVE",
        "broker_connected": bool(getattr(rt.api_client, "is_connected", False)),
        "assets_tracked": len(scanner.assets()),
        "users": {"count": len(users)},
        "daily": reports["daily"],
        "weekly": reports["weekly"],
        "monthly": reports["monthly"],
        "recent_trades": reports["daily"]["trades"][-10:][::-1],
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/api/analytics", dependencies=[Depends(require_dashboard_key)])
def analytics(period: str = Query(default="daily", pattern="^(daily|weekly|monthly)$")) -> dict:
    rt = _runtime()
    periods = _periods()
    start, end = periods[period]
    return {
        "period": period,
        "report": rt.storage.get_trade_report(start, end),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/api/admin/users", dependencies=[Depends(require_dashboard_key)])
def list_users(limit: int = Query(default=100, ge=1, le=500)) -> dict:
    rt = _runtime()
    users = rt.storage.list_all_users(limit=limit)
    return {"users": users, "count": len(users)}


@app.post("/api/admin/users", status_code=201, dependencies=[Depends(require_dashboard_key)])
def create_user(payload: UserCreate) -> dict:
    rt = _runtime()
    try:
        user = rt.storage.create_user(
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
    user = _runtime().storage.get_user(telegram_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return {"user": user}


@app.patch("/api/admin/users/{telegram_id}", dependencies=[Depends(require_dashboard_key)])
def update_user(telegram_id: str, payload: UserUpdate) -> dict:
    user = _runtime().storage.update_user(
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
    deleted = _runtime().storage.delete_user(telegram_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="User not found")
    return {"deleted": True, "telegram_id": telegram_id}


@app.get("/api/market/status", dependencies=[Depends(require_dashboard_key)])
async def market_status() -> dict:
    rt = _runtime()
    connected = bool(getattr(rt.api_client, "is_connected", False))
    return {
        "status": "LIVE" if connected else "DATA_UNAVAILABLE",
        "connected": connected,
        "assets_tracked": len(scanner.assets()),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/api/market/assets", dependencies=[Depends(require_dashboard_key)])
async def market_assets() -> dict:
    return {"assets": scanner.assets(), "count": len(scanner.assets())}


@app.get("/api/market/scanner", dependencies=[Depends(require_dashboard_key)])
async def market_scanner(timeframe: str = Query(default="1m")) -> dict:
    try:
        return await scanner.scan(timeframe)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc



@app.get("/api/market/candles", dependencies=[Depends(require_dashboard_key)])
async def market_candles(
    asset: str = Query(..., min_length=1),
    timeframe: str = Query(default="1m"),
    count: int = Query(default=120, ge=30, le=300),
) -> dict:
    """Return broker-backed OHLC candles for the terminal chart.

    This endpoint is deliberately read-only and reuses the bot-owned
    market-data connection. No synthetic candles are generated here.
    """
    allowed = {"1m", "2m", "5m", "15m", "30m", "1h"}
    timeframe = timeframe.lower().strip()
    if timeframe not in allowed:
        raise HTTPException(status_code=400, detail=f"Unsupported timeframe: {timeframe}")
    if asset not in scanner.assets():
        raise HTTPException(status_code=400, detail=f"Unknown OTC asset: {asset}")
    rt = _runtime()
    await scanner.ensure_connected()
    fetcher = rt.data_fetcher
    if fetcher is None:
        raise HTTPException(status_code=503, detail="Broker market connection unavailable")
    try:
        df = await fetcher.get_historical_data(asset, timeframe=timeframe, count=count)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Market data unavailable: {exc}") from exc
    if df is None or df.empty:
        raise HTTPException(status_code=503, detail="No broker candles returned")

    frame = df.copy()
    frame.columns = [str(c).lower() for c in frame.columns]
    required = {"open", "high", "low", "close"}
    missing = required - set(frame.columns)
    if missing:
        raise HTTPException(status_code=503, detail=f"Candle feed missing columns: {sorted(missing)}")

    timestamp_column = next((c for c in ("timestamp", "time", "datetime", "date") if c in frame.columns), None)
    rows = []
    for index, row in frame.tail(count).iterrows():
        raw_ts = row.get(timestamp_column) if timestamp_column else index
        try:
            if isinstance(raw_ts, (int, float)):
                value = float(raw_ts)
                if value > 10_000_000_000:
                    value /= 1000.0
                ts = datetime.fromtimestamp(value, tz=timezone.utc).isoformat()
            else:
                parsed = pd.to_datetime(raw_ts, utc=True, errors="coerce")
                ts = parsed.isoformat() if not pd.isna(parsed) else None
        except Exception:
            ts = None
        try:
            rows.append({
                "time": ts,
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "volume": float(row["volume"]) if "volume" in frame.columns and pd.notna(row["volume"]) else None,
            })
        except (TypeError, ValueError):
            continue
    if not rows:
        raise HTTPException(status_code=503, detail="Broker candle feed contained no usable OHLC rows")

    # Phase 6 indicator payload. Calculated from the same broker candles returned above.
    c = pd.Series([x["close"] for x in rows], dtype="float64")
    h = pd.Series([x["high"] for x in rows], dtype="float64")
    l = pd.Series([x["low"] for x in rows], dtype="float64")
    ema20 = c.ewm(span=20, adjust=False).mean()
    ema50 = c.ewm(span=50, adjust=False).mean()
    ema100 = c.ewm(span=100, adjust=False).mean()
    ema12 = c.ewm(span=12, adjust=False).mean()
    ema26 = c.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    macd_signal = macd.ewm(span=9, adjust=False).mean()
    macd_hist = macd - macd_signal
    delta = c.diff()
    gain = delta.clip(lower=0).ewm(alpha=1/14, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1/14, adjust=False).mean()
    rsi = 100 - (100 / (1 + gain / loss.replace(0, np.nan)))
    prev = c.shift(1)
    tr = pd.concat([(h-l), (h-prev).abs(), (l-prev).abs()], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1/14, adjust=False).mean()
    mid = c.rolling(20).mean()
    std = c.rolling(20).std(ddof=0)
    bb_upper, bb_lower = mid + 2*std, mid - 2*std
    enriched=[]
    for i,row in enumerate(rows):
        enriched.append({**row, "ema20": float(ema20.iloc[i]) if pd.notna(ema20.iloc[i]) else None,
            "ema50": float(ema50.iloc[i]) if pd.notna(ema50.iloc[i]) else None,
            "ema100": float(ema100.iloc[i]) if pd.notna(ema100.iloc[i]) else None,
            "macd": float(macd.iloc[i]) if pd.notna(macd.iloc[i]) else None,
            "macd_signal": float(macd_signal.iloc[i]) if pd.notna(macd_signal.iloc[i]) else None,
            "macd_hist": float(macd_hist.iloc[i]) if pd.notna(macd_hist.iloc[i]) else None,
            "rsi": float(rsi.iloc[i]) if pd.notna(rsi.iloc[i]) else None,
            "atr": float(atr.iloc[i]) if pd.notna(atr.iloc[i]) else None,
            "bb_upper": float(bb_upper.iloc[i]) if pd.notna(bb_upper.iloc[i]) else None,
            "bb_mid": float(mid.iloc[i]) if pd.notna(mid.iloc[i]) else None,
            "bb_lower": float(bb_lower.iloc[i]) if pd.notna(bb_lower.iloc[i]) else None})
    return {
        "status": "LIVE", "asset": asset, "timeframe": timeframe, "count": len(enriched),
        "candles": enriched, "updated_at": datetime.now(timezone.utc).isoformat(),
        "indicators": {"ema20": float(ema20.iloc[-1]), "ema50": float(ema50.iloc[-1]), "ema100": float(ema100.iloc[-1]),
                        "macd": float(macd.iloc[-1]), "macd_signal": float(macd_signal.iloc[-1]),
                        "macd_hist": float(macd_hist.iloc[-1]), "rsi": float(rsi.iloc[-1]), "atr": float(atr.iloc[-1]),
                        "bb_upper": float(bb_upper.iloc[-1]), "bb_mid": float(mid.iloc[-1]), "bb_lower": float(bb_lower.iloc[-1])},
    }

@app.get("/api/market/signal/history", dependencies=[Depends(require_dashboard_key)])
def signal_history(limit: int = Query(default=25, ge=1, le=100)) -> dict:
    return {"history": list(_SIGNAL_HISTORY)[:limit], "count": min(limit, len(_SIGNAL_HISTORY))}


@app.get("/api/market/pending", dependencies=[Depends(require_dashboard_key)])
def market_pending() -> dict:
    # Uses the authoritative storage report rather than a second broker connection.
    start, end = _periods()["daily"]
    report = _runtime().storage.get_trade_report(start, end)
    pending = [t for t in report.get("trades", []) if str(t.get("result", "")).upper() in {"PENDING", "OPEN", "UNRESOLVED"}]
    return {"pending": pending, "count": len(pending), "updated_at": datetime.now(timezone.utc).isoformat()}


@app.get("/api/market/assets/{asset}", dependencies=[Depends(require_dashboard_key)])
async def market_asset(asset: str, timeframe: str = Query(default="1m")) -> dict:
    try:
        return await scanner.detail(asset, timeframe)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


async def _fresh_trade_signal(asset: str, timeframe: str) -> dict:
    timeframe = timeframe.lower().strip()
    if timeframe not in {"1m", "2m", "5m", "15m", "30m", "1h"}:
        raise HTTPException(status_code=400, detail=f"Unsupported timeframe: {timeframe}")
    if asset not in scanner.assets():
        raise HTTPException(status_code=400, detail=f"Unknown OTC asset: {asset}")
    rt = _runtime()
    await scanner.ensure_connected()
    if rt.data_fetcher is None or rt.api_client is None:
        raise HTTPException(status_code=503, detail="Broker market connection unavailable")
    candles = await rt.data_fetcher.get_historical_data(asset, timeframe=timeframe, count=200)
    result = await rt.signal_engine.generate_signal(asset=asset, timeframe=timeframe, candles=candles)
    return {"asset": asset, "timeframe": timeframe, "signal": result}


@app.post("/api/market/signal", dependencies=[Depends(require_dashboard_key)])
async def market_signal(asset: str = Query(..., min_length=1), timeframe: str = Query(default="1m")) -> dict:
    try:
        fresh = await _fresh_trade_signal(asset, timeframe)
        result = fresh["signal"]
        action = str(result.get("action") or "WAIT").upper()
        confidence = float(result.get("confidence") or 0.0)
        scan = await scanner.detail(asset, timeframe)
        entry_quality = "HIGH" if scan.get("strength", 0) >= 78 and not scan.get("conflicts") else "MEDIUM" if scan.get("strength", 0) >= 62 else "LOW"
        expiry_map = {"1m": [30, 60, 120], "2m": [60, 120, 300], "5m": [120, 300, 600], "15m": [300, 600], "30m": [600], "1h": [600]}
        expiry_note = "Trend-aligned setup" if action in {"CALL", "PUT"} and scan.get("trend") == ("BULLISH" if action == "CALL" else "BEARISH") else "Wait for alignment"
        decision = _DECISION_ENGINE.build(
            signal=result, scanner=scan, timeframe=timeframe, amount=None, balance=None, risk_blocked=False
        )
        enriched = {**fresh, "scanner": scan, "entry_quality": entry_quality,
                    "expiry_suitability": {"recommended_seconds": expiry_map.get(timeframe, [60]), "note": expiry_note},
                    "confidence_breakdown": {"engine_confidence": confidence, "scanner_score": scan.get("strength", 0),
                                             "trend": scan.get("trend"), "regime": scan.get("regime"),
                                             "multi_timeframe": scan.get("confirmation_trend")},
                    "decision": decision}
        _SIGNAL_HISTORY.appendleft({"asset": asset, "timeframe": timeframe, "action": action, "confidence": confidence,
                                    "scanner_score": scan.get("strength"), "entry_quality": entry_quality,
                                    "generated_at": result.get("timestamp") or datetime.now(timezone.utc).isoformat()})
        return {"status": "SIGNAL_READY" if action in {"CALL", "PUT"} else "WAIT", **enriched, "generated_at": result.get("timestamp")}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Signal engine unavailable: {exc}") from exc


def _dashboard_operator_id() -> int:
    raw = os.getenv("DASHBOARD_OPERATOR_ID", "").strip()
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = 0
    if value <= 0:
        raise HTTPException(status_code=503, detail="DASHBOARD_OPERATOR_ID is not configured on the server")
    return value


async def _trade_validation(payload: TradePreviewRequest) -> dict:
    rt = _runtime()
    amount = float(payload.amount)
    duration = int(payload.duration)
    minimum = float(getattr(rt.settings, "MIN_TRADE_AMOUNT", 0.0))
    maximum = float(getattr(rt.settings, "MAX_TRADE_AMOUNT", 0.0))
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
    get_balance = getattr(rt.api_client, "get_balance", None)
    if callable(get_balance):
        try:
            balance = float(await get_balance())
        except Exception:
            balance = None

    reasons = []
    if action not in {"CALL", "PUT"}: reasons.append("Signal is not executable.")
    if confidence < float(getattr(rt.settings, "MIN_CONFIDENCE", 70)): reasons.append("Signal confidence is below the configured minimum.")
    if balance is None: reasons.append("Broker balance is unavailable.")
    elif amount > balance: reasons.append("Trade amount exceeds available balance.")

    risk_blocked = False
    if balance is not None:
        risk = RiskManager(account_balance=balance, max_risk_per_trade=0.02)
        risk_blocked = risk.should_block(amount, confidence)
        if risk_blocked:
            reasons.append("Risk manager rejected the requested amount/confidence.")

    scan = await scanner.detail(payload.asset, payload.timeframe)
    decision = _DECISION_ENGINE.build(
        signal=signal, scanner=scan, timeframe=payload.timeframe,
        amount=amount, balance=balance, risk_blocked=risk_blocked
    )
    reasons.extend(decision["no_trade_conditions"])
    # Keep order stable while removing duplicates.
    reasons = list(dict.fromkeys(reasons))

    return {
        "allowed": not reasons and decision["decision"] == "EXECUTE_CANDIDATE",
        "reasons": reasons, "asset": fresh["asset"],
        "timeframe": fresh["timeframe"], "signal": signal, "scanner": scan,
        "decision": decision, "amount": amount,
        "duration": duration, "balance": balance, "min_amount": minimum,
        "max_amount": maximum, "demo_mode": bool(getattr(rt.settings, "DEMO_MODE", True)),
    }


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
    rt = _runtime()
    async with _EXECUTION_LOCK:
        preview = await _trade_validation(payload)
        if not preview["allowed"]:
            raise HTTPException(status_code=409, detail="Trade blocked: " + " ".join(preview["reasons"]))

        signal_data = preview["signal"]
        direction = str(signal_data.get("action") or "").upper()
        amount = float(preview["amount"])
        duration = int(preview["duration"])
        asset = preview["asset"]
        import time
        dedup_key = f"{asset}|{direction}|{amount:.8f}|{duration}"
        now_mono = time.monotonic()
        previous = _LAST_EXECUTIONS.get(dedup_key)
        if previous is not None and now_mono - previous < _EXECUTION_DEDUP_SECONDS:
            raise HTTPException(status_code=409, detail="Duplicate execution blocked. Wait a few seconds before submitting the same trade again.")

        place_trade = getattr(rt.api_client, "place_trade", None)
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
        trade_row_id = rt.storage.save_trade(
            user_id=operator_id, chat_id=operator_id, asset=asset,
            direction=direction, amount=amount, duration_secs=duration,
            order_id=trade_id, entry_price=signal_data.get("entry_price"),
        )
        if trade_row_id is None:
            raise HTTPException(status_code=500, detail="Broker accepted the trade, but local audit recording failed. Reconciliation is required.")
        _LAST_EXECUTIONS[dedup_key] = now_mono
        return {
            "status": "EXECUTED", "trade_id": trade_id, "trade_history_id": trade_row_id,
            "operator_id": operator_id, "asset": asset, "direction": direction,
            "amount": amount, "duration": duration, "entry_price": signal_data.get("entry_price"),
            "signal_confidence": signal_data.get("confidence"), "signal_timestamp": signal_data.get("timestamp"),
            "demo_mode": preview["demo_mode"],
            "decision": preview.get("decision"),
            "execution": {"status": "SUBMITTED", "broker_order_id": trade_id, "settlement": "PENDING"},
        }

@app.get("/api/phase7/decision/{asset}", dependencies=[Depends(require_dashboard_key)])
async def phase7_decision(asset: str, timeframe: str = Query(default="1m")) -> dict:
    """Return the complete decision package without executing a trade."""
    try:
        fresh = await _fresh_trade_signal(asset, timeframe)
        scan = await scanner.detail(asset, timeframe)
        decision = _DECISION_ENGINE.build(
            signal=fresh["signal"], scanner=scan, timeframe=timeframe
        )
        return {"status": "READY", "decision": decision, "generated_at": datetime.now(timezone.utc).isoformat()}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Decision analysis unavailable: {exc}") from exc


@app.post("/api/phase7/trade-preview", dependencies=[Depends(require_dashboard_key)])
async def phase7_trade_preview(payload: TradePreviewRequest) -> dict:
    """Generate the full pre-trade checklist and risk gate."""
    try:
        preview = await _trade_validation(payload)
        return {"status": "READY" if preview["allowed"] else "BLOCKED", **preview,
                "checklist": {
                    "live_market_data": True,
                    "signal_available": str(preview["signal"].get("action", "WAIT")).upper() in {"CALL", "PUT"},
                    "risk_validated": preview["decision"]["risk"]["status"] == "OK",
                    "user_confirmation_required": True,
                }}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Trade preview unavailable: {exc}") from exc


@app.get("/api/phase7/opportunities", dependencies=[Depends(require_dashboard_key)])
async def phase7_opportunities(timeframe: str = Query(default="1m"), limit: int = Query(default=10, ge=1, le=50)) -> dict:
    """Rank current scanner opportunities without placing trades."""
    result = await scanner.scan(timeframe)
    rows = [r for r in result.get("rows", []) if r.get("status") == "READY"]
    rows.sort(key=lambda r: (float(r.get("strength") or 0), float(r.get("quality_grade", "D") == "A")), reverse=True)
    opportunities = []
    for row in rows[:limit]:
        opportunities.append({
            "asset": row.get("asset"), "direction": row.get("direction", "WAIT"),
            "scanner_score": row.get("strength", 0), "quality_grade": row.get("quality_grade"),
            "readiness": row.get("readiness"), "regime": row.get("regime"),
            "conflicts": row.get("conflicts", []), "trend": row.get("trend"),
            "volatility_state": row.get("volatility_state"),
        })
    return {"status": result.get("status"), "timeframe": timeframe, "opportunities": opportunities,
            "count": len(opportunities), "updated_at": datetime.now(timezone.utc).isoformat()}


@app.get("/api/phase7/journal", dependencies=[Depends(require_dashboard_key)])
def phase7_journal(period: str = Query(default="daily", pattern="^(daily|weekly|monthly)$"), limit: int = Query(default=100, ge=1, le=500)) -> dict:
    periods = _periods()
    start, end = periods[period]
    report = _runtime().storage.get_trade_report(start, end)
    trades = list(report.get("trades", []))[-limit:][::-1]
    return {"period": period, "trades": trades, "count": len(trades), "summary": {k: report.get(k) for k in ("total", "settled", "wins", "losses", "draws", "pending", "unresolved", "win_rate", "net_pl")}}


@app.get("/api/phase7/compare", dependencies=[Depends(require_dashboard_key)])
async def phase7_compare(assets: str = Query(..., description="Comma-separated OTC assets"), timeframe: str = Query(default="1m")) -> dict:
    names = [x.strip() for x in assets.split(",") if x.strip()]
    if not names or len(names) > 10:
        raise HTTPException(status_code=400, detail="Provide between 1 and 10 assets")
    rows = []
    for asset in names:
        if asset not in scanner.assets():
            continue
        try:
            row = await scanner.detail(asset, timeframe)
            rows.append({
                "asset": asset, "score": row.get("strength", 0), "direction": row.get("direction", "WAIT"),
                "quality_grade": row.get("quality_grade"), "regime": row.get("regime"),
                "trend": row.get("trend"), "momentum": row.get("momentum"),
                "volatility": row.get("volatility_state"), "conflicts": row.get("conflicts", []),
            })
        except Exception as exc:
            rows.append({"asset": asset, "status": "DATA_UNAVAILABLE", "error": str(exc)})
    rows.sort(key=lambda x: float(x.get("score") or 0), reverse=True)
    return {"timeframe": timeframe, "assets": rows, "updated_at": datetime.now(timezone.utc).isoformat()}


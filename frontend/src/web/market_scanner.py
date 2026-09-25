from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

import numpy as np
import pandas as pd

from config.settings import get_settings
from src.api.factory import create_broker_client
from src.api.data_fetcher import MarketDataFetcher

_ALLOWED_TIMEFRAMES = {"1m", "2m", "5m", "15m", "30m", "1h"}
_DEFAULT_COUNT = 200
_SCANNER_COUNT = 80
_SCANNER_CONCURRENCY = 3
_CACHE_SECONDS = 12


class LiveMarketScanner:
    """Read-only scanner. Never uses synthetic/demo candles."""

    def __init__(self) -> None:
        self.settings = get_settings(require_token=False)
        self.client: Any = None
        self.fetcher: MarketDataFetcher | None = None
        self._lock = asyncio.Lock()
        self._connect_error: str | None = None
        self._scan_semaphore = asyncio.Semaphore(_SCANNER_CONCURRENCY)
        self._scan_cache: dict[tuple[str, str], tuple[float, dict[str, Any]]] = {}
        self._scan_tasks: dict[str, asyncio.Task[dict[str, Any]]] = {}

    def assets(self) -> list[str]:
        raw = getattr(self.settings, "OTC_ASSETS", [])
        if isinstance(raw, dict):
            return [str(k) for k in raw.keys()]
        return [str(x) for x in raw]

    async def ensure_connected(self) -> None:
        if self.client is not None and getattr(self.client, "is_connected", False):
            return
        async with self._lock:
            if self.client is not None and getattr(self.client, "is_connected", False):
                return
            try:
                self.client = create_broker_client(self.settings)
                await self.client.connect()
                if not getattr(self.client, "is_connected", False):
                    raise RuntimeError("broker connection did not become active")
                self.fetcher = MarketDataFetcher(client=self.client, demo_mode=False)
                self._connect_error = None
            except Exception as exc:
                self._connect_error = str(exc)
                self.client = None
                self.fetcher = None
                raise

    async def close(self) -> None:
        client = self.client
        self.client = None
        self.fetcher = None
        if client is not None:
            try:
                close = getattr(client, "disconnect", None) or getattr(client, "close", None)
                if close:
                    result = close()
                    if asyncio.iscoroutine(result):
                        await result
            except Exception:
                pass

    async def scan(self, timeframe: str = "1m") -> dict[str, Any]:
        timeframe = timeframe.lower().strip()
        if timeframe not in _ALLOWED_TIMEFRAMES:
            raise ValueError(f"Unsupported timeframe: {timeframe}")

        now = asyncio.get_running_loop().time()
        cached = self._scan_cache.get(("scan", timeframe))
        if cached and (now - cached[0]) < _CACHE_SECONDS:
            return cached[1]

        existing = self._scan_tasks.get(timeframe)
        if existing is not None and not existing.done():
            return await existing

        task = asyncio.create_task(self._perform_scan(timeframe))
        self._scan_tasks[timeframe] = task
        try:
            return await task
        finally:
            if self._scan_tasks.get(timeframe) is task:
                self._scan_tasks.pop(timeframe, None)

    async def _perform_scan(self, timeframe: str) -> dict[str, Any]:
        try:
            await self.ensure_connected()
        except Exception:
            return self._unavailable(
                timeframe,
                self._connect_error or "broker unavailable",
            )

        assets = self.assets()

        async def scan_one(asset: str) -> dict[str, Any]:
            try:
                async with self._scan_semaphore:
                    return await self._scan_asset(asset, timeframe)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                return {
                    "asset": asset,
                    "status": "DATA_UNAVAILABLE",
                    "error": str(exc),
                    "timeframe": timeframe,
                }

        rows = list(await asyncio.gather(*(scan_one(asset) for asset in assets)))

        ready = [r for r in rows if r.get("status") == "READY"]
        ready.sort(key=lambda r: r.get("strength", 0), reverse=True)

        result = {
            "status": "LIVE" if ready else "DATA_UNAVAILABLE",
            "timeframe": timeframe,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "assets_tracked": len(rows),
            "ready": len(ready),
            "rows": rows,
        }

        self._scan_cache[("scan", timeframe)] = (
            asyncio.get_running_loop().time(),
            result,
        )
        return result

    async def detail(self, asset: str, timeframe: str = "1m") -> dict[str, Any]:
        timeframe = timeframe.lower().strip()
        if timeframe not in _ALLOWED_TIMEFRAMES:
            raise ValueError(f"Unsupported timeframe: {timeframe}")
        if asset not in self.assets():
            raise ValueError(f"Unknown OTC asset: {asset}")
        try:
            await self.ensure_connected()
            return await self._scan_asset(asset, timeframe)
        except Exception as exc:
            return {
                "asset": asset,
                "timeframe": timeframe,
                "status": "DATA_UNAVAILABLE",
                "error": str(exc),
            }

    async def _scan_asset(self, asset: str, timeframe: str) -> dict[str, Any]:
        cache_key = (asset, timeframe)
        cached = self._scan_cache.get(cache_key)
        if cached is not None:
            cached_at, cached_result = cached
            if asyncio.get_running_loop().time() - cached_at < _CACHE_SECONDS:
                return cached_result

        if self.fetcher is None:
            raise RuntimeError("scanner broker is not connected")
        df = await self.fetcher.get_historical_data(asset, timeframe=timeframe, count=_SCANNER_COUNT)
        if df is None or df.empty:
            raise RuntimeError("no candles returned")
        df = df.copy()
        df.columns = [str(c).lower() for c in df.columns]
        required = {"open", "high", "low", "close"}
        if not required.issubset(df.columns):
            raise RuntimeError(f"missing OHLC columns: {sorted(required - set(df.columns))}")

        close = pd.to_numeric(df["close"], errors="coerce")
        high = pd.to_numeric(df["high"], errors="coerce")
        low = pd.to_numeric(df["low"], errors="coerce")
        valid = close.notna() & high.notna() & low.notna()
        close, high, low = close[valid], high[valid], low[valid]
        if len(close) < 50:
            raise RuntimeError(f"insufficient candles: {len(close)}")

        delta = close.diff()
        gain = delta.clip(lower=0).ewm(alpha=1/14, adjust=False).mean()
        loss = (-delta.clip(upper=0)).ewm(alpha=1/14, adjust=False).mean()
        rs = gain / loss.replace(0, np.nan)
        rsi = float((100 - (100 / (1 + rs))).iloc[-1])

        ema12 = close.ewm(span=12, adjust=False).mean()
        ema26 = close.ewm(span=26, adjust=False).mean()
        macd = ema12 - ema26
        macd_signal = macd.ewm(span=9, adjust=False).mean()
        macd_hist = macd - macd_signal
        ema20 = close.ewm(span=20, adjust=False).mean()
        ema50 = close.ewm(span=50, adjust=False).mean()

        prev = close.shift(1)
        tr = pd.concat([(high-low), (high-prev).abs(), (low-prev).abs()], axis=1).max(axis=1)
        atr = float(tr.ewm(alpha=1/14, adjust=False).mean().iloc[-1])

        last = float(close.iloc[-1])
        e20 = float(ema20.iloc[-1])
        e50 = float(ema50.iloc[-1])
        m = float(macd.iloc[-1])
        ms = float(macd_signal.iloc[-1])
        mh = float(macd_hist.iloc[-1])

        if last > e20 > e50:
            trend, trend_score = "BULLISH", 25
        elif last < e20 < e50:
            trend, trend_score = "BEARISH", 25
        elif last > e20:
            trend, trend_score = "BULLISH", 15
        elif last < e20:
            trend, trend_score = "BEARISH", 15
        else:
            trend, trend_score = "NEUTRAL", 0

        momentum_score = 20 if ((m > ms and mh > 0) or (m < ms and mh < 0)) else 8
        rsi_score = 15 if ((trend == "BULLISH" and 50 <= rsi <= 70) or
                            (trend == "BEARISH" and 30 <= rsi <= 50)) else 8
        macd_score = 15 if ((trend == "BULLISH" and m > ms) or
                            (trend == "BEARISH" and m < ms)) else 6
        ema_score = 10 if ((last > e20 > e50) or (last < e20 < e50)) else 5

        lookback = min(10, len(close) - 1)
        move = float(close.iloc[-1] - close.iloc[-1-lookback])
        price_score = 10 if ((move > 0 and trend == "BULLISH") or
                             (move < 0 and trend == "BEARISH")) else 5

        atr_pct = (atr / last * 100) if last else 0.0
        volatility_score = 5 if 0.02 <= atr_pct <= 0.8 else 3
        strength = int(round(
            trend_score + momentum_score + rsi_score + macd_score +
            ema_score + price_score + volatility_score
        ))
        readiness = "READY" if strength >= 70 else "WATCH" if strength >= 55 else "WAIT"

        result = {
            "asset": asset,
            "timeframe": timeframe,
            "status": "READY",
            "bias": trend,
            "trend": trend,
            "strength": strength,
            "rsi": round(rsi, 2),
            "macd": round(m, 6),
            "macd_signal": round(ms, 6),
            "macd_hist": round(mh, 6),
            "ema20": round(e20, 6),
            "ema50": round(e50, 6),
            "atr": round(atr, 6),
            "atr_percent": round(atr_pct, 4),
            "price": round(last, 8),
            "readiness": readiness,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

        self._scan_cache[cache_key] = (
            asyncio.get_running_loop().time(),
            result,
        )
        return result

    @staticmethod
    def _unavailable(timeframe: str, error: str) -> dict[str, Any]:
        return {
            "status": "DATA_UNAVAILABLE",
            "timeframe": timeframe,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "assets_tracked": 0,
            "ready": 0,
            "rows": [],
            "error": error,
        }


scanner = LiveMarketScanner()




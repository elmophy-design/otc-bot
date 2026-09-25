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
_SCANNER_COUNT = 120
_SCANNER_CONCURRENCY = 3
_CACHE_SECONDS = 10
_CONFIRM_TF = {"1m": "5m", "2m": "5m", "5m": "15m", "15m": "30m", "30m": "1h", "1h": "1h"}


def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
    d = close.diff()
    gain = d.clip(lower=0).ewm(alpha=1 / period, adjust=False).mean()
    loss = (-d.clip(upper=0)).ewm(alpha=1 / period, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def _atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    prev = close.shift(1)
    tr = pd.concat([(high-low), (high-prev).abs(), (low-prev).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False).mean()


def _adx(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    up = high.diff()
    down = -low.diff()
    plus_dm = up.where((up > down) & (up > 0), 0.0)
    minus_dm = down.where((down > up) & (down > 0), 0.0)
    atr = _atr(high, low, close, period).replace(0, np.nan)
    plus_di = 100 * plus_dm.ewm(alpha=1/period, adjust=False).mean() / atr
    minus_di = 100 * minus_dm.ewm(alpha=1/period, adjust=False).mean() / atr
    dx = ((plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)) * 100
    return dx.ewm(alpha=1/period, adjust=False).mean()


def _stochastic(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> float:
    ll = low.rolling(period).min()
    hh = high.rolling(period).max()
    value = ((close - ll) / (hh - ll).replace(0, np.nan)) * 100
    return float(value.iloc[-1])


def _profile(df: pd.DataFrame) -> dict[str, Any]:
    close = pd.to_numeric(df["close"], errors="coerce")
    high = pd.to_numeric(df["high"], errors="coerce")
    low = pd.to_numeric(df["low"], errors="coerce")
    valid = close.notna() & high.notna() & low.notna()
    close, high, low = close[valid], high[valid], low[valid]
    if len(close) < 60:
        raise RuntimeError(f"insufficient candles: {len(close)}")

    ema9 = close.ewm(span=9, adjust=False).mean()
    ema20 = close.ewm(span=20, adjust=False).mean()
    ema50 = close.ewm(span=50, adjust=False).mean()
    ema100 = close.ewm(span=100, adjust=False).mean()
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    macd_signal = macd.ewm(span=9, adjust=False).mean()
    macd_hist = macd - macd_signal
    rsi = _rsi(close)
    atr = _atr(high, low, close)
    adx = _adx(high, low, close)
    stoch = _stochastic(high, low, close)
    mid = close.rolling(20).mean()
    std = close.rolling(20).std(ddof=0)
    upper = mid + 2 * std
    lower = mid - 2 * std

    last = float(close.iloc[-1])
    e9, e20, e50, e100 = [float(x.iloc[-1]) for x in (ema9, ema20, ema50, ema100)]
    r = float(rsi.iloc[-1])
    m, ms, mh = float(macd.iloc[-1]), float(macd_signal.iloc[-1]), float(macd_hist.iloc[-1])
    a = float(atr.iloc[-1])
    adx_v = float(adx.iloc[-1]) if pd.notna(adx.iloc[-1]) else 0.0
    bb_mid = float(mid.iloc[-1])
    bb_u = float(upper.iloc[-1])
    bb_l = float(lower.iloc[-1])
    bb_width = ((bb_u - bb_l) / last * 100) if last else 0.0
    atr_pct = (a / last * 100) if last else 0.0

    trend = "BULLISH" if last > e20 > e50 else "BEARISH" if last < e20 < e50 else "NEUTRAL"
    alignment = "STRONG_BULLISH" if last > e9 > e20 > e50 > e100 else "STRONG_BEARISH" if last < e9 < e20 < e50 < e100 else trend
    macd_bias = "BULLISH" if m > ms and mh > 0 else "BEARISH" if m < ms and mh < 0 else "MIXED"
    momentum = "BULLISH" if r >= 55 and r < 75 else "BEARISH" if r <= 45 and r > 25 else "NEUTRAL"
    regime = "TRENDING" if adx_v >= 25 else "RANGING" if adx_v < 18 else "TRANSITION"
    volatility = "HIGH" if atr_pct >= 0.8 else "LOW" if atr_pct <= 0.12 else "NORMAL"
    bb_position = ((last - bb_l) / (bb_u - bb_l) * 100) if bb_u != bb_l else 50.0
    lookback = min(12, len(close) - 1)
    move_pct = ((last / float(close.iloc[-1-lookback])) - 1) * 100
    slope = ((e20 / float(ema20.iloc[-6])) - 1) * 100 if len(ema20) >= 7 else 0.0

    return {
        "price": round(last, 8), "rsi": round(r, 2), "macd": round(m, 6),
        "macd_signal": round(ms, 6), "macd_hist": round(mh, 6),
        "ema9": round(e9, 8), "ema20": round(e20, 8), "ema50": round(e50, 8), "ema100": round(e100, 8),
        "atr": round(a, 8), "atr_percent": round(atr_pct, 4), "adx": round(adx_v, 2),
        "stochastic": round(stoch, 2), "bb_mid": round(bb_mid, 8), "bb_upper": round(bb_u, 8),
        "bb_lower": round(bb_l, 8), "bb_width_percent": round(bb_width, 4), "bb_position": round(bb_position, 2),
        "trend": trend, "ema_alignment": alignment, "macd_bias": macd_bias, "momentum": momentum,
        "regime": regime, "volatility_state": volatility, "move_percent": round(move_pct, 4),
        "ema20_slope_percent": round(slope, 4), "stochastic_state": "OVERBOUGHT" if stoch >= 80 else "OVERSOLD" if stoch <= 20 else "MID",
    }


def _score(profile: dict[str, Any], confirmation: dict[str, Any] | None) -> dict[str, Any]:
    trend = str(profile["trend"])
    bull = trend == "BULLISH"
    bear = trend == "BEARISH"
    components: dict[str, float] = {}
    components["trend_structure"] = 18 if profile["ema_alignment"].startswith("STRONG_") else 12 if trend != "NEUTRAL" else 5
    components["momentum"] = 12 if profile["momentum"] == trend else 6 if profile["momentum"] == "NEUTRAL" else 2
    components["macd"] = 12 if profile["macd_bias"] == trend else 6 if profile["macd_bias"] == "MIXED" else 2
    components["rsi"] = 10 if ((bull and 50 <= profile["rsi"] <= 70) or (bear and 30 <= profile["rsi"] <= 50)) else 5
    components["price_action"] = 10 if ((bull and profile["move_percent"] > 0) or (bear and profile["move_percent"] < 0)) else 4
    components["volatility"] = 8 if profile["volatility_state"] == "NORMAL" else 4 if profile["volatility_state"] == "LOW" else 2
    components["regime"] = 8 if profile["regime"] == "TRENDING" else 5 if profile["regime"] == "TRANSITION" else 2
    components["band_location"] = 5 if ((bull and 35 <= profile["bb_position"] <= 80) or (bear and 20 <= profile["bb_position"] <= 65)) else 2
    components["multi_timeframe"] = 17 if confirmation and confirmation["trend"] == trend else 8 if confirmation and confirmation["trend"] == "NEUTRAL" else 2
    total = min(100, int(round(sum(components.values()))))
    direction = "CALL" if bull else "PUT" if bear else "WAIT"
    readiness = "HIGH" if total >= 78 else "MEDIUM" if total >= 62 else "LOW"
    conflicts = []
    if profile["regime"] == "RANGING": conflicts.append("Market is range-bound")
    if profile["volatility_state"] == "HIGH": conflicts.append("Volatility is elevated")
    if profile["momentum"] not in {trend, "NEUTRAL"} and trend != "NEUTRAL": conflicts.append("Momentum conflicts with trend")
    if confirmation and trend != "NEUTRAL" and confirmation["trend"] not in {trend, "NEUTRAL"}: conflicts.append("Higher timeframe disagrees")
    quality = "A" if total >= 82 and not conflicts else "B" if total >= 70 else "C" if total >= 55 else "D"
    return {"score": total, "direction": direction, "readiness": readiness, "quality_grade": quality,
            "components": {k: round(v, 1) for k, v in components.items()}, "conflicts": conflicts}


class LiveMarketScanner:
    """Read-only scanner using the bot-owned broker session when bound."""
    def __init__(self) -> None:
        self.settings = get_settings(require_token=False)
        self.client: Any = None
        self.fetcher: MarketDataFetcher | None = None
        self._lock = asyncio.Lock()
        self._connect_error: str | None = None
        self._bound_client: Any = None
        self._bound_fetcher: MarketDataFetcher | None = None
        self._scan_semaphore = asyncio.Semaphore(_SCANNER_CONCURRENCY)
        self._scan_cache: dict[tuple[str, str], tuple[float, dict[str, Any]]] = {}
        self._scan_tasks: dict[str, asyncio.Task[dict[str, Any]]] = {}

    def bind_runtime(self, client: Any, fetcher: MarketDataFetcher | None) -> None:
        self._bound_client, self._bound_fetcher = client, fetcher
        self.client, self.fetcher = client, fetcher
        self._connect_error = None

    def assets(self) -> list[str]:
        raw = getattr(self.settings, "OTC_ASSETS", [])
        return [str(k) for k in raw.keys()] if isinstance(raw, dict) else [str(x) for x in raw]

    async def ensure_connected(self) -> None:
        if self._bound_client is not None:
            self.client, self.fetcher = self._bound_client, self._bound_fetcher
            if not getattr(self.client, "is_connected", False): raise RuntimeError("bot-owned broker connection is not connected")
            if self.fetcher is None: raise RuntimeError("bot-owned market data fetcher is unavailable")
            return
        if self.client is not None and getattr(self.client, "is_connected", False): return
        async with self._lock:
            if self.client is not None and getattr(self.client, "is_connected", False): return
            try:
                self.client = create_broker_client(self.settings)
                await self.client.connect()
                if not getattr(self.client, "is_connected", False): raise RuntimeError("broker connection did not become active")
                self.fetcher = MarketDataFetcher(client=self.client, demo_mode=False)
            except Exception as exc:
                self._connect_error, self.client, self.fetcher = str(exc), None, None
                raise

    async def close(self) -> None:
        if self._bound_client is not None: return
        client, self.client, self.fetcher = self.client, None, None
        if client:
            try:
                close = getattr(client, "disconnect", None) or getattr(client, "close", None)
                if close:
                    result = close()
                    if asyncio.iscoroutine(result): await result
            except Exception: pass

    async def scan(self, timeframe: str = "1m") -> dict[str, Any]:
        timeframe = timeframe.lower().strip()
        if timeframe not in _ALLOWED_TIMEFRAMES: raise ValueError(f"Unsupported timeframe: {timeframe}")
        now = asyncio.get_running_loop().time()
        cached = self._scan_cache.get(("scan", timeframe))
        if cached and now - cached[0] < _CACHE_SECONDS: return cached[1]
        existing = self._scan_tasks.get(timeframe)
        if existing and not existing.done(): return await existing
        task = asyncio.create_task(self._perform_scan(timeframe)); self._scan_tasks[timeframe] = task
        try: return await task
        finally:
            if self._scan_tasks.get(timeframe) is task: self._scan_tasks.pop(timeframe, None)

    async def _perform_scan(self, timeframe: str) -> dict[str, Any]:
        try: await self.ensure_connected()
        except Exception: return self._unavailable(timeframe, self._connect_error or "broker unavailable")
        async def scan_one(asset: str) -> dict[str, Any]:
            try:
                async with self._scan_semaphore: return await self._scan_asset(asset, timeframe)
            except asyncio.CancelledError: raise
            except Exception as exc: return {"asset": asset, "status": "DATA_UNAVAILABLE", "error": str(exc), "timeframe": timeframe}
        rows = list(await asyncio.gather(*(scan_one(a) for a in self.assets())))
        ready = [r for r in rows if r.get("status") == "READY"]
        ready.sort(key=lambda r: r.get("strength", 0), reverse=True)
        result = {"status": "LIVE" if ready else "DATA_UNAVAILABLE", "timeframe": timeframe,
                  "confirmation_timeframe": _CONFIRM_TF[timeframe], "updated_at": datetime.now(timezone.utc).isoformat(),
                  "assets_tracked": len(rows), "ready": len(ready), "rows": rows, "assets": ready}
        self._scan_cache[("scan", timeframe)] = (asyncio.get_running_loop().time(), result)
        return result

    async def detail(self, asset: str, timeframe: str = "1m") -> dict[str, Any]:
        timeframe = timeframe.lower().strip()
        if timeframe not in _ALLOWED_TIMEFRAMES: raise ValueError(f"Unsupported timeframe: {timeframe}")
        if asset not in self.assets(): raise ValueError(f"Unknown OTC asset: {asset}")
        try: await self.ensure_connected(); return await self._scan_asset(asset, timeframe)
        except Exception as exc: return {"asset": asset, "timeframe": timeframe, "status": "DATA_UNAVAILABLE", "error": str(exc)}

    async def _scan_asset(self, asset: str, timeframe: str) -> dict[str, Any]:
        key = (asset, timeframe); cached = self._scan_cache.get(key)
        if cached and asyncio.get_running_loop().time() - cached[0] < _CACHE_SECONDS: return cached[1]
        if self.fetcher is None: raise RuntimeError("scanner broker is not connected")
        df = await self.fetcher.get_historical_data(asset, timeframe=timeframe, count=_SCANNER_COUNT)
        if df is None or df.empty: raise RuntimeError("no candles returned")
        df = df.copy(); df.columns = [str(c).lower() for c in df.columns]
        if not {"open", "high", "low", "close"}.issubset(df.columns): raise RuntimeError("missing OHLC columns")
        profile = _profile(df)
        confirm = None
        ctf = _CONFIRM_TF[timeframe]
        if ctf != timeframe:
            cdf = await self.fetcher.get_historical_data(asset, timeframe=ctf, count=100)
            if cdf is not None and not cdf.empty:
                cdf = cdf.copy(); cdf.columns = [str(c).lower() for c in cdf.columns]
                if {"high", "low", "close"}.issubset(cdf.columns): confirm = _profile(cdf)
        scored = _score(profile, confirm)
        result = {"asset": asset, "timeframe": timeframe, "status": "READY", "bias": profile["trend"],
                  "trend": profile["trend"], "strength": scored["score"], "readiness": scored["readiness"],
                  "score": scored["score"], "quality_grade": scored["quality_grade"], "direction": scored["direction"],
                  "score_components": scored["components"], "conflicts": scored["conflicts"],
                  "confirmation_timeframe": ctf, "confirmation_trend": confirm["trend"] if confirm else None,
                  "regime": profile["regime"], "momentum": profile["momentum"], "volatility_state": profile["volatility_state"],
                  "updated_at": datetime.now(timezone.utc).isoformat(), **profile}
        self._scan_cache[key] = (asyncio.get_running_loop().time(), result)
        return result

    @staticmethod
    def _unavailable(timeframe: str, error: str) -> dict[str, Any]:
        return {"status": "DATA_UNAVAILABLE", "timeframe": timeframe, "updated_at": datetime.now(timezone.utc).isoformat(),
                "assets_tracked": 0, "ready": 0, "rows": [], "assets": [], "error": error}


scanner = LiveMarketScanner()

"""
BinaryOptionsTools-v2 adapter.

Optional live backend. Install with:
  pip install BinaryOptionsToolsV2
  # or from GitHub releases / source if wheels fail

Selected via env:
  LIVE_BACKEND=auto|botv2|native
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Union

import pandas as pd

from ..utils.logger import get_logger
from .protocol import parse_ssid, timeframe_to_seconds

logger = get_logger(__name__)

# Optional dependency
_BOTV2_AVAILABLE = False
_PocketOptionAsync = None
_import_error: Optional[str] = None

try:
    from BinaryOptionsToolsV2 import PocketOptionAsync  # type: ignore

    _PocketOptionAsync = PocketOptionAsync
    _BOTV2_AVAILABLE = True
except Exception as e1:
    try:
        from BinaryOptionsToolsV2.pocketoption import PocketOptionAsync  # type: ignore

        _PocketOptionAsync = PocketOptionAsync
        _BOTV2_AVAILABLE = True
    except Exception as e2:
        _import_error = f"{e1} | {e2}"
        _BOTV2_AVAILABLE = False


def botv2_available() -> bool:
    return _BOTV2_AVAILABLE


def botv2_import_error() -> Optional[str]:
    return _import_error


class BotV2Client:
    """
    Thin async adapter that exposes the same surface our MarketDataFetcher expects:
      - connect() / disconnect()
      - is_connected / is_authenticated
      - get_candles(asset, timeframe, count) -> DataFrame
    """

    def __init__(self, settings: Any):
        self.settings = settings
        self.demo_mode = getattr(settings, "DEMO_MODE", True)
        self._client: Any = None
        self._connected = False
        self._authenticated = False
        self._ssid_raw = getattr(settings, "POCKETOPTION_SSID", None) or ""
        self._ssid_for_lib = self._normalize_ssid(self._ssid_raw)
        # Remembers which candle-fetch method actually worked last time so
        # subsequent calls skip straight to it instead of re-probing every
        # method in order (this was the main source of slow "Analyzing…").
        self._working_candle_method: Optional[str] = None

    @staticmethod
    def _normalize_ssid(raw: str) -> str:
        """BOTv2 accepts full 42[\"auth\",...] or session-only depending on version."""
        raw = (raw or "").strip()
        if not raw:
            return ""
        try:
            parsed = parse_ssid(raw)
            # Prefer full wire format when we have structured fields
            if "auth" in raw:
                return raw
            return parsed.session or raw
        except Exception:
            return raw

    @property
    def is_connected(self) -> bool:
        return self._connected and self._client is not None

    @property
    def is_authenticated(self) -> bool:
        return self._authenticated

    async def connect(self) -> bool:
        if not _BOTV2_AVAILABLE or _PocketOptionAsync is None:
            logger.warning(
                "BinaryOptionsToolsV2 not installed (%s)", _import_error
            )
            return False

        if not self._ssid_for_lib:
            logger.info("No SSID – BotV2Client cannot connect")
            return False

        try:
            # Some versions use context manager; we keep a long-lived instance
            self._client = _PocketOptionAsync(ssid=self._ssid_for_lib)
            # Optional: some builds need an explicit connect / sleep for handshake
            if hasattr(self._client, "connect") and callable(self._client.connect):
                res = self._client.connect()
                if asyncio.iscoroutine(res):
                    await res
            else:
                # Give native layer a moment to establish WS
                await asyncio.sleep(2.0)

            # Wait until assets are loaded (critical for history/ticks)
            if hasattr(self._client, "wait_for_assets"):
                try:
                    await asyncio.wait_for(self._client.wait_for_assets(), timeout=12.0)
                except Exception as e:
                    logger.debug("wait_for_assets: %s", e)
                    await asyncio.sleep(2.0)
            else:
                await asyncio.sleep(2.0)

            # Probe with balance if available
            bal = await self._try_balance()
            self._connected = True
            self._authenticated = bal is not None or True
            logger.info(
                "✅ BotV2 connected (balance=%s)",
                bal if bal is not None else "n/a",
            )
            return True
        except Exception as e:
            logger.warning("BotV2 connect failed: %s", e)
            self._client = None
            self._connected = False
            self._authenticated = False
            if not self.demo_mode:
                raise
            return False

    async def _try_balance(self) -> Optional[float]:
        if self._client is None:
            return None
        for name in ("balance", "get_balance"):
            if hasattr(self._client, name):
                try:
                    res = getattr(self._client, name)()
                    if asyncio.iscoroutine(res):
                        res = await res
                    if isinstance(res, (int, float)):
                        return float(res)
                    if hasattr(res, "balance"):
                        return float(res.balance)
                    if isinstance(res, dict) and "balance" in res:
                        return float(res["balance"])
                except Exception as e:
                    logger.debug("balance probe via %s failed: %s", name, e)
        return None

    async def get_candles(
        self,
        asset: str,
        timeframe: Union[str, int] = "1m",
        count: int = 200,
        end_time: Optional[int] = None,
        include_forming: bool = False,
    ) -> pd.DataFrame:
        """
        Fetch OHLC candles.

        By default the incomplete (forming) candle is dropped so indicators
        and signals only see closed bars. Pass include_forming=True to keep it.
        """
        if not self.is_connected or self._client is None:
            return pd.DataFrame()

        period = timeframe_to_seconds(timeframe)
        # Prefer working tick-based path; fall back to (often broken) candle APIs.
        # The whole probe chain is capped so a single slow/hanging method can
        # never make "Analyzing…" wait indefinitely — after this deadline we
        # give up and let the caller fall back to cached/demo data.
        try:
            raw = await asyncio.wait_for(
                self._fetch_raw_candles(asset, period, count + 1), timeout=15.0
            )
        except asyncio.TimeoutError:
            logger.warning(
                "Candle fetch for %s exceeded 15s overall deadline; falling back",
                asset,
            )
            raw = []
        df = self._to_dataframe(raw, count + 1)
        if df.empty:
            return df

        if not include_forming and len(df) > 0:
            df = self._drop_forming_candle(df, period)

        if len(df) > count:
            df = df.iloc[-count:].reset_index(drop=True)
        return df

    @staticmethod
    def _drop_forming_candle(df: pd.DataFrame, period: int) -> pd.DataFrame:
        """Remove the last bar if it is still open (not fully closed)."""
        if df is None or df.empty or "timestamp" not in df.columns:
            return df
        try:
            import time as _time

            now = int(_time.time())
            last_ts = df["timestamp"].iloc[-1]
            if hasattr(last_ts, "timestamp"):
                last_unix = int(last_ts.timestamp())
            else:
                last_unix = int(last_ts)
            # Candle is still forming if we are inside its period window
            if now < last_unix + period:
                return df.iloc[:-1].reset_index(drop=True)
        except Exception:
            pass
        return df

    async def _fetch_raw_candles(
        self, asset: str, period: int, count: int
    ) -> List[Any]:
        """
        Fetch OHLC data.

        BinaryOptionsToolsV2 candle endpoints (get_candles / history /
        get_candles_live) frequently return None or [] on current builds.
        get_ticks works reliably, so we build candles from ticks first.

        Each attempt gets a short timeout (8s, not 20-25s) so a hanging
        method can't eat the whole request, and once a method is confirmed
        to work we remember it and try it first on every later call instead
        of re-probing all of them in order — this was the main cause of
        slow "Analyzing…" responses.
        """
        client = self._client
        assert client is not None
        ATTEMPT_TIMEOUT = 8.0

        async def try_ticks() -> Optional[List[Any]]:
            if not hasattr(client, "get_ticks"):
                return None
            lookback = max(count * period + period * 2, 300)
            lookback = min(lookback, 7200)
            res = client.get_ticks(asset, lookback)
            if asyncio.iscoroutine(res):
                res = await asyncio.wait_for(res, timeout=ATTEMPT_TIMEOUT)
            if res:
                candles = self._ticks_to_ohlc(list(res), period)
                if candles:
                    logger.info(
                        "Built %d candles from %d ticks for %s (period=%ss)",
                        len(candles), len(res), asset, period,
                    )
                    return candles[-count:]
            return None

        async def try_get_candles() -> Optional[List[Any]]:
            if not hasattr(client, "get_candles"):
                return None
            offset = max(count, 30)
            res = client.get_candles(asset, period, offset)
            if asyncio.iscoroutine(res):
                res = await asyncio.wait_for(res, timeout=ATTEMPT_TIMEOUT)
            if res:
                return list(res) if not isinstance(res, dict) else [res]
            return None

        async def try_history() -> Optional[List[Any]]:
            if not hasattr(client, "history"):
                return None
            res = client.history(asset, period)
            if asyncio.iscoroutine(res):
                res = await asyncio.wait_for(res, timeout=ATTEMPT_TIMEOUT)
            if isinstance(res, str):
                import json
                res = json.loads(res)
            return list(res) if res else None

        async def try_candles() -> Optional[List[Any]]:
            if not hasattr(client, "candles"):
                return None
            res = client.candles(asset, period)
            if asyncio.iscoroutine(res):
                res = await asyncio.wait_for(res, timeout=ATTEMPT_TIMEOUT)
            return list(res) if res else None

        async def try_candles_live() -> Optional[List[Any]]:
            if not hasattr(client, "get_candles_live"):
                return None
            hours = max(0.25, (count * period) / 3600.0)
            gen = client.get_candles_live(asset, period=period, hours=hours, max_rows=count)
            if asyncio.iscoroutine(gen):
                gen = await asyncio.wait_for(gen, timeout=ATTEMPT_TIMEOUT)
            async for closed, _forming in gen:
                if closed:
                    return list(closed)[-count:]
                break
            return None

        async def try_candles_advanced() -> Optional[List[Any]]:
            if not hasattr(client, "get_candles_advanced"):
                return None
            import time as _time
            now = int(_time.time())
            for args in ((asset, period, now, count), (asset, period, count, now)):
                try:
                    res = client.get_candles_advanced(*args)
                    if asyncio.iscoroutine(res):
                        res = await asyncio.wait_for(res, timeout=ATTEMPT_TIMEOUT)
                    if res:
                        return list(res)[-count:]
                except TypeError:
                    continue
            return None

        attempts = {
            "ticks": try_ticks,
            "get_candles": try_get_candles,
            "history": try_history,
            "candles": try_candles,
            "candles_live": try_candles_live,
            "candles_advanced": try_candles_advanced,
        }

        # Try the method that worked last time first.
        order = list(attempts.keys())
        if self._working_candle_method in order:
            order.remove(self._working_candle_method)
            order.insert(0, self._working_candle_method)

        for name in order:
            try:
                result = await attempts[name]()
            except Exception as e:
                logger.debug("%s failed: %s", name, e)
                continue
            if result:
                self._working_candle_method = name
                return result

        return []

    @staticmethod
    def _ticks_to_ohlc(ticks: List[Any], period: int) -> List[Dict[str, Any]]:
        """
        Convert raw ticks into OHLC candle dicts.

        Tick shapes supported:
          [timestamp, price]
          (timestamp, price)
          {"time"|"timestamp": ts, "price"|"close"|"value": price}
        """
        from collections import defaultdict

        buckets: Dict[int, List[float]] = defaultdict(list)

        for item in ticks:
            ts: Optional[float] = None
            price: Optional[float] = None
            try:
                if isinstance(item, (list, tuple)) and len(item) >= 2:
                    ts = float(item[0])
                    price = float(item[1])
                elif isinstance(item, dict):
                    ts = item.get("time") or item.get("timestamp") or item.get("t")
                    price = (
                        item.get("price")
                        or item.get("close")
                        or item.get("value")
                        or item.get("p")
                    )
                    if ts is not None:
                        ts = float(ts)
                    if price is not None:
                        price = float(price)
            except (TypeError, ValueError):
                continue

            if ts is None or price is None:
                continue
            if ts > 1e12:  # milliseconds
                ts /= 1000.0

            bucket = int(ts) // period * period
            buckets[bucket].append(price)

        candles: List[Dict[str, Any]] = []
        for bucket_ts in sorted(buckets.keys()):
            prices = buckets[bucket_ts]
            if not prices:
                continue
            candles.append(
                {
                    "time": bucket_ts,
                    "open": prices[0],
                    "high": max(prices),
                    "low": min(prices),
                    "close": prices[-1],
                    "volume": len(prices),
                }
            )
        return candles

    @staticmethod
    def _to_dataframe(raw: List[Any], count: int) -> pd.DataFrame:
        if not raw:
            return pd.DataFrame(
                columns=["timestamp", "open", "high", "low", "close", "volume"]
            )

        rows = []
        for c in raw:
            if isinstance(c, (list, tuple)) and len(c) >= 5:
                # [time, open, close, high, low] or similar
                ts, o, cl, h, l = c[0], c[1], c[2], c[3], c[4]
                v = c[5] if len(c) > 5 else 0
            elif isinstance(c, dict):
                ts = c.get("time") or c.get("timestamp") or c.get("t")
                o = c.get("open", c.get("o"))
                h = c.get("high", c.get("h"))
                l = c.get("low", c.get("l"))
                cl = c.get("close", c.get("c"))
                v = c.get("volume", c.get("v", 0))
            else:
                continue

            try:
                ts_f = float(ts)
                if ts_f > 1e12:
                    ts_f /= 1000.0
                dt = datetime.fromtimestamp(ts_f, tz=timezone.utc)
            except Exception:
                dt = datetime.now(timezone.utc)

            try:
                rows.append(
                    {
                        "timestamp": dt,
                        "open": float(o),
                        "high": float(h),
                        "low": float(l),
                        "close": float(cl),
                        "volume": float(v or 0),
                    }
                )
            except Exception:
                continue

        if not rows:
            return pd.DataFrame(
                columns=["timestamp", "open", "high", "low", "close", "volume"]
            )

        df = pd.DataFrame(rows)
        df = df.sort_values("timestamp").drop_duplicates(subset=["timestamp"], keep="last")
        if len(df) > count:
            df = df.iloc[-count:]
        return df.reset_index(drop=True)

    async def disconnect(self) -> None:
        self._connected = False
        self._authenticated = False
        if self._client is not None:
            for name in ("disconnect", "close", "shutdown"):
                if hasattr(self._client, name):
                    try:
                        res = getattr(self._client, name)()
                        if asyncio.iscoroutine(res):
                            await res
                    except Exception:
                        pass
                    break
        self._client = None
        logger.info("BotV2 disconnected")

    async def close(self) -> None:
        await self.disconnect()

    # ------------------------------------------------------------------
    # Real-time trade execution
    # ------------------------------------------------------------------

    async def place_trade(
        self,
        asset: str,
        direction: str,
        amount: float,
        duration: int = 60,
    ) -> Dict[str, Any]:
        """
        Place a binary options trade.

        direction: "CALL" / "BUY" / "call"  → buy (price up)
                   "PUT"  / "SELL" / "put"  → sell (price down)
        amount: stake in account currency
        duration: expiry in seconds (e.g. 60)

        Returns dict with keys: success, order_id, raw, error
        """
        if not self.is_connected or self._client is None:
            return {"success": False, "error": "Not connected", "order_id": None}

        direction = (direction or "").strip().upper()
        is_call = direction in ("CALL", "BUY", "CALLS")
        is_put = direction in ("PUT", "SELL", "PUTS")
        if not is_call and not is_put:
            return {
                "success": False,
                "error": f"Invalid direction: {direction}",
                "order_id": None,
            }

        client = self._client
        amount = float(amount)
        duration = int(duration)

        # Clamp against settings if present
        min_amt = float(getattr(self.settings, "MIN_TRADE_AMOUNT", 1.0))
        max_amt = float(getattr(self.settings, "MAX_TRADE_AMOUNT", 50.0))
        amount = max(min_amt, min(max_amt, amount))

        try:
            if is_call:
                # Prefer buy() then trade()
                if hasattr(client, "buy"):
                    res = client.buy(asset, amount, duration)
                elif hasattr(client, "trade"):
                    res = client.trade(asset, "call", amount, duration)
                else:
                    return {"success": False, "error": "No buy/trade method", "order_id": None}
            else:
                if hasattr(client, "sell"):
                    res = client.sell(asset, amount, duration)
                elif hasattr(client, "trade"):
                    res = client.trade(asset, "put", amount, duration)
                else:
                    return {"success": False, "error": "No sell/trade method", "order_id": None}

            if asyncio.iscoroutine(res):
                res = await asyncio.wait_for(res, timeout=30.0)

            order_id = None
            raw = res
            if isinstance(res, (list, tuple)) and len(res) >= 1:
                order_id = res[0]
                raw = res[1] if len(res) > 1 else res[0]
            elif isinstance(res, dict):
                order_id = res.get("id") or res.get("order_id") or res.get("trade_id")
            elif isinstance(res, str):
                order_id = res

            logger.info(
                "Trade placed: %s %s amount=%.2f duration=%ss → order_id=%s",
                direction,
                asset,
                amount,
                duration,
                order_id,
            )
            return {
                "success": True,
                "order_id": order_id,
                "raw": raw,
                "direction": direction,
                "asset": asset,
                "amount": amount,
                "duration": duration,
                "error": None,
            }
        except Exception as e:
            logger.exception("place_trade failed: %s", e)
            return {"success": False, "error": str(e), "order_id": None}

    async def check_win(
        self, order_id: str, timeout_seconds: int = 90
    ) -> Dict[str, Any]:
        """
        Wait for trade result.

        Returns: {success, result: "win"|"loss"|"draw"|None, raw, error}
        """
        if not self.is_connected or self._client is None:
            return {"success": False, "result": None, "error": "Not connected"}

        if not hasattr(self._client, "check_win"):
            return {"success": False, "result": None, "error": "check_win not available"}

        try:
            res = self._client.check_win(order_id)
            if asyncio.iscoroutine(res):
                res = await asyncio.wait_for(res, timeout=float(timeout_seconds))

            result = None
            if isinstance(res, dict):
                result = (
                    res.get("result")
                    or res.get("win")
                    or res.get("status")
                )
                if result is True or result == 1:
                    result = "win"
                elif result is False or result == -1:
                    result = "loss"
                elif result == 0:
                    result = "draw"
            elif isinstance(res, str):
                result = res.lower()
            elif isinstance(res, bool):
                result = "win" if res else "loss"

            logger.info("Trade %s result: %s", order_id, result)
            return {"success": True, "result": result, "raw": res, "error": None}
        except Exception as e:
            logger.warning("check_win failed for %s: %s", order_id, e)
            return {"success": False, "result": None, "error": str(e)}

    async def get_balance(self) -> Optional[float]:
        return await self._try_balance()

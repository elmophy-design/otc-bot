"""
BinaryOptionsTools-v2 adapter.

Optional live backend. Install with:
  pip install BinaryOptionsToolsV2

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
    """Adapter for BinaryOptionsToolsV2 PocketOptionAsync."""

    def __init__(self, settings: Any):
        self.settings = settings
        self.demo_mode = getattr(settings, "DEMO_MODE", True)
        self._client: Any = None
        self._connected = False
        self._authenticated = False
        self._ssid_raw = getattr(settings, "POCKETOPTION_SSID", None) or ""
        self._ssid_for_lib = self._normalize_ssid(self._ssid_raw)

    @staticmethod
    def _normalize_ssid(raw: str) -> str:
        raw = (raw or "").strip()
        if not raw:
            return ""
        try:
            parsed = parse_ssid(raw)
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
            logger.warning("BinaryOptionsToolsV2 not installed (%s)", _import_error)
            return False

        if not self._ssid_for_lib:
            logger.info("No SSID – BotV2Client cannot connect")
            return False

        try:
            self._client = _PocketOptionAsync(ssid=self._ssid_for_lib)
            if hasattr(self._client, "connect") and callable(self._client.connect):
                res = self._client.connect()
                if asyncio.iscoroutine(res):
                    await res
            else:
                await asyncio.sleep(2.0)

            bal = await self._try_balance()
            self._connected = True
            self._authenticated = bal is not None or True
            logger.info("✅ BotV2 connected (balance=%s)", bal if bal is not None else "n/a")
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

    async def get_balance(self) -> Optional[float]:
        return await self._try_balance()

    async def get_candles(
        self,
        asset: str,
        timeframe: Union[str, int] = "1m",
        count: int = 200,
        end_time: Optional[int] = None,
    ) -> pd.DataFrame:
        if not self.is_connected or self._client is None:
            return pd.DataFrame()
        period = timeframe_to_seconds(timeframe)
        raw = await self._fetch_raw_candles(asset, period, count)
        return self._to_dataframe(raw, count)

    async def _fetch_raw_candles(self, asset: str, period: int, count: int) -> List[Any]:
        client = self._client
        assert client is not None
        min_bars = max(50, min(count, 100))
        best: List[Any] = []

        def _as_list(res: Any) -> List[Any]:
            if res is None:
                return []
            if isinstance(res, dict):
                return [res]
            if isinstance(res, str):
                import json
                try:
                    parsed = json.loads(res)
                    return list(parsed) if isinstance(parsed, (list, tuple)) else [parsed]
                except Exception:
                    return []
            try:
                return list(res)
            except Exception:
                return []

        if hasattr(client, "get_candles"):
            offsets = [
                max(count * period, 3600),
                max(count * period, 7200),
                max(count * period, 14400),
                max(count * period, 28800),
                9000,
                18000,
            ]
            seen = set()
            uniq_offsets = []
            for o in offsets:
                if o not in seen:
                    seen.add(o)
                    uniq_offsets.append(o)

            for offset in uniq_offsets:
                try:
                    res = client.get_candles(asset, period, offset)
                    if asyncio.iscoroutine(res):
                        res = await asyncio.wait_for(res, timeout=20.0)
                    rows = _as_list(res)
                    if len(rows) > len(best):
                        best = rows
                    if len(best) >= min_bars:
                        return best
                except Exception as e:
                    logger.debug("get_candles offset=%s failed: %s", offset, e)

        if hasattr(client, "get_candles_advanced"):
            import time as _time
            for offset in (max(count * period, 7200), 14400, 28800):
                try:
                    res = client.get_candles_advanced(asset, period, offset, int(_time.time()))
                    if asyncio.iscoroutine(res):
                        res = await asyncio.wait_for(res, timeout=20.0)
                    rows = _as_list(res)
                    if len(rows) > len(best):
                        best = rows
                    if len(best) >= min_bars:
                        return best
                except Exception as e:
                    logger.debug("get_candles_advanced failed: %s", e)

        if hasattr(client, "history"):
            try:
                res = client.history(asset, period)
                if asyncio.iscoroutine(res):
                    res = await asyncio.wait_for(res, timeout=20.0)
                rows = _as_list(res)
                if len(rows) > len(best):
                    best = rows
            except Exception as e:
                logger.debug("history failed: %s", e)

        if hasattr(client, "candles"):
            try:
                res = client.candles(asset, period)
                if asyncio.iscoroutine(res):
                    res = await asyncio.wait_for(res, timeout=20.0)
                rows = _as_list(res)
                if len(rows) > len(best):
                    best = rows
            except Exception as e:
                logger.debug("candles() failed: %s", e)

        if hasattr(client, "get_candles_live") and len(best) < min_bars:
            try:
                hours = max(2.0, (count * period) / 3600.0)
                gen = client.get_candles_live(
                    asset, period=period, hours=hours, max_rows=max(count, 100)
                )
                if asyncio.iscoroutine(gen):
                    gen = await gen
                async for closed, _forming in gen:
                    rows = _as_list(closed)
                    if len(rows) > len(best):
                        best = rows
                    break
            except Exception as e:
                logger.debug("get_candles_live failed: %s", e)

        if best:
            logger.info(
                "Candle fetch for %s period=%ss: %d rows (target >=%d)",
                asset, period, len(best), min_bars,
            )
        else:
            logger.warning("Candle fetch for %s returned 0 rows", asset)
        return best

    @staticmethod
    def _to_dataframe(raw: List[Any], count: int) -> pd.DataFrame:
        if not raw:
            return pd.DataFrame(
                columns=["timestamp", "open", "high", "low", "close", "volume"]
            )

        rows = []
        for c in raw:
            if isinstance(c, (list, tuple)) and len(c) >= 5:
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

    async def place_trade(
        self,
        asset: str,
        direction: str,
        amount: float,
        duration: int = 60,
    ) -> dict:
        """Place a binary trade. Returns dict with success/error keys for handlers."""
        if not self.is_connected or self._client is None:
            return {
                "success": False,
                "ok": False,
                "trade_id": None,
                "error": "BotV2Client is not connected",
                "asset": asset,
                "direction": (direction or "").upper(),
                "amount": float(amount),
                "duration": int(duration),
            }

        direction_l = (direction or "").strip().lower()
        if direction_l in ("call", "buy", "up"):
            method_name = "buy"
        elif direction_l in ("put", "sell", "down"):
            method_name = "sell"
        else:
            return {
                "success": False,
                "ok": False,
                "trade_id": None,
                "error": f"Invalid direction: {direction}",
                "asset": asset,
                "direction": (direction or "").upper(),
                "amount": float(amount),
                "duration": int(duration),
            }

        client = self._client
        method = getattr(client, method_name, None)
        if method is None:
            return {
                "success": False,
                "ok": False,
                "trade_id": None,
                "error": f"Underlying client has no '{method_name}' method",
                "asset": asset,
                "direction": direction_l.upper(),
                "amount": float(amount),
                "duration": int(duration),
            }

        try:
            res = method(asset, float(amount), int(duration))
            if asyncio.iscoroutine(res):
                res = await asyncio.wait_for(res, timeout=30.0)
        except Exception as e:
            logger.exception("place_trade failed for %s %s", asset, direction_l)
            return {
                "success": False,
                "ok": False,
                "trade_id": None,
                "error": str(e) or repr(e),
                "asset": asset,
                "direction": direction_l.upper(),
                "amount": float(amount),
                "duration": int(duration),
            }

        trade_id = None
        deal = res
        if isinstance(res, (tuple, list)) and len(res) >= 1:
            trade_id = res[0]
            deal = res[1] if len(res) > 1 else res[0]
        elif isinstance(res, dict):
            trade_id = res.get("id") or res.get("trade_id") or res.get("order_id")

        logger.info(
            "Trade placed: asset=%s dir=%s amount=%s duration=%ss id=%s",
            asset, direction_l, amount, duration, trade_id,
        )
        return {
            "success": True,
            "ok": True,
            "trade_id": str(trade_id) if trade_id is not None else None,
            "deal": deal,
            "asset": asset,
            "direction": direction_l.upper(),
            "amount": float(amount),
            "duration": int(duration),
            "error": None,
        }

    async def place_order(self, *args, **kwargs):
        return await self.place_trade(*args, **kwargs)

    async def open_trade(self, *args, **kwargs):
        return await self.place_trade(*args, **kwargs)

    async def check_win(self, trade_id: str, timeout: Optional[int] = None) -> dict:
        """Check and normalize the broker settlement for a trade."""
        if not self.is_connected or self._client is None:
            raise RuntimeError("BotV2Client is not connected")

        client = self._client
        if not hasattr(client, "check_win"):
            raise AttributeError("Underlying client has no check_win")

        res = client.check_win(trade_id)
        if asyncio.iscoroutine(res):
            res = await asyncio.wait_for(
                res,
                timeout=(timeout or 120),
            )

        normalized = self._normalize_settlement(res)

        logger.info(
            "Trade settlement: trade_id=%s result=%s profit=%s raw_result=%s",
            trade_id,
            normalized.get("result"),
            normalized.get("profit"),
            normalized.get("raw_result"),
        )

        return normalized

    @staticmethod
    def _normalize_settlement(res: Any) -> dict:
        """Normalize broker settlement data.

        BinaryOptionsToolsV2 v0.2.14 uses profit as the settlement
        signal:

        profit > 0  -> WIN
        profit == 0 -> DRAW
        profit < 0  -> LOSS

        If an explicit result is also supplied, both sources must agree.
        Contradictory evidence is preserved as
        REQUIRES_RECONCILIATION.
        """

        if isinstance(res, dict):
            payload = res
        elif isinstance(res, bool):
            payload = {"win": res}
        elif isinstance(res, (int, float)):
            # Some broker versions return settlement profit directly.
            payload = {"profit": float(res)}
        else:
            payload = {"result": res}

        raw_result = (
            payload.get("result")
            or payload.get("outcome")
            or payload.get("status")
            or payload.get("trade_result")
            or payload.get("trade_outcome")
        )

        explicit_result = None

        if raw_result is not None:
            value = str(raw_result).strip().upper()

            if value in {
                "WIN",
                "WON",
                "PROFIT",
                "SUCCESS",
                "TRUE",
            }:
                explicit_result = "WIN"

            elif value in {
                "LOSS",
                "LOST",
                "LOSE",
                "FAILED",
                "FAIL",
                "FALSE",
            }:
                explicit_result = "LOSS"

            elif value in {
                "DRAW",
                "TIE",
                "REFUND",
                "REFUNDED",
                "BREAKEVEN",
                "BREAK_EVEN",
            }:
                explicit_result = "DRAW"

        if explicit_result is None:
            for key in ("win", "won", "is_win"):
                if key in payload and isinstance(
                    payload[key],
                    bool,
                ):
                    explicit_result = (
                        "WIN"
                        if payload[key]
                        else "LOSS"
                    )
                    break

        numeric_profit = None

        for key in (
            "profit",
            "profit_loss",
            "pnl",
            "net_profit",
        ):
            value = payload.get(key)

            if value is None:
                continue

            try:
                numeric_profit = float(value)
                break
            except (TypeError, ValueError):
                continue

        profit_result = None

        if numeric_profit is not None:
            if numeric_profit > 0:
                profit_result = "WIN"
            elif numeric_profit < 0:
                profit_result = "LOSS"
            else:
                profit_result = "DRAW"

        if (
            explicit_result is not None
            and profit_result is not None
            and explicit_result != profit_result
        ):
            return {
                "result": "REQUIRES_RECONCILIATION",
                "raw_result": raw_result,
                "profit": numeric_profit,
                "settlement_conflict": True,
                "expected_result": profit_result,
                "raw": payload,
            }

        if explicit_result is not None:
            return {
                "result": explicit_result,
                "raw_result": raw_result,
                "profit": numeric_profit,
                "settlement_conflict": False,
                "raw": payload,
            }

        if profit_result is not None:
            return {
                "result": profit_result,
                "raw_result": raw_result,
                "profit": numeric_profit,
                "settlement_conflict": False,
                "raw": payload,
            }

        return {
            "result": "UNKNOWN",
            "raw_result": raw_result,
            "profit": None,
            "settlement_conflict": False,
            "raw": payload,
        }

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
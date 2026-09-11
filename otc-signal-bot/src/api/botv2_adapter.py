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
    ) -> pd.DataFrame:
        if not self.is_connected or self._client is None:
            return pd.DataFrame()

        period = timeframe_to_seconds(timeframe)
        # Prefer dedicated candle APIs; fall back to history / ticks
        raw = await self._fetch_raw_candles(asset, period, count)
        return self._to_dataframe(raw, count)

    async def _fetch_raw_candles(
        self, asset: str, period: int, count: int
    ) -> List[Any]:
        client = self._client
        assert client is not None

        # 1) get_candles(asset, period, offset) — common BOTv2 signature
        if hasattr(client, "get_candles"):
            try:
                offset = max(count * period, 9000)
                res = client.get_candles(asset, period, offset)
                if asyncio.iscoroutine(res):
                    res = await asyncio.wait_for(res, timeout=20.0)
                if res:
                    return list(res) if not isinstance(res, dict) else [res]
            except Exception as e:
                logger.debug("get_candles failed: %s", e)

        # 2) history(asset, period)
        if hasattr(client, "history"):
            try:
                res = client.history(asset, period)
                if asyncio.iscoroutine(res):
                    res = await asyncio.wait_for(res, timeout=20.0)
                if isinstance(res, str):
                    import json

                    res = json.loads(res)
                if res:
                    return list(res)
            except Exception as e:
                logger.debug("history failed: %s", e)

        # 3) candles(asset, period) — deprecated path in some versions
        if hasattr(client, "candles"):
            try:
                res = client.candles(asset, period)
                if asyncio.iscoroutine(res):
                    res = await asyncio.wait_for(res, timeout=20.0)
                if res:
                    return list(res)
            except Exception as e:
                logger.debug("candles() failed: %s", e)

        # 4) get_candles_live — take first snapshot of closed bars
        if hasattr(client, "get_candles_live"):
            try:
                gen = client.get_candles_live(
                    asset, period=period, hours=max(1.0, count * period / 3600.0), max_rows=count
                )
                if asyncio.iscoroutine(gen):
                    gen = await gen
                # async iterator
                async for closed, _forming in gen:
                    if closed:
                        return list(closed)[-count:]
                    break
            except Exception as e:
                logger.debug("get_candles_live failed: %s", e)

        return []

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

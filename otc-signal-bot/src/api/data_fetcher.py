"""Market Data Fetcher with Caching + Professional Demo Mode"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

import numpy as np
import pandas as pd

from ..utils.logger import get_logger

logger = get_logger(__name__)


# Reasonable base prices for common OTC assets (used only in demo mode)
_ASSET_BASE_PRICES: Dict[str, float] = {
    "EURUSD_otc": 1.0850,
    "GBPUSD_otc": 1.2650,
    "USDJPY_otc": 149.50,
    "AUDUSD_otc": 0.6550,
    "USDCAD_otc": 1.3650,
    "NZDUSD_otc": 0.6050,
    "XAUUSD_otc": 2350.0,
    "XAGUSD_otc": 28.50,
    "BTCUSD_otc": 62000.0,
    "ETHUSD_otc": 3200.0,
    "LTCUSD_otc": 75.0,
    "XRPUSD_otc": 0.55,
}


class MarketDataFetcher:
    """
    Professional data fetcher.

    - Prefers live data from the broker client when available.
    - In DEMO_MODE (or when live data is unavailable) generates realistic
      synthetic OHLCV so the signal engine and Telegram bot remain fully testable.
    - Results are cached for a short TTL to avoid hammering the source.
    """

    def __init__(self, client: Any = None, demo_mode: bool = True):
        self.client = client
        self.demo_mode = demo_mode
        self.cache: Dict[str, tuple] = {}
        self.cache_ttl = 45  # seconds

    async def get_historical_data(
        self,
        asset: str,
        timeframe: str = "1m",
        count: int = 200,
    ) -> pd.DataFrame:
        """Return OHLCV DataFrame for the given asset."""
        cache_key = f"{asset}_{timeframe}_{count}"

        # Cache hit?
        if cache_key in self.cache:
            data, ts = self.cache[cache_key]
            if (datetime.now(timezone.utc) - ts).total_seconds() < self.cache_ttl:
                logger.debug("Cache hit for %s", asset)
                return data.copy()

        # Try live path first (works with demo SSID too when client is connected)
        df: Optional[pd.DataFrame] = None
        if self.client is not None:
            try:
                df = await self._fetch_live(asset, timeframe, count)
            except Exception as exc:
                logger.warning(
                    "Live fetch failed for %s (%s). Falling back to synthetic data.",
                    asset,
                    exc,
                )

        # Demo / fallback path
        if df is None or df.empty:
            if not self.demo_mode:
                raise RuntimeError(
                    f"No market data available for {asset} and DEMO_MODE is disabled."
                )
            logger.info("Using demo OHLCV for %s (%s, n=%d)", asset, timeframe, count)
            df = self._generate_demo_ohlcv(asset, timeframe, count)

        # Normalize & cache
        df = self._normalize(df)
        self.cache[cache_key] = (df.copy(), datetime.now(timezone.utc))
        return df

    async def _fetch_live(
        self, asset: str, timeframe: str, count: int
    ) -> Optional[pd.DataFrame]:
        """
        Fetch candles from the live PocketOption client when connected.
        Returns None on failure so the demo path can activate.
        """
        if self.client is None:
            return None
        if not getattr(self.client, "is_connected", False):
            logger.debug("Client not connected – skip live fetch")
            return None
        try:
            if hasattr(self.client, "get_candles"):
                df = await self.client.get_candles(asset, timeframe=timeframe, count=count)
                if df is not None and not df.empty:
                    logger.info("Live candles: %s rows for %s", len(df), asset)
                    return df
            return None
        except Exception as e:
            logger.warning("Live candle fetch failed for %s: %s", asset, e)
            return None

    def _generate_demo_ohlcv(
        self, asset: str, timeframe: str, count: int
    ) -> pd.DataFrame:
        """
        Generate realistic synthetic OHLCV.

        Uses a seeded RNG derived from the asset name so the same asset
        produces consistent (but evolving) data across calls within the
        same process, while different assets look distinct.
        """
        base = _ASSET_BASE_PRICES.get(asset, 100.0)
        # Seed from asset + current minute so data slowly evolves
        seed = hash(asset) % (2**32) + int(datetime.now().timestamp() // 60)
        rng = np.random.default_rng(seed % (2**32))

        # Per-bar relative volatility (keeps numbers stable across asset classes)
        if "BTC" in asset or "ETH" in asset:
            rel_vol = 0.0035
        elif "XAU" in asset or "XAG" in asset:
            rel_vol = 0.0012
        elif "JPY" in asset:
            rel_vol = 0.0007
        else:
            rel_vol = 0.0005

        # Additive random-walk on price (more stable than exp of cumulative returns)
        shocks = rng.normal(0, base * rel_vol, count)
        burst_idx = rng.choice(count, size=max(2, count // 30), replace=False)
        shocks[burst_idx] *= rng.uniform(2.0, 3.5, size=len(burst_idx))

        close = base + np.cumsum(shocks)
        # Prevent non-positive prices
        close = np.maximum(close, base * 0.2)
        close = pd.Series(close)

        # Intrabar high/low
        wick = np.abs(rng.normal(0, base * rel_vol * 0.8, count))
        high = (close + wick).values
        low = (close - wick).values
        open_ = close.shift(1).fillna(close.iloc[0]).values
        # Ensure open is between low/high
        open_ = np.clip(open_, low, high)

        volume = rng.integers(80, 1200, count).astype(float)

        # Timestamps (newest last)
        tf_minutes = self._timeframe_to_minutes(timeframe)
        now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
        times = [now - timedelta(minutes=tf_minutes * (count - i - 1)) for i in range(count)]

        df = pd.DataFrame(
            {
                "timestamp": times,
                "open": open_,
                "high": high,
                "low": low,
                "close": close.values,
                "volume": volume,
            }
        )
        return df

    @staticmethod
    def _timeframe_to_minutes(tf: str) -> int:
        tf = (tf or "1m").lower().strip()
        if tf.endswith("m"):
            return max(1, int(tf[:-1] or 1))
        if tf.endswith("h"):
            return max(1, int(tf[:-1] or 1) * 60)
        if tf.endswith("d"):
            return max(1, int(tf[:-1] or 1) * 1440)
        return 1

    @staticmethod
    def _normalize(df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df.columns = [str(c).lower() for c in df.columns]
        required = {"open", "high", "low", "close"}
        if not required.issubset(df.columns):
            raise ValueError(f"OHLCV missing columns: {required - set(df.columns)}")
        # Ensure numeric
        for col in ("open", "high", "low", "close", "volume"):
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        df = df.dropna(subset=["open", "high", "low", "close"])
        return df.reset_index(drop=True)

    def clear_cache(self) -> None:
        self.cache.clear()
        logger.info("Market data cache cleared")

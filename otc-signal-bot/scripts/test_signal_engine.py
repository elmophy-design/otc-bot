#!/usr/bin/env python3
"""
Quick offline test of the multi-indicator SignalEngine.
Generates synthetic OHLCV data and prints the resulting signal.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import numpy as np
import pandas as pd

# Make src importable
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.signals.engine import SignalEngine  # noqa: E402


class DummySettings:
    MIN_CONFIDENCE = 65
    config = {
        "signals": {
            "technical": {
                "rsi_period": 14,
                "rsi_overbought": 70,
                "rsi_oversold": 30,
                "macd_fast": 12,
                "macd_slow": 26,
                "macd_signal": 9,
                "bb_period": 20,
                "bb_std": 2.0,
            },
            "confidence": {"min_required": 65},
        }
    }


def make_synthetic_df(
    n: int = 150,
    trend: str = "down",  # "up" | "down" | "sideways"
    seed: int = 42,
) -> pd.DataFrame:
    """Generate OHLCV that produces clearer short-term signals."""
    rng = np.random.default_rng(seed)
    t = np.arange(n)

    # Base path
    if trend == "up":
        # Gradual up then strong late push (oversold recovery style inverted)
        price = 100 + np.sin(t / 12) * 1.5 + t * 0.04
        # Strong final leg up so RSI/Stoch become overbought → PUT bias
        price[-15:] = price[-16] + np.linspace(0, 4.5, 15)
    elif trend == "down":
        price = 100 + np.sin(t / 12) * 1.5 - t * 0.04
        # Strong final leg down → oversold → CALL bias
        price[-15:] = price[-16] - np.linspace(0, 4.5, 15)
    else:
        price = 100 + np.sin(t / 8) * 2.0 + rng.normal(0, 0.15, n)

    noise = rng.normal(0, 0.12, n)
    close = pd.Series(price + noise)
    high = close + rng.uniform(0.08, 0.4, n)
    low = close - rng.uniform(0.08, 0.4, n)
    open_ = close.shift(1).fillna(close.iloc[0]) + rng.normal(0, 0.08, n)
    volume = rng.integers(200, 1500, n)

    return pd.DataFrame(
        {
            "open": open_.values,
            "high": high.values,
            "low": low.values,
            "close": close.values,
            "volume": volume,
        }
    )


async def run_test(trend: str) -> None:
    print(f"\n{'='*60}")
    print(f"Testing trend = {trend.upper()}")
    print("=" * 60)

    df = make_synthetic_df(trend=trend)
    engine = SignalEngine(DummySettings())

    signal = await engine.generate_signal(
        asset=f"TEST_{trend.upper()}_otc",
        timeframe="1m",
        candles=df,
    )

    print(f"Action     : {signal.get('action')}")
    print(f"Confidence : {signal.get('confidence')}")
    print(f"Reason     : {signal.get('reason')}")
    print(f"Entry      : {signal.get('entry_price')}")
    print(f"Votes      : {signal.get('votes')}")
    print(f"Snapshot   : {signal.get('indicator_snapshot')}")
    print(f"Timestamp  : {signal.get('timestamp')}")


async def main() -> None:
    for trend in ("down", "up", "sideways"):
        await run_test(trend)


if __name__ == "__main__":
    asyncio.run(main())

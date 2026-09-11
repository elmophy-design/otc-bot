"""Multi-timeframe helpers: resampling and higher-TF bias."""
from __future__ import annotations

from typing import Dict, Optional, Tuple

import pandas as pd

from .technical.indicators import TechnicalIndicators


# Map common bot timeframes to pandas offset aliases
_TF_TO_PANDAS = {
    "1m": "1min",
    "2m": "2min",
    "3m": "3min",
    "5m": "5min",
    "15m": "15min",
    "30m": "30min",
    "1h": "1h",
    "4h": "4h",
    "1d": "1D",
}

# Suggested higher timeframe for each base TF
DEFAULT_HTF_MAP = {
    "1m": "5m",
    "2m": "5m",
    "3m": "15m",
    "5m": "15m",
    "15m": "1h",
    "30m": "1h",
    "1h": "4h",
}


def timeframe_to_pandas(tf: str) -> str:
    tf = (tf or "1m").lower().strip()
    return _TF_TO_PANDAS.get(tf, "1min")


def suggest_higher_tf(tf: str) -> str:
    return DEFAULT_HTF_MAP.get((tf or "1m").lower().strip(), "5m")


def resample_ohlcv(df: pd.DataFrame, target_tf: str) -> pd.DataFrame:
    """
    Resample OHLCV to a higher timeframe.
    Expects columns: open, high, low, close (volume optional).
    Uses a DatetimeIndex when a timestamp column is present; otherwise
    synthesizes one assuming 1-minute bars.
    """
    data = df.copy()
    data.columns = [str(c).lower() for c in data.columns]

    if "timestamp" in data.columns:
        data["timestamp"] = pd.to_datetime(data["timestamp"], utc=True, errors="coerce")
        data = data.dropna(subset=["timestamp"]).set_index("timestamp")
    elif not isinstance(data.index, pd.DatetimeIndex):
        # Assume 1-minute bars ending now
        n = len(data)
        idx = pd.date_range(end=pd.Timestamp.now(tz='UTC'), periods=n, freq="1min")
        data.index = idx

    rule = timeframe_to_pandas(target_tf)
    agg = {
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
    }
    if "volume" in data.columns:
        agg["volume"] = "sum"

    resampled = data.resample(rule).agg(agg).dropna(subset=["open", "high", "low", "close"])
    return resampled.reset_index(drop=False).rename(columns={"index": "timestamp"})


def higher_tf_bias(
    htf_df: pd.DataFrame,
    rsi_period: int = 14,
    ema_fast: int = 9,
    ema_slow: int = 21,
) -> Dict:
    """
    Compute a simple higher-timeframe bias.

    Returns:
      {
        "bias": "BULLISH" | "BEARISH" | "NEUTRAL",
        "score": -2..+2,
        "rsi": float,
        "ema_fast": float,
        "ema_slow": float,
      }
    """
    if htf_df is None or len(htf_df) < max(ema_slow, rsi_period) + 2:
        return {"bias": "NEUTRAL", "score": 0, "rsi": 50.0, "ema_fast": 0.0, "ema_slow": 0.0}

    df = htf_df.copy()
    df.columns = [str(c).lower() for c in df.columns]
    close = df["close"]

    rsi = TechnicalIndicators.rsi(close, rsi_period)
    ema_f = TechnicalIndicators.ema(close, ema_fast)
    ema_s = TechnicalIndicators.ema(close, ema_slow)

    last_rsi = float(rsi.iloc[-1]) if not pd.isna(rsi.iloc[-1]) else 50.0
    last_ef = float(ema_f.iloc[-1])
    last_es = float(ema_s.iloc[-1])
    last_close = float(close.iloc[-1])

    score = 0
    # EMA structure
    if last_ef > last_es and last_close > last_ef:
        score += 1
    elif last_ef < last_es and last_close < last_ef:
        score -= 1
    # RSI regime
    if last_rsi >= 55:
        score += 1
    elif last_rsi <= 45:
        score -= 1

    if score >= 1:
        bias = "BULLISH"
    elif score <= -1:
        bias = "BEARISH"
    else:
        bias = "NEUTRAL"

    return {
        "bias": bias,
        "score": score,
        "rsi": round(last_rsi, 2),
        "ema_fast": round(last_ef, 5),
        "ema_slow": round(last_es, 5),
    }

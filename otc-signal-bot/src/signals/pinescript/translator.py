"""
PineScript-inspired helpers.

These are NOT a full Pine → Python compiler. They provide familiar
Pine-style building blocks (crossover, crossunder, rising, falling,
strategy.entry style votes) implemented on pandas Series so you can
port common TradingView logic quickly.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

import numpy as np
import pandas as pd


class PineHelper:
    """Familiar Pine-like operators on pandas Series."""

    @staticmethod
    def crossover(a: pd.Series, b: pd.Series) -> pd.Series:
        """True when a crosses above b (Pine: ta.crossover)."""
        return (a > b) & (a.shift(1) <= b.shift(1))

    @staticmethod
    def crossunder(a: pd.Series, b: pd.Series) -> pd.Series:
        """True when a crosses below b (Pine: ta.crossunder)."""
        return (a < b) & (a.shift(1) >= b.shift(1))

    @staticmethod
    def rising(series: pd.Series, length: int = 1) -> pd.Series:
        return series > series.shift(length)

    @staticmethod
    def falling(series: pd.Series, length: int = 1) -> pd.Series:
        return series < series.shift(length)

    @staticmethod
    def sma(series: pd.Series, length: int) -> pd.Series:
        return series.rolling(length, min_periods=length).mean()

    @staticmethod
    def ema(series: pd.Series, length: int) -> pd.Series:
        return series.ewm(span=length, adjust=False).mean()

    @staticmethod
    def rsi(series: pd.Series, length: int = 14) -> pd.Series:
        delta = series.diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)
        avg_gain = gain.ewm(alpha=1 / length, min_periods=length, adjust=False).mean()
        avg_loss = loss.ewm(alpha=1 / length, min_periods=length, adjust=False).mean()
        rs = avg_gain / avg_loss.replace(0, np.nan)
        return 100 - (100 / (1 + rs))

    @staticmethod
    def macd(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
        line = PineHelper.ema(series, fast) - PineHelper.ema(series, slow)
        sig = PineHelper.ema(line, signal)
        hist = line - sig
        return line, sig, hist

    @staticmethod
    def highest(series: pd.Series, length: int) -> pd.Series:
        return series.rolling(length, min_periods=length).max()

    @staticmethod
    def lowest(series: pd.Series, length: int) -> pd.Series:
        return series.rolling(length, min_periods=length).min()

    @staticmethod
    def valuewhen(condition: pd.Series, source: pd.Series, occurrence: int = 0) -> pd.Series:
        """Simplified valuewhen – last value of source where condition was true."""
        out = pd.Series(np.nan, index=source.index)
        vals = source.where(condition)
        # forward-fill last true values
        filled = vals.ffill()
        return filled


def pine_strategy_vote(df: pd.DataFrame, style: str = "rsi_macd") -> Dict[str, Any]:
    """
    Evaluate a small set of classic Pine-style strategies and return a vote.

    Styles:
      - rsi_macd: RSI exit of oversold/overbought + MACD hist direction
      - ema_cross: EMA 9/21 crossover
      - supertrend_lite: close vs ATR-based bands (lite)
    """
    df = df.copy()
    df.columns = [str(c).lower() for c in df.columns]
    close = df["close"]
    high = df["high"]
    low = df["low"]
    ph = PineHelper()

    action = "NEUTRAL"
    strength = 0.0
    reason = "no pine setup"

    if style == "ema_cross":
        e9 = ph.ema(close, 9)
        e21 = ph.ema(close, 21)
        if bool(ph.crossover(e9, e21).iloc[-1]):
            action, strength, reason = "CALL", 0.75, "Pine EMA 9/21 bullish crossover"
        elif bool(ph.crossunder(e9, e21).iloc[-1]):
            action, strength, reason = "PUT", 0.75, "Pine EMA 9/21 bearish crossover"
        elif e9.iloc[-1] > e21.iloc[-1] and close.iloc[-1] > e9.iloc[-1]:
            action, strength, reason = "CALL", 0.45, "Pine price above EMA stack"
        elif e9.iloc[-1] < e21.iloc[-1] and close.iloc[-1] < e9.iloc[-1]:
            action, strength, reason = "PUT", 0.45, "Pine price below EMA stack"

    elif style == "supertrend_lite":
        atr_period = 10
        mult = 2.0
        tr = pd.concat(
            [
                high - low,
                (high - close.shift(1)).abs(),
                (low - close.shift(1)).abs(),
            ],
            axis=1,
        ).max(axis=1)
        atr = tr.ewm(alpha=1 / atr_period, adjust=False).mean()
        hl2 = (high + low) / 2
        upper = hl2 + mult * atr
        lower = hl2 - mult * atr
        if close.iloc[-1] > upper.iloc[-1]:
            action, strength, reason = "CALL", 0.7, "Pine supertrend-lite bullish"
        elif close.iloc[-1] < lower.iloc[-1]:
            action, strength, reason = "PUT", 0.7, "Pine supertrend-lite bearish"

    else:  # rsi_macd default
        rsi = ph.rsi(close, 14)
        _, _, hist = ph.macd(close)
        r = float(rsi.iloc[-1]) if not pd.isna(rsi.iloc[-1]) else 50.0
        h = float(hist.iloc[-1]) if not pd.isna(hist.iloc[-1]) else 0.0
        h_prev = float(hist.iloc[-2]) if len(hist) > 1 and not pd.isna(hist.iloc[-2]) else 0.0
        if r < 30 and h > h_prev:
            action, strength, reason = "CALL", 0.8, f"Pine RSI oversold ({r:.1f}) + MACD rising"
        elif r > 70 and h < h_prev:
            action, strength, reason = "PUT", 0.8, f"Pine RSI overbought ({r:.1f}) + MACD falling"
        elif r < 35:
            action, strength, reason = "CALL", 0.5, f"Pine RSI low ({r:.1f})"
        elif r > 65:
            action, strength, reason = "PUT", 0.5, f"Pine RSI high ({r:.1f})"

    return {
        "action": action,
        "strength": round(strength, 2),
        "reason": reason,
        "style": style,
    }

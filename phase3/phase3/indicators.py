"""Professional Technical Analysis Indicators"""
from __future__ import annotations

from typing import Dict, Tuple

import numpy as np
import pandas as pd


class TechnicalIndicators:
    """Collection of production-ready technical indicators."""

    @staticmethod
    def rsi(series: pd.Series, period: int = 14) -> pd.Series:
        """Relative Strength Index (Wilder-style smoothing)."""
        if len(series) < period + 1:
            return pd.Series(np.nan, index=series.index)

        delta = series.diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)

        avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
        avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()

        rs = avg_gain / avg_loss.replace(0, np.nan)
        rsi = 100 - (100 / (1 + rs))
        return rsi.fillna(50)

    @staticmethod
    def macd(
        series: pd.Series,
        fast: int = 12,
        slow: int = 26,
        signal: int = 9,
    ) -> Tuple[pd.Series, pd.Series, pd.Series]:
        """MACD line, signal line and histogram."""
        ema_fast = series.ewm(span=fast, adjust=False).mean()
        ema_slow = series.ewm(span=slow, adjust=False).mean()
        macd_line = ema_fast - ema_slow
        signal_line = macd_line.ewm(span=signal, adjust=False).mean()
        histogram = macd_line - signal_line
        return macd_line, signal_line, histogram

    @staticmethod
    def bollinger_bands(
        series: pd.Series,
        period: int = 20,
        std_dev: float = 2.0,
    ) -> Tuple[pd.Series, pd.Series, pd.Series]:
        """Upper, middle (SMA) and lower Bollinger Bands."""
        mid = series.rolling(window=period, min_periods=period).mean()
        std = series.rolling(window=period, min_periods=period).std()
        upper = mid + std_dev * std
        lower = mid - std_dev * std
        return upper, mid, lower

    @staticmethod
    def sma(series: pd.Series, period: int) -> pd.Series:
        """Simple Moving Average."""
        return series.rolling(window=period, min_periods=period).mean()

    @staticmethod
    def ema(series: pd.Series, period: int) -> pd.Series:
        """Exponential Moving Average."""
        return series.ewm(span=period, adjust=False).mean()

    @staticmethod
    def stochastic(
        high: pd.Series,
        low: pd.Series,
        close: pd.Series,
        k_period: int = 14,
        d_period: int = 3,
    ) -> Tuple[pd.Series, pd.Series]:
        """Stochastic %K and %D."""
        lowest_low = low.rolling(window=k_period, min_periods=k_period).min()
        highest_high = high.rolling(window=k_period, min_periods=k_period).max()
        denom = (highest_high - lowest_low).replace(0, np.nan)
        percent_k = 100 * (close - lowest_low) / denom
        percent_d = percent_k.rolling(window=d_period, min_periods=d_period).mean()
        return percent_k.fillna(50), percent_d.fillna(50)

    @staticmethod
    def atr(
        high: pd.Series,
        low: pd.Series,
        close: pd.Series,
        period: int = 14,
    ) -> pd.Series:
        """Average True Range."""
        prev_close = close.shift(1)
        tr = pd.concat(
            [
                high - low,
                (high - prev_close).abs(),
                (low - prev_close).abs(),
            ],
            axis=1,
        ).max(axis=1)
        return tr.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()

    @staticmethod
    def adx(
        high: pd.Series,
        low: pd.Series,
        close: pd.Series,
        period: int = 14,
    ) -> pd.Series:
        """Average Directional Index (trend strength)."""
        plus_dm = high.diff()
        minus_dm = -low.diff()
        plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0.0)
        minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0.0)

        tr = TechnicalIndicators.atr(high, low, close, period=1)
        atr = tr.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()

        plus_di = 100 * (
            plus_dm.ewm(alpha=1 / period, min_periods=period, adjust=False).mean() / atr
        )
        minus_di = 100 * (
            minus_dm.ewm(alpha=1 / period, min_periods=period, adjust=False).mean() / atr
        )

        dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
        adx = dx.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
        return adx.fillna(0)

    @classmethod
    def compute_all(
        cls,
        df: pd.DataFrame,
        rsi_period: int = 14,
        macd_fast: int = 12,
        macd_slow: int = 26,
        macd_signal: int = 9,
        bb_period: int = 20,
        bb_std: float = 2.0,
        ema_fast: int = 9,
        ema_slow: int = 21,
        stoch_k: int = 14,
        stoch_d: int = 3,
        atr_period: int = 14,
        adx_period: int = 14,
    ) -> Dict[str, pd.Series]:
        """
        Compute a full indicator suite from an OHLCV DataFrame.
        Expects columns: open, high, low, close (volume optional).
        """
        df = df.copy()
        df.columns = [str(c).lower() for c in df.columns]

        required = {"open", "high", "low", "close"}
        if not required.issubset(set(df.columns)):
            raise ValueError(
                f"DataFrame missing required columns: {required - set(df.columns)}"
            )

        close = df["close"]
        high = df["high"]
        low = df["low"]

        macd_line, signal_line, hist = cls.macd(
            close, macd_fast, macd_slow, macd_signal
        )
        bb_upper, bb_mid, bb_lower = cls.bollinger_bands(close, bb_period, bb_std)
        stoch_k_vals, stoch_d_vals = cls.stochastic(
            high, low, close, stoch_k, stoch_d
        )

        return {
            "rsi": cls.rsi(close, rsi_period),
            "macd": macd_line,
            "macd_signal": signal_line,
            "macd_hist": hist,
            "bb_upper": bb_upper,
            "bb_mid": bb_mid,
            "bb_lower": bb_lower,
            "ema_fast": cls.ema(close, ema_fast),
            "ema_slow": cls.ema(close, ema_slow),
            "sma_20": cls.sma(close, 20),
            "sma_50": cls.sma(close, 50)
            if len(df) >= 50
            else cls.sma(close, min(20, len(df))),
            "stoch_k": stoch_k_vals,
            "stoch_d": stoch_d_vals,
            "atr": cls.atr(high, low, close, atr_period),
            "adx": cls.adx(high, low, close, adx_period),
        }

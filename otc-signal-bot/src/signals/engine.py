"""Professional Multi-Indicator Signal Engine"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import pandas as pd

from ..utils.logger import get_logger
from .confidence import ConfidenceScorer
from .technical.indicators import TechnicalIndicators

logger = get_logger(__name__)


class SignalEngine:
    """
    Production-grade signal engine using multi-indicator confluence.

    Indicators used:
      - RSI (momentum / overbought-oversold)
      - MACD (trend + momentum)
      - Bollinger Bands (volatility + mean-reversion)
      - EMA cross (short-term trend)
      - Stochastic (momentum confirmation)
      - ADX (trend strength filter)

    Rules are deliberately strict: only emit CALL / PUT when several
    independent signals agree. Otherwise return NO_SIGNAL.
    """

    def __init__(self, settings: Any, data_fetcher: Any = None):
        self.settings = settings
        self.data_fetcher = data_fetcher
        self.min_confidence = getattr(settings, "MIN_CONFIDENCE", 70)
        self.indicators = TechnicalIndicators()
        self.use_ai = getattr(settings, "USE_AI", False)
        self.tech_weight = float(getattr(settings, "TECH_WEIGHT", 0.7))
        self.ai_weight = 1.0 - self.tech_weight
        # Multi-timeframe confluence (enabled by default)
        self.use_mtf = True
        self.htf_filter_strict = False  # if True, block counter-trend signals

        # Load technical parameters from config if available
        tech_cfg: Dict = {}
        signals_cfg: Dict = {}
        if hasattr(settings, "config") and isinstance(settings.config, dict):
            signals_cfg = settings.config.get("signals", {}) or {}
            tech_cfg = signals_cfg.get("technical", {}) or {}
            engine_mode = signals_cfg.get("engine", "technical")
            if engine_mode == "hybrid":
                self.use_ai = True
            self.use_ai = self.use_ai or bool(signals_cfg.get("use_ai", False))
            mtf_cfg = signals_cfg.get("mtf") or {}
            self.use_mtf = bool(mtf_cfg.get("enabled", True))
            self.htf_filter_strict = bool(mtf_cfg.get("strict_filter", False))
            self.mtf_min_alignment = int(mtf_cfg.get("min_alignment", 1))

        self.min_confluence = int(tech_cfg.get("min_confluence", 2))
        self.rsi_period = tech_cfg.get("rsi_period", 14)
        self.rsi_ob = tech_cfg.get("rsi_overbought", 70)
        self.rsi_os = tech_cfg.get("rsi_oversold", 30)
        self.macd_fast = tech_cfg.get("macd_fast", 12)
        self.macd_slow = tech_cfg.get("macd_slow", 26)
        self.macd_signal = tech_cfg.get("macd_signal", 9)
        self.bb_period = tech_cfg.get("bb_period", 20)
        self.bb_std = float(tech_cfg.get("bb_std", 2.0))

        conf_cfg: Dict = {}
        if signals_cfg:
            conf_cfg = signals_cfg.get("confidence", {}) or {}
        self.scorer = ConfidenceScorer(
            conf_cfg or {"min_required": self.min_confidence}
        )

        # Lazy ML predictor
        self._ml_predictor = None
        if self.use_ai:
            try:
                from .ai.predictor import MLPredictor
                self._ml_predictor = MLPredictor(settings)
                logger.info("Hybrid mode enabled – ML predictor loaded")
            except Exception as e:
                logger.warning("Could not load ML predictor: %s", e)
                self.use_ai = False

    async def generate_signal(
        self,
        asset: str,
        timeframe: str = "1m",
        candles: Optional[pd.DataFrame] = None,
    ) -> Dict[str, Any]:
        """
        Generate a trading signal for the given asset.

        Prefer passing a ready DataFrame (candles) for testing / offline use.
        If candles is None, the engine will try to fetch via data_fetcher.
        """
        try:
            if candles is None:
                if self.data_fetcher is None:
                    return self._no_signal(asset, "No data source available")
                candles = await self.data_fetcher.get_historical_data(
                    asset, timeframe
                )

            if candles is None or candles.empty:
                return self._no_signal(asset, "No data available")

            if len(candles) < 30:
                return self._no_signal(
                    asset,
                    f"Insufficient data ({len(candles)} candles, need ≥30)",
                )

            # Normalize columns
            df = candles.copy()
            df.columns = [str(c).lower() for c in df.columns]

            indicators = self.indicators.compute_all(
                df,
                rsi_period=self.rsi_period,
                macd_fast=self.macd_fast,
                macd_slow=self.macd_slow,
                macd_signal=self.macd_signal,
                bb_period=self.bb_period,
                bb_std=self.bb_std,
            )

            analysis = self._analyze(df, indicators)
            analysis["asset"] = asset
            analysis["timeframe"] = timeframe
            analysis["entry_price"] = float(df["close"].iloc[-1])
            analysis["timestamp"] = datetime.now(timezone.utc).isoformat()

            # Multi-timeframe confluence
            htf_info = None
            if self.use_mtf and len(df) >= 60:
                try:
                    from .timeframes import (
                        higher_tf_bias,
                        resample_ohlcv,
                        suggest_higher_tf,
                    )

                    htf_name = suggest_higher_tf(timeframe)
                    htf_df = resample_ohlcv(df, htf_name)
                    htf_info = higher_tf_bias(htf_df)
                    htf_info["timeframe"] = htf_name
                    analysis["htf"] = htf_info

                    if analysis["action"] in ("CALL", "PUT") and htf_info:
                        aligned = (
                            (analysis["action"] == "CALL" and htf_info["bias"] == "BULLISH")
                            or (analysis["action"] == "PUT" and htf_info["bias"] == "BEARISH")
                        )
                        opposed = (
                            (analysis["action"] == "CALL" and htf_info["bias"] == "BEARISH")
                            or (analysis["action"] == "PUT" and htf_info["bias"] == "BULLISH")
                        )

                        if aligned:
                            analysis["confluence_score"] = (
                                float(analysis.get("confluence_score") or 0) + self.mtf_min_alignment
                            )
                            analysis["reason"] = (
                                analysis.get("reason", "")
                                + f" | HTF {htf_name} {htf_info['bias']}"
                            )
                        elif opposed:
                            if self.htf_filter_strict:
                                return self._no_signal(
                                    asset,
                                    f"Blocked by HTF {htf_name} bias ({htf_info['bias']})",
                                    snapshot=analysis.get("indicator_snapshot"),
                                )
                            analysis["confluence_score"] = max(
                                0.0,
                                float(analysis.get("confluence_score") or 0) - self.mtf_min_alignment,
                            )
                            analysis["reason"] = (
                                analysis.get("reason", "")
                                + f" | HTF conflict ({htf_info['bias']})"
                            )
                except Exception as e:
                    logger.debug("MTF analysis skipped: %s", e)

            # Optional ML vote (hybrid mode)
            ml_result = None
            if self.use_ai and self._ml_predictor is not None:
                try:
                    ml_result = await self._ml_predictor.predict(df, indicators)
                    analysis["ml"] = {
                        "action": ml_result.get("action"),
                        "confidence": ml_result.get("confidence"),
                        "method": ml_result.get("method"),
                    }
                except Exception as e:
                    logger.debug("ML prediction skipped: %s", e)

            if analysis["action"] == "NO_SIGNAL":
                # In hybrid mode, a strong ML signal can still produce a trade
                if (
                    ml_result
                    and ml_result.get("action") in ("CALL", "PUT")
                    and (ml_result.get("confidence") or 0) >= max(65, self.min_confidence)
                ):
                    analysis["action"] = ml_result["action"]
                    analysis["reason"] = (
                        f"ML override ({ml_result.get('method')}): "
                        f"{ml_result['action']} @ {ml_result['confidence']:.0f}%"
                    )
                    analysis["confluence_score"] = analysis.get("confluence_score", 0) + 1
                else:
                    return analysis

            # Technical confidence
            conf_result = self.scorer.calculate(
                {
                    "action": analysis["action"],
                    "votes": analysis.get("votes", {}),
                    "indicators": analysis.get("indicator_snapshot", {}),
                    "confluence_score": analysis.get("confluence_score", 0),
                }
            )
            tech_conf = float(conf_result["confidence"])

            # Blend with ML when both agree or hybrid weights apply
            if ml_result and ml_result.get("action") in ("CALL", "PUT"):
                ml_conf = float(ml_result.get("confidence") or 0)
                if ml_result["action"] == analysis["action"]:
                    # Agreement → weighted average, slight boost
                    blended = (
                        self.tech_weight * tech_conf + self.ai_weight * ml_conf
                    )
                    analysis["confidence"] = min(99.0, blended + 3.0)
                    analysis["reason"] = (
                        analysis.get("reason", "") + " | ML agrees"
                    )
                else:
                    # Disagreement → keep technical but reduce confidence
                    analysis["confidence"] = max(0.0, tech_conf - 8.0)
            else:
                analysis["confidence"] = tech_conf

            # HTF confidence adjustment
            if htf_info and analysis.get("action") in ("CALL", "PUT"):
                if (
                    (analysis["action"] == "CALL" and htf_info["bias"] == "BULLISH")
                    or (analysis["action"] == "PUT" and htf_info["bias"] == "BEARISH")
                ):
                    analysis["confidence"] = min(99.0, analysis["confidence"] + 5.0)
                elif (
                    (analysis["action"] == "CALL" and htf_info["bias"] == "BEARISH")
                    or (analysis["action"] == "PUT" and htf_info["bias"] == "BULLISH")
                ):
                    analysis["confidence"] = max(0.0, analysis["confidence"] - 10.0)

            analysis["is_valid"] = analysis["confidence"] >= self.min_confidence

            # Final gate
            if analysis["confidence"] < self.min_confidence:
                return self._no_signal(
                    asset,
                    f"Confidence {analysis['confidence']:.0f}% below threshold "
                    f"({self.min_confidence}%)",
                    snapshot=analysis.get("indicator_snapshot"),
                )

            return analysis

        except Exception as e:
            logger.exception("Signal generation failed for %s", asset)
            return self._no_signal(asset, f"Error: {str(e)}")

    def _analyze(
        self, df: pd.DataFrame, ind: Dict[str, pd.Series]
    ) -> Dict[str, Any]:
        """Core multi-indicator confluence logic."""
        close = df["close"]
        last_close = float(close.iloc[-1])

        def last(s: pd.Series, default: float = 0.0) -> float:
            if s is None or s.empty or pd.isna(s.iloc[-1]):
                return default
            return float(s.iloc[-1])

        def prev(s: pd.Series, default: float = 0.0) -> float:
            if s is None or len(s) < 2 or pd.isna(s.iloc[-2]):
                return default
            return float(s.iloc[-2])

        rsi = last(ind["rsi"], 50)
        macd = last(ind["macd"])
        macd_sig = last(ind["macd_signal"])
        macd_hist = last(ind["macd_hist"])
        macd_hist_prev = prev(ind["macd_hist"])
        bb_upper = last(ind["bb_upper"], last_close)
        bb_mid = last(ind["bb_mid"], last_close)
        bb_lower = last(ind["bb_lower"], last_close)
        ema_fast = last(ind["ema_fast"], last_close)
        ema_slow = last(ind["ema_slow"], last_close)
        stoch_k = last(ind["stoch_k"], 50)
        stoch_d = last(ind["stoch_d"], 50)
        adx = last(ind["adx"], 0)

        # --- Individual votes ---
        votes: Dict[str, int] = {
            "rsi": 0,
            "macd": 0,
            "bollinger": 0,
            "ema": 0,
            "stochastic": 0,
        }
        reasons: List[str] = []

        # 1. RSI
        if rsi <= self.rsi_os:
            votes["rsi"] = 1
            reasons.append(f"RSI oversold ({rsi:.1f})")
        elif rsi >= self.rsi_ob:
            votes["rsi"] = -1
            reasons.append(f"RSI overbought ({rsi:.1f})")

        # 2. MACD (histogram direction + cross)
        # Soften when RSI is extreme so lagging MACD does not block mean-reversion
        macd_vote = 0
        if macd_hist > 0 and macd_hist > macd_hist_prev:
            macd_vote = 1
            reasons.append("MACD histogram rising / bullish")
        elif macd_hist < 0 and macd_hist < macd_hist_prev:
            macd_vote = -1
            reasons.append("MACD histogram falling / bearish")
        elif macd > macd_sig and prev(ind["macd"]) <= prev(ind["macd_signal"]):
            macd_vote = 1
            reasons.append("MACD bullish crossover")
        elif macd < macd_sig and prev(ind["macd"]) >= prev(ind["macd_signal"]):
            macd_vote = -1
            reasons.append("MACD bearish crossover")
        # At extreme RSI, only cancel MACD when it *opposes* the RSI
        # mean-reversion direction (lagging MACD vetoing the setup).
        # Previously this zeroed MACD even when it agreed, which
        # silently discarded confirming votes at the exact moments a
        # signal was most likely to be valid.
        if rsi <= 18 and macd_vote < 0:
            macd_vote = 0
        elif rsi >= 82 and macd_vote > 0:
            macd_vote = 0
        votes["macd"] = macd_vote

        # 3. Bollinger Bands (mean-reversion bias)
        bb_range = bb_upper - bb_lower
        if bb_range > 0:
            bb_pos = (last_close - bb_lower) / bb_range
            if last_close <= bb_lower * 1.001:
                votes["bollinger"] = 1
                reasons.append("Price at/below lower Bollinger Band")
            elif last_close >= bb_upper * 0.999:
                votes["bollinger"] = -1
                reasons.append("Price at/above upper Bollinger Band")
            elif bb_pos < 0.25:
                votes["bollinger"] = 1
                reasons.append("Price in lower Bollinger zone")
            elif bb_pos > 0.75:
                votes["bollinger"] = -1
                reasons.append("Price in upper Bollinger zone")

        # 4. EMA trend (softened when RSI is extreme – mean-reversion priority)
        ema_vote = 0
        if ema_fast > ema_slow and last_close > ema_fast:
            ema_vote = 1
            reasons.append("Price above rising EMA stack")
        elif ema_fast < ema_slow and last_close < ema_fast:
            ema_vote = -1
            reasons.append("Price below falling EMA stack")
        # Same fix as MACD above: only cancel EMA when it opposes the
        # extreme-RSI mean-reversion direction, not whenever it agrees.
        if rsi <= 18 and ema_vote < 0:
            ema_vote = 0
        elif rsi >= 82 and ema_vote > 0:
            ema_vote = 0
        votes["ema"] = ema_vote

        # 5. Stochastic
        if stoch_k < 20 and stoch_k > stoch_d:
            votes["stochastic"] = 1
            reasons.append(f"Stochastic oversold turn-up ({stoch_k:.1f})")
        elif stoch_k > 80 and stoch_k < stoch_d:
            votes["stochastic"] = -1
            reasons.append(f"Stochastic overbought turn-down ({stoch_k:.1f})")
        elif stoch_k < 25:
            votes["stochastic"] = 1
            reasons.append(f"Stochastic oversold ({stoch_k:.1f})")
        elif stoch_k > 75:
            votes["stochastic"] = -1
            reasons.append(f"Stochastic overbought ({stoch_k:.1f})")

        # --- Aggregate ---
        bullish = sum(1 for v in votes.values() if v > 0)
        bearish = sum(1 for v in votes.values() if v < 0)
        net = sum(votes.values())

        strong_trend = adx >= 20

        snapshot = {
            "rsi": round(rsi, 2),
            "macd_hist": round(macd_hist, 6),
            "bb_position": round(
                (last_close - bb_lower) / bb_range if bb_range > 0 else 0.5, 3
            ),
            "ema_fast": round(ema_fast, 5),
            "ema_slow": round(ema_slow, 5),
            "stoch_k": round(stoch_k, 2),
            "adx": round(adx, 2),
        }

        # Decision thresholds (professional but usable for short-term OTC):
        # Require at least `min_confluence` agreeing votes (default 2 of 5)
        # and a matching net score, so a lone opposing vote can't cancel
        # a real setup but true 50/50 splits still get filtered out.
        min_conf = self.min_confluence
        if bullish >= min_conf and net >= min_conf:
            action = "CALL"
            reason = " | ".join(reasons) if reasons else "Bullish confluence"
        elif bearish >= min_conf and net <= -min_conf:
            action = "PUT"
            reason = " | ".join(reasons) if reasons else "Bearish confluence"
        else:
            return {
                "action": "NO_SIGNAL",
                "confidence": 0,
                "reason": (
                    f"Insufficient confluence (bull={bullish}, bear={bearish}, net={net}). "
                    "Conditions for a clear CALL or PUT are not met."
                ),
                "votes": votes,
                "indicator_snapshot": snapshot,
                "confluence_score": max(bullish, bearish),
            }

        confluence_score = float(max(bullish, bearish))
        if not strong_trend:
            confluence_score = max(0.0, confluence_score - 0.5)

        return {
            "action": action,
            "reason": reason,
            "votes": votes,
            "indicator_snapshot": snapshot,
            "confluence_score": confluence_score,
            "bullish_count": bullish,
            "bearish_count": bearish,
        }

    def _no_signal(
        self,
        asset: str,
        reason: str,
        snapshot: Optional[Dict] = None,
    ) -> Dict[str, Any]:
        """Standard NO_SIGNAL response."""
        return {
            "action": "NO_SIGNAL",
            "asset": asset,
            "confidence": 0,
            "reason": reason,
            "entry_price": None,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "indicator_snapshot": snapshot or {},
        }

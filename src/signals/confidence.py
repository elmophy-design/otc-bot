"""Multi-factor Confidence Scoring System"""
from __future__ import annotations

from typing import Any, Dict


class ConfidenceScorer:
    """
    Converts indicator confluence + snapshot strength into a 0-100 confidence score.
    Designed to work with the multi-indicator SignalEngine.
    """

    def __init__(self, config: Dict[str, Any] | None = None):
        config = config or {}
        self.min_required = float(config.get("min_required", 70))
        # Weights kept for future hybrid (ML / PineScript) expansion
        self.weights = {
            "technical": float(config.get("weight_technical", 0.7)),
            "ml": float(config.get("weight_ml", 0.2)),
            "pinescript": float(config.get("weight_pinescript", 0.05)),
            "consensus": float(config.get("weight_consensus", 0.05)),
        }

    def calculate(self, signals: Dict[str, Any]) -> Dict[str, Any]:
        """
        Expected keys in `signals`:
          - action: CALL | PUT | NO_SIGNAL
          - votes: dict of indicator -> +1 / 0 / -1
          - confluence_score: float (number of agreeing indicators)
          - indicators: snapshot dict (rsi, macd_hist, bb_position, stoch_k, adx, ...)
        """
        if signals.get("action") == "NO_SIGNAL":
            return {"confidence": 0.0, "is_valid": False}

        votes = signals.get("votes") or {}
        confluence = float(signals.get("confluence_score") or 0)
        snap = signals.get("indicators") or {}

        # Base from how many indicators agree (max theoretical = 5)
        # 3 → ~68, 4 → ~80, 5 → ~90
        base = 50.0 + (confluence * 10.0)
        base = min(base, 92.0)

        # Strength bonuses / penalties from individual indicators
        bonus = 0.0

        rsi = snap.get("rsi")
        if rsi is not None:
            if rsi <= 20 or rsi >= 80:
                bonus += 6.0  # extreme
            elif rsi <= 30 or rsi >= 70:
                bonus += 3.0

        stoch_k = snap.get("stoch_k")
        if stoch_k is not None:
            if stoch_k <= 15 or stoch_k >= 85:
                bonus += 4.0
            elif stoch_k <= 25 or stoch_k >= 75:
                bonus += 2.0

        # Bollinger position (0 = lower band, 1 = upper band)
        bb_pos = snap.get("bb_position")
        if bb_pos is not None:
            if bb_pos <= 0.05 or bb_pos >= 0.95:
                bonus += 5.0
            elif bb_pos <= 0.2 or bb_pos >= 0.8:
                bonus += 2.5

        adx = snap.get("adx")
        if adx is not None:
            if adx >= 30:
                bonus += 4.0  # strong trend
            elif adx >= 20:
                bonus += 2.0
            elif adx < 15:
                bonus -= 5.0  # choppy → lower confidence

        # Slight boost when net vote is clean (no opposing votes)
        opposing = sum(1 for v in votes.values() if v != 0 and (
            (signals.get("action") == "CALL" and v < 0) or
            (signals.get("action") == "PUT" and v > 0)
        ))
        if opposing == 0:
            bonus += 3.0
        else:
            bonus -= opposing * 4.0

        confidence = max(0.0, min(99.0, base + bonus))

        return {
            "confidence": round(confidence, 1),
            "is_valid": confidence >= self.min_required,
            "breakdown": {
                "base": round(base, 1),
                "bonus": round(bonus, 1),
                "confluence": confluence,
            },
        }

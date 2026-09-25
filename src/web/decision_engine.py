"""Phase 7 professional decision and execution intelligence.

This module is deliberately broker-agnostic. It converts the existing live
scanner + signal-engine output into a structured decision package that the
Render dashboard can present before a user confirms execution.

It never places a trade. Actual execution remains owned by the Railway bot
runtime and its single broker session.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class DecisionThresholds:
    minimum_trade_score: float = 70.0
    minimum_signal_confidence: float = 70.0
    minimum_scanner_score: float = 62.0


class ProfessionalDecisionEngine:
    """Build a transparent, deterministic decision package."""

    def __init__(self, thresholds: DecisionThresholds | None = None) -> None:
        self.thresholds = thresholds or DecisionThresholds()

    def build(
        self,
        *,
        signal: dict[str, Any],
        scanner: dict[str, Any],
        timeframe: str,
        amount: float | None = None,
        balance: float | None = None,
        risk_blocked: bool = False,
    ) -> dict[str, Any]:
        action = str(signal.get("action") or "WAIT").upper()
        confidence = self._num(signal.get("confidence"))
        scan_score = self._num(scanner.get("strength") or scanner.get("score"))
        trend = str(scanner.get("trend") or scanner.get("bias") or "NEUTRAL").upper()
        regime = self._regime(scanner)
        conflicts = list(scanner.get("conflicts") or [])
        components = dict(scanner.get("score_components") or {})

        # Directional confluence: scanner, signal engine, and higher timeframe.
        htf = str(scanner.get("confirmation_trend") or "NEUTRAL").upper()
        expected_trend = "BULLISH" if action == "CALL" else "BEARISH" if action == "PUT" else "NEUTRAL"
        confluence = {
            "signal_engine": self._vote(action),
            "scanner_trend": self._vote_from_trend(trend, expected_trend),
            "momentum": self._vote_from_trend(str(scanner.get("momentum") or "NEUTRAL"), expected_trend),
            "macd": self._vote_from_trend(str(scanner.get("macd_bias") or "MIXED"), expected_trend),
            "higher_timeframe": self._vote_from_trend(htf, expected_trend),
            "regime": regime,
        }
        confluence_score = self._confluence_score(confluence)

        trade_quality = self._trade_quality(
            action=action,
            confidence=confidence,
            scan_score=scan_score,
            confluence_score=confluence_score,
            regime=regime,
            conflicts=conflicts,
        )
        entry_quality = self._entry_quality(scanner, action, conflicts)
        expiry = self._expiry(timeframe, regime, scanner, action)
        no_trade = self._no_trade_conditions(
            action=action,
            confidence=confidence,
            scan_score=scan_score,
            trade_quality=trade_quality["score"],
            regime=regime,
            conflicts=conflicts,
            risk_blocked=risk_blocked,
        )
        explanation = self._explanation(action, scanner, signal, confluence, no_trade)

        risk = self._risk_snapshot(amount, balance, risk_blocked)
        allowed = not no_trade and risk["status"] == "OK"

        return {
            "decision": "EXECUTE_CANDIDATE" if allowed else "WAIT",
            "action": action,
            "asset": signal.get("asset") or scanner.get("asset"),
            "timeframe": timeframe,
            "market_regime": regime,
            "scanner_score": round(scan_score, 1),
            "signal_confidence": round(confidence, 1),
            "confluence_score": round(confluence_score, 1),
            "entry_quality": entry_quality,
            "trade_quality": trade_quality,
            "expiry_recommendation": expiry,
            "risk": risk,
            "confluence_matrix": confluence,
            "score_components": components,
            "conflicts": conflicts,
            "no_trade_conditions": no_trade,
            "explanation": explanation,
            "signal_snapshot": signal,
            "scanner_snapshot": scanner,
        }

    @staticmethod
    def _num(value: Any, default: float = 0.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _vote(action: str) -> str:
        return action if action in {"CALL", "PUT"} else "WAIT"

    @staticmethod
    def _vote_from_trend(value: str, expected: str) -> str:
        if expected == "NEUTRAL":
            return "NEUTRAL"
        value = value.upper()
        return "AGREE" if value == expected else "CONFLICT" if value in {"BULLISH", "BEARISH"} else "NEUTRAL"

    @staticmethod
    def _regime(scanner: dict[str, Any]) -> str:
        raw = str(scanner.get("regime") or "").upper()
        if raw in {"TRENDING", "RANGING", "TRANSITION", "VOLATILE"}:
            if raw == "TRENDING" and str(scanner.get("volatility_state", "")).upper() == "HIGH":
                return "VOLATILE"
            return raw
        volatility = str(scanner.get("volatility_state") or "").upper()
        if volatility == "HIGH":
            return "VOLATILE"
        if raw in {"RANGE", "RANGING"}:
            return "RANGING"
        return "TRENDING" if raw else "TRANSITION"

    @staticmethod
    def _confluence_score(matrix: dict[str, Any]) -> float:
        vals = [v for k, v in matrix.items() if k != "regime"]
        agree = vals.count("AGREE")
        conflict = vals.count("CONFLICT")
        neutral = vals.count("NEUTRAL")
        return max(0.0, min(100.0, 50.0 + agree * 12.5 - conflict * 15.0 - neutral * 2.5))

    def _trade_quality(self, *, action: str, confidence: float, scan_score: float,
                       confluence_score: float, regime: str, conflicts: list[str]) -> dict[str, Any]:
        score = 0.35 * confidence + 0.30 * scan_score + 0.35 * confluence_score
        if regime == "RANGING" and action in {"CALL", "PUT"}:
            score -= 8
        if regime == "VOLATILE":
            score -= 10
        score -= min(20, len(conflicts) * 5)
        score = max(0.0, min(100.0, score))
        grade = "A" if score >= 82 else "B" if score >= 72 else "C" if score >= 62 else "D"
        return {"score": round(score, 1), "grade": grade, "label": "HIGH" if score >= 78 else "MEDIUM" if score >= 62 else "LOW"}

    @staticmethod
    def _entry_quality(scanner: dict[str, Any], action: str, conflicts: list[str]) -> str:
        score = float(scanner.get("strength") or 0)
        if action not in {"CALL", "PUT"}:
            return "LOW"
        if conflicts or score < 62:
            return "LOW"
        return "HIGH" if score >= 78 else "MEDIUM"

    @staticmethod
    def _expiry(timeframe: str, regime: str, scanner: dict[str, Any], action: str) -> dict[str, Any]:
        base = {"1m": [60, 120], "2m": [120, 300], "5m": [300, 600], "15m": [600], "30m": [600], "1h": [600]}
        values = base.get(timeframe, [60])
        if action == "WAIT":
            return {"recommended_seconds": values, "confidence": "LOW", "reason": "No executable directional signal"}
        if regime == "VOLATILE":
            return {"recommended_seconds": values[-1:], "confidence": "LOW", "reason": "Volatility is elevated; shorter expiry is avoided"}
        if regime == "RANGING":
            return {"recommended_seconds": values[-1:], "confidence": "MEDIUM", "reason": "Range conditions require confirmation before entry"}
        return {"recommended_seconds": values, "confidence": "HIGH", "reason": "Expiry aligned with timeframe and directional regime"}

    def _no_trade_conditions(self, *, action: str, confidence: float, scan_score: float,
                             trade_quality: float, regime: str, conflicts: list[str], risk_blocked: bool) -> list[str]:
        reasons: list[str] = []
        if action not in {"CALL", "PUT"}:
            reasons.append("Signal engine returned WAIT/NO_SIGNAL")
        if confidence < self.thresholds.minimum_signal_confidence:
            reasons.append(f"Signal confidence below {self.thresholds.minimum_signal_confidence:.0f}%")
        if scan_score < self.thresholds.minimum_scanner_score:
            reasons.append(f"Scanner score below {self.thresholds.minimum_scanner_score:.0f}")
        if trade_quality < self.thresholds.minimum_trade_score:
            reasons.append(f"Trade quality below {self.thresholds.minimum_trade_score:.0f}")
        if regime == "VOLATILE":
            reasons.append("Elevated volatility")
        if len(conflicts) >= 2:
            reasons.append("Multiple indicator conflicts")
        if risk_blocked:
            reasons.append("Risk validation rejected the requested trade")
        return reasons

    @staticmethod
    def _explanation(action: str, scanner: dict[str, Any], signal: dict[str, Any], matrix: dict[str, Any], no_trade: list[str]) -> dict[str, Any]:
        reasons: list[str] = []
        if action == "CALL":
            reasons.append("Directional bias is bullish")
        elif action == "PUT":
            reasons.append("Directional bias is bearish")
        else:
            reasons.append("Directional evidence is insufficient")
        for key in ("momentum", "macd", "higher_timeframe"):
            if matrix.get(key) == "AGREE":
                reasons.append(f"{key.replace('_', ' ').title()} confirms direction")
            elif matrix.get(key) == "CONFLICT":
                reasons.append(f"{key.replace('_', ' ').title()} conflicts with direction")
        engine_reason = signal.get("reason")
        if engine_reason:
            reasons.append(str(engine_reason))
        return {
            "why_call": reasons if action == "CALL" else [],
            "why_put": reasons if action == "PUT" else [],
            "why_wait": no_trade if no_trade else [],
            "summary": " | ".join(reasons[:5]),
        }

    @staticmethod
    def _risk_snapshot(amount: float | None, balance: float | None, blocked: bool) -> dict[str, Any]:
        if blocked:
            status = "BLOCKED"
        elif amount is None or balance is None or balance <= 0:
            status = "UNAVAILABLE"
        else:
            pct = amount / balance * 100
            status = "OK" if pct <= 2 else "WARNING" if pct <= 5 else "BLOCKED"
            return {"status": status, "amount": round(amount, 2), "balance": round(balance, 2), "risk_percent": round(pct, 2), "max_risk_percent": 2.0}
        return {"status": status, "amount": amount, "balance": balance, "risk_percent": None, "max_risk_percent": 2.0}

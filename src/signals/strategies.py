"""Multi-Strategy Registry & Concrete Strategies"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Type

from ..utils.logger import get_logger

logger = get_logger(__name__)


class BaseStrategy(ABC):
    """Abstract base for all trading strategies."""

    name: str = "base"

    @abstractmethod
    def evaluate(
        self, indicators: Dict[str, Any], snapshot: Dict[str, float]
    ) -> Dict[str, Any]:
        """
        Return a vote dict:
          {
            "action": "CALL" | "PUT" | "NEUTRAL",
            "strength": 0.0-1.0,
            "reason": str
          }
        """
        ...


class RSIStrategy(BaseStrategy):
    name = "rsi"

    def __init__(self, oversold: float = 30, overbought: float = 70):
        self.oversold = oversold
        self.overbought = overbought

    def evaluate(
        self, indicators: Dict[str, Any], snapshot: Dict[str, float]
    ) -> Dict[str, Any]:
        rsi = snapshot.get("rsi", 50)
        if rsi <= self.oversold:
            strength = min(1.0, (self.oversold - rsi) / 15 + 0.6)
            return {
                "action": "CALL",
                "strength": strength,
                "reason": f"RSI oversold ({rsi:.1f})",
            }
        if rsi >= self.overbought:
            strength = min(1.0, (rsi - self.overbought) / 15 + 0.6)
            return {
                "action": "PUT",
                "strength": strength,
                "reason": f"RSI overbought ({rsi:.1f})",
            }
        return {"action": "NEUTRAL", "strength": 0.0, "reason": "RSI neutral"}


class MACDStrategy(BaseStrategy):
    name = "macd"

    def evaluate(
        self, indicators: Dict[str, Any], snapshot: Dict[str, float]
    ) -> Dict[str, Any]:
        hist = snapshot.get("macd_hist", 0.0)
        if hist > 0:
            return {
                "action": "CALL",
                "strength": min(1.0, abs(hist) * 50 + 0.5),
                "reason": "MACD hist positive",
            }
        if hist < 0:
            return {
                "action": "PUT",
                "strength": min(1.0, abs(hist) * 50 + 0.5),
                "reason": "MACD hist negative",
            }
        return {"action": "NEUTRAL", "strength": 0.0, "reason": "MACD flat"}


class BollingerStrategy(BaseStrategy):
    name = "bollinger"

    def evaluate(
        self, indicators: Dict[str, Any], snapshot: Dict[str, float]
    ) -> Dict[str, Any]:
        pos = snapshot.get("bb_position", 0.5)
        if pos <= 0.15:
            return {
                "action": "CALL",
                "strength": 0.7 + (0.15 - pos) * 2,
                "reason": "Near lower BB",
            }
        if pos >= 0.85:
            return {
                "action": "PUT",
                "strength": 0.7 + (pos - 0.85) * 2,
                "reason": "Near upper BB",
            }
        return {"action": "NEUTRAL", "strength": 0.0, "reason": "BB mid-zone"}


class StrategyRegistry:
    """Registry for trading strategies."""

    _strategies: Dict[str, Type[BaseStrategy]] = {}

    @classmethod
    def register(cls, name: str, strategy_class: Type[BaseStrategy]) -> None:
        cls._strategies[name] = strategy_class
        logger.info("Registered strategy: %s", name)

    @classmethod
    def get_strategy(cls, name: str) -> Optional[Type[BaseStrategy]]:
        return cls._strategies.get(name)

    @classmethod
    def list_strategies(cls) -> List[str]:
        return list(cls._strategies.keys())

    @classmethod
    def create_default_set(cls) -> List[BaseStrategy]:
        """Return a ready-to-use list of default strategy instances."""
        return [
            RSIStrategy(),
            MACDStrategy(),
            BollingerStrategy(),
        ]


# Auto-register built-ins
StrategyRegistry.register("rsi", RSIStrategy)
StrategyRegistry.register("macd", MACDStrategy)


class PineStyleStrategy(BaseStrategy):
    name = "pine"

    def __init__(self, style: str = "rsi_macd"):
        self.style = style

    def evaluate(
        self, indicators: Dict[str, Any], snapshot: Dict[str, float]
    ) -> Dict[str, Any]:
        # Snapshot-only lightweight vote (full DF path available via pine_strategy_vote)
        rsi = snapshot.get("rsi", 50)
        macd_hist = snapshot.get("macd_hist", 0)
        if rsi < 30 and macd_hist > 0:
            return {"action": "CALL", "strength": 0.75, "reason": f"Pine-style RSI+MACD CALL ({rsi:.1f})"}
        if rsi > 70 and macd_hist < 0:
            return {"action": "PUT", "strength": 0.75, "reason": f"Pine-style RSI+MACD PUT ({rsi:.1f})"}
        return {"action": "NEUTRAL", "strength": 0.0, "reason": "Pine-style neutral"}

StrategyRegistry.register("bollinger", BollingerStrategy)
StrategyRegistry.register("pine", PineStyleStrategy)

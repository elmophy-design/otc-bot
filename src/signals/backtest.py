"""Professional Backtesting Engine for binary-style OTC signals."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from ..utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class Trade:
    entry_idx: int
    direction: str  # CALL or PUT
    entry_price: float
    exit_price: float
    pnl: float
    won: bool
    confidence: float
    reason: str = ""


@dataclass
class BacktestResult:
    total_trades: int = 0
    wins: int = 0
    losses: int = 0
    win_rate: float = 0.0
    total_return_pct: float = 0.0
    final_balance: float = 0.0
    max_drawdown_pct: float = 0.0
    profit_factor: float = 0.0
    avg_confidence: float = 0.0
    trades: List[Trade] = field(default_factory=list)
    equity_curve: List[float] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_trades": self.total_trades,
            "wins": self.wins,
            "losses": self.losses,
            "win_rate": round(self.win_rate, 2),
            "total_return_pct": round(self.total_return_pct, 2),
            "final_balance": round(self.final_balance, 2),
            "max_drawdown_pct": round(self.max_drawdown_pct, 2),
            "profit_factor": round(self.profit_factor, 3),
            "avg_confidence": round(self.avg_confidence, 1),
        }


class BacktestEngine:
    """
    Walk-forward backtester tailored to short-expiry binary / OTC signals.

    At each bar (after a warm-up), the signal engine is evaluated on the
    historical window. A CALL/PUT is opened and resolved after `expiry_bars`
    using simple close-to-close direction.
    """

    def __init__(self, config: Optional[Dict] = None):
        config = config or {}
        self.initial_balance = float(config.get("initial_balance", 1000.0))
        self.stake = float(config.get("stake", 10.0))  # fixed stake per trade
        self.payout = float(config.get("payout", 0.80))  # 80% return on win
        self.expiry_bars = int(config.get("expiry_bars", 3))
        self.warmup = int(config.get("warmup", 40))
        self.min_confidence = float(config.get("min_confidence", 70))
        self.commission = float(config.get("commission", 0.0))

    async def run(
        self,
        data: pd.DataFrame,
        engine: Any,
        asset: str = "BACKTEST",
    ) -> BacktestResult:
        """
        Run a walk-forward backtest.

        Parameters
        ----------
        data : OHLCV DataFrame (oldest first)
        engine : SignalEngine instance (will be called with candles=window)
        asset : label for logging
        """
        df = data.copy()
        df.columns = [str(c).lower() for c in df.columns]
        if len(df) < self.warmup + self.expiry_bars + 5:
            logger.warning("Not enough data for backtest")
            return BacktestResult(final_balance=self.initial_balance)

        balance = self.initial_balance
        peak = balance
        max_dd = 0.0
        equity: List[float] = [balance]
        trades: List[Trade] = []
        gross_profit = 0.0
        gross_loss = 0.0

        n = len(df)
        i = self.warmup
        while i < n - self.expiry_bars:
            window = df.iloc[: i + 1]
            try:
                signal = await engine.generate_signal(asset, candles=window)
            except Exception as e:
                logger.debug("Signal error at bar %d: %s", i, e)
                i += 1
                continue

            action = signal.get("action")
            conf = float(signal.get("confidence") or 0)

            if action not in ("CALL", "PUT") or conf < self.min_confidence:
                i += 1
                continue

            entry_price = float(df["close"].iloc[i])
            exit_price = float(df["close"].iloc[i + self.expiry_bars])
            direction = action

            if direction == "CALL":
                won = exit_price > entry_price
            else:
                won = exit_price < entry_price

            if won:
                pnl = self.stake * self.payout - self.commission
                gross_profit += pnl
            else:
                pnl = -self.stake - self.commission
                gross_loss += abs(pnl)

            balance += pnl
            peak = max(peak, balance)
            dd = (peak - balance) / peak * 100 if peak > 0 else 0
            max_dd = max(max_dd, dd)
            equity.append(balance)

            trades.append(
                Trade(
                    entry_idx=i,
                    direction=direction,
                    entry_price=entry_price,
                    exit_price=exit_price,
                    pnl=pnl,
                    won=won,
                    confidence=conf,
                    reason=signal.get("reason", "")[:80],
                )
            )

            # Skip ahead by expiry to avoid overlapping trades
            i += self.expiry_bars + 1

        wins = sum(1 for t in trades if t.won)
        losses = len(trades) - wins
        win_rate = (wins / len(trades) * 100) if trades else 0.0
        total_return = (
            (balance - self.initial_balance) / self.initial_balance * 100
        )
        profit_factor = (
            gross_profit / gross_loss if gross_loss > 0 else float("inf")
        )
        avg_conf = (
            float(np.mean([t.confidence for t in trades])) if trades else 0.0
        )

        result = BacktestResult(
            total_trades=len(trades),
            wins=wins,
            losses=losses,
            win_rate=win_rate,
            total_return_pct=total_return,
            final_balance=balance,
            max_drawdown_pct=max_dd,
            profit_factor=profit_factor if profit_factor != float("inf") else 999.0,
            avg_confidence=avg_conf,
            trades=trades,
            equity_curve=equity,
        )
        logger.info(
            "Backtest %s: trades=%d win_rate=%.1f%% return=%.1f%% maxDD=%.1f%%",
            asset,
            result.total_trades,
            result.win_rate,
            result.total_return_pct,
            result.max_drawdown_pct,
        )
        return result

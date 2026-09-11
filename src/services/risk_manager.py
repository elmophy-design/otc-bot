"""Risk management service for professional signal filtering."""
from __future__ import annotations


class RiskManager:
    """Reject weak or unsafe trade setups before sending them to the user."""

    def __init__(
        self,
        account_balance: float = 1000.0,
        max_daily_loss: float = 150.0,
        max_risk_per_trade: float = 0.02,
    ):
        self.account_balance = float(account_balance)
        self.max_daily_loss = float(max_daily_loss)
        self.max_risk_per_trade = float(max_risk_per_trade)

    def should_block(self, risk_amount: float, confidence: float) -> bool:
        """Block unsafe setups when risk or confidence is outside the expected range."""
        risk_value = float(risk_amount or 0.0)
        confidence_value = float(confidence or 0.0)

        if risk_value <= 0:
            return False

        if self.account_balance > 0:
            risk_pct = risk_value / self.account_balance
            if risk_pct > self.max_risk_per_trade:
                return True

        if confidence_value < 60.0:
            return True

        return False

    def daily_loss_status(self, total_loss: float) -> str:
        """Return a simple status for the current daily loss state."""
        if total_loss >= self.max_daily_loss:
            return "LIMIT_REACHED"
        if total_loss >= self.max_daily_loss * 0.75:
            return "WARNING"
        return "OK"

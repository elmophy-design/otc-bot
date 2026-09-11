"""Message Formatting Utilities"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict


def format_signal_message(signal: Dict[str, Any]) -> str:
    """Format signal into a professional Telegram message."""
    action = signal.get("action", "NO_SIGNAL")
    asset = signal.get("asset", "Unknown")
    confidence = float(signal.get("confidence") or 0)
    reason = signal.get("reason", "Conditions not met")
    snapshot = signal.get("indicator_snapshot") or {}
    htf = signal.get("htf") or {}
    votes = signal.get("votes") or {}
    ts = signal.get("timestamp") or datetime.utcnow().isoformat()
    ts_display = ts[:19].replace("T", " ") if isinstance(ts, str) else str(ts)

    def _ind_line(snap: Dict) -> str:
        parts = []
        if "rsi" in snap:
            parts.append(f"RSI {snap['rsi']}")
        if "macd_hist" in snap:
            parts.append(f"MACD-H {snap['macd_hist']}")
        if "bb_position" in snap:
            parts.append(f"BB-pos {snap['bb_position']}")
        if "stoch_k" in snap:
            parts.append(f"Stoch {snap['stoch_k']}")
        if "adx" in snap:
            parts.append(f"ADX {snap['adx']}")
        return " · ".join(parts) if parts else "—"

    def _vote_line() -> str:
        if not votes:
            return ""
        vote_parts = []
        for key, value in votes.items():
            if value > 0:
                vote_parts.append(f"{key.upper()} bullish")
            elif value < 0:
                vote_parts.append(f"{key.upper()} bearish")
        return "\n📌 <b>Vote map:</b> " + ", ".join(vote_parts) if vote_parts else ""

    htf_line = ""
    if htf:
        bias = htf.get("bias", "NEUTRAL")
        bias_emoji = {"BULLISH": "🟢", "BEARISH": "🔴", "NEUTRAL": "⚪"}.get(bias, "⚪")
        htf_line = (
            f"\n🕰 <b>HTF {htf.get('timeframe', '?')}:</b> "
            f"{bias_emoji} {bias} (RSI {htf.get('rsi', '—')})"
        )

    if action == "NO_SIGNAL":
        snap_lines = ""
        if snapshot:
            snap_lines = "\n📈 <b>Indicators:</b> " + _ind_line(snapshot)
        return f"""
⏳ <b>No Signal — {asset}</b>
━━━━━━━━━━━━━━━━━━━━━
📊 <b>Reason:</b> {reason}{snap_lines}{_vote_line()}{htf_line}
🕐 <b>Time:</b> {ts_display} UTC

💡 <i>Conditions for a CALL or PUT are not currently met. Try again later.</i>
""".strip()

    action_emoji = "📈" if action == "CALL" else "📉"
    if confidence >= 80:
        conf_level, conf_emoji = "Very High", "🟢"
    elif confidence >= 75:
        conf_level, conf_emoji = "High", "🟢"
    elif confidence >= 65:
        conf_level, conf_emoji = "Medium", "🟡"
    else:
        conf_level, conf_emoji = "Low", "🔴"

    entry = signal.get("entry_price")
    entry_str = f"${entry:.5f}" if entry is not None else "n/a"
    ind_line = _ind_line(snapshot)

    return f"""
{action_emoji} <b>Signal — {asset}</b>
━━━━━━━━━━━━━━━━━━━━━
🎯 <b>Action:</b> {action}
📊 <b>Confidence:</b> {conf_emoji} {confidence:.1f}% ({conf_level})
💰 <b>Entry:</b> {entry_str}
📋 <b>Reason:</b> {reason}
📈 <b>Indicators:</b> {ind_line}{_vote_line()}{htf_line}
🕐 <b>Time:</b> {ts_display} UTC
━━━━━━━━━━━━━━━━━━━━━
⚠️ <i>Always use proper risk management. Demo first.</i>
""".strip()

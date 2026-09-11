"""Message Formatting Utilities"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from zoneinfo import ZoneInfo


def _resolve_tz(name: Optional[str] = None):
    """Resolve display timezone (default: local / Africa/Lagos for WAT)."""
    tz_name = (
        name
        or os.getenv("DISPLAY_TIMEZONE")
        or os.getenv("TZ")
        or "Africa/Lagos"  # WAT (UTC+1) – common for West Africa users
    )
    try:
        return ZoneInfo(tz_name)
    except Exception:
        try:
            # Fallback: system local
            return datetime.now().astimezone().tzinfo or timezone.utc
        except Exception:
            return timezone.utc


def format_local_time(ts: Any, tz_name: Optional[str] = None) -> str:
    """Convert ISO/UTC timestamp to local display string."""
    tz = _resolve_tz(tz_name)
    dt: Optional[datetime] = None

    if isinstance(ts, datetime):
        dt = ts
    elif isinstance(ts, (int, float)):
        dt = datetime.fromtimestamp(float(ts), tz=timezone.utc)
    elif isinstance(ts, str) and ts:
        try:
            # Handle "2026-09-10T14:34:00+00:00" / "...Z" / naive ISO
            cleaned = ts.replace("Z", "+00:00")
            dt = datetime.fromisoformat(cleaned)
        except Exception:
            return str(ts)[:19].replace("T", " ")

    if dt is None:
        dt = datetime.now(timezone.utc)

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    local = dt.astimezone(tz)
    # e.g. 2026-09-10 15:34:00 WAT
    label = getattr(tz, "key", None) or str(tz)
    short = label.split("/")[-1] if "/" in str(label) else str(label)
    # Prefer common abbreviations
    abbrev_map = {
        "Lagos": "WAT",
        "London": "BST/GMT",
        "New_York": "ET",
        "UTC": "UTC",
    }
    abbrev = abbrev_map.get(short, short)
    return f"{local.strftime('%Y-%m-%d %H:%M:%S')} {abbrev}"


def format_signal_message(signal: Dict[str, Any]) -> str:
    """Format signal into a professional Telegram message."""
    action = signal.get("action", "NO_SIGNAL")
    asset = signal.get("asset", "Unknown")
    confidence = float(signal.get("confidence") or 0)
    reason = signal.get("reason", "Conditions not met")
    snapshot = signal.get("indicator_snapshot") or {}
    htf = signal.get("htf") or {}
    votes = signal.get("votes") or {}
    ts = signal.get("timestamp") or datetime.now(timezone.utc).isoformat()
    ts_display = format_local_time(ts)
    timeframe = signal.get("timeframe") or "1m"
    expiry = signal.get("expiry_seconds") or signal.get("duration")

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

    tf_line = f"\n⏱ <b>Timeframe:</b> {timeframe}"
    if expiry:
        tf_line += f" · Expiry: {int(expiry)}s"

    if action == "NO_SIGNAL":
        snap_lines = ""
        if snapshot:
            snap_lines = "\n📈 <b>Indicators:</b> " + _ind_line(snapshot)
        return f"""
⏳ <b>No Signal — {asset}</b>
━━━━━━━━━━━━━━━━━━━━━
📊 <b>Reason:</b> {reason}{snap_lines}{_vote_line()}{htf_line}{tf_line}
🕐 <b>Time:</b> {ts_display}

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
📈 <b>Indicators:</b> {ind_line}{_vote_line()}{htf_line}{tf_line}
🕐 <b>Time:</b> {ts_display}
━━━━━━━━━━━━━━━━━━━━━
⚠️ <i>Always use proper risk management. Demo first.</i>
""".strip()

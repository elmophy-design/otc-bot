"""
PocketOption WebSocket protocol helpers (Socket.IO style).

Unofficial reverse-engineered message formats used by community clients.
SSID must be captured from the browser (DevTools → Network → WS → 42["auth"...]).
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple, Union

# Common demo/live WebSocket endpoints (may change by region)
DEFAULT_WS_URLS = [
    "wss://api-n.po.market/socket.io/?EIO=4&transport=websocket",
    "wss://demo-api-n.po.market/socket.io/?EIO=4&transport=websocket",
    "wss://api.po.market/socket.io/?EIO=4&transport=websocket",
]


@dataclass
class ParsedSSID:
    session: str
    uid: int
    is_demo: bool
    platform: int
    raw: str
    is_fast_history: bool = True
    is_optimized: bool = True


def parse_ssid(ssid: str) -> ParsedSSID:
    """
    Accept either:
      - Full wire string: 42["auth",{"session":"...","isDemo":1,"uid":123,...}]
      - Raw session token only (uid/demo must come from settings)
    """
    ssid = (ssid or "").strip()
    if not ssid:
        raise ValueError("Empty SSID")

    # Full Socket.IO auth payload
    if "auth" in ssid and "{" in ssid:
        match = re.search(r'42\s*\[\s*"auth"\s*,\s*(\{.*\})\s*\]', ssid, re.DOTALL)
        if not match:
            # Try without 42 prefix
            match = re.search(r'\[\s*"auth"\s*,\s*(\{.*\})\s*\]', ssid, re.DOTALL)
        if match:
            payload = json.loads(match.group(1))
            return ParsedSSID(
                session=str(payload.get("session", "")),
                uid=int(payload.get("uid") or 0),
                is_demo=bool(int(payload.get("isDemo", 1))),
                platform=int(payload.get("platform") or 1),
                raw=ssid,
                is_fast_history=bool(payload.get("isFastHistory", True)),
                is_optimized=bool(payload.get("isOptimized", True)),
            )

    # Raw session string
    return ParsedSSID(
        session=ssid,
        uid=0,
        is_demo=True,
        platform=1,
        raw=ssid,
    )


def build_auth_message(
    session: str,
    uid: int,
    is_demo: bool = True,
    platform: int = 1,
    is_fast_history: bool = True,
    is_optimized: bool = True,
) -> str:
    """Build Socket.IO EVENT auth frame (42 = EVENT)."""
    payload = {
        "session": session,
        "isDemo": 1 if is_demo else 0,
        "uid": int(uid),
        "platform": int(platform),
        "isFastHistory": bool(is_fast_history),
        "isOptimized": bool(is_optimized),
    }
    return '42["auth",' + json.dumps(payload, separators=(",", ":")) + "]"


def build_history_request(
    asset: str,
    period: int,
    end_time: Optional[int] = None,
    offset: int = 9000,
) -> str:
    """
    Build loadHistoryPeriod / candles history request.

    period: candle size in seconds (60 = 1m)
    offset: server window parameter (large values reduce timeouts)
    end_time: unix timestamp (seconds); defaults to now
    """
    end_time = end_time or int(time.time())
    # Community clients commonly use this shape
    body = {
        "asset": asset,
        "index": end_time,
        "time": end_time,
        "offset": offset,
        "period": period,
    }
    return '42["loadHistoryPeriod",' + json.dumps(body, separators=(",", ":")) + "]"


def build_subscribe_message(asset: str, period: int = 60) -> str:
    """Subscribe to asset stream for ticks / forming candles."""
    body = {"asset": asset, "period": period}
    return '42["changeSymbol",' + json.dumps(body, separators=(",", ":")) + "]"


def timeframe_to_seconds(tf: Union[str, int]) -> int:
    if isinstance(tf, int):
        return max(1, tf)
    tf = (tf or "1m").lower().strip()
    if tf.endswith("m"):
        return max(1, int(tf[:-1] or 1) * 60)
    if tf.endswith("h"):
        return max(1, int(tf[:-1] or 1) * 3600)
    if tf.endswith("s"):
        return max(1, int(tf[:-1] or 1))
    try:
        return max(1, int(tf))
    except ValueError:
        return 60


def parse_socketio_packet(raw: str) -> Tuple[Optional[str], Any]:
    """
    Parse a Socket.IO packet string.
    Returns (event_name_or_type, data).
    """
    if not raw:
        return None, None

    # Engine.IO open / ping / pong
    if raw[0] in ("0", "2", "3"):
        return raw[0], raw[1:] if len(raw) > 1 else None

    # Socket.IO EVENT: 42[...]
    if raw.startswith("42"):
        try:
            payload = json.loads(raw[2:])
            if isinstance(payload, list) and payload:
                event = payload[0] if isinstance(payload[0], str) else None
                data = payload[1] if len(payload) > 1 else None
                return event, data
        except json.JSONDecodeError:
            return "42", raw[2:]

    # MESSAGE / other
    if raw.startswith("42"):
        return "event", raw
    return "raw", raw


def candles_to_dataframe(candles: List[Dict[str, Any]]) -> "pd.DataFrame":
    """Convert list of candle dicts to normalized OHLCV DataFrame."""
    import pandas as pd

    if not candles:
        return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])

    rows = []
    for c in candles:
        # Support multiple community response shapes
        ts = c.get("time") or c.get("timestamp") or c.get("t") or c.get(0)
        o = c.get("open") or c.get("o") or c.get(1)
        h = c.get("high") or c.get("h") or c.get(3)
        l = c.get("low") or c.get("l") or c.get(4)
        cl = c.get("close") or c.get("c") or c.get(2)
        v = c.get("volume") or c.get("v") or 0

        # Array form: [ts, open, close, high, low]
        if isinstance(c, (list, tuple)) and len(c) >= 5:
            ts, o, cl, h, l = c[0], c[1], c[2], c[3], c[4]
            v = c[5] if len(c) > 5 else 0

        try:
            ts_f = float(ts)
            if ts_f > 1e12:  # ms
                ts_f /= 1000.0
            dt = datetime.fromtimestamp(ts_f, tz=timezone.utc)
        except Exception:
            dt = datetime.now(timezone.utc)

        rows.append(
            {
                "timestamp": dt,
                "open": float(o),
                "high": float(h),
                "low": float(l),
                "close": float(cl),
                "volume": float(v or 0),
            }
        )

    df = pd.DataFrame(rows)
    df = df.sort_values("timestamp").drop_duplicates(subset=["timestamp"], keep="last")
    return df.reset_index(drop=True)


def extract_candles_from_history_payload(data: Any) -> List[Dict[str, Any]]:
    """Best-effort extraction of candle list from various server response shapes."""
    if data is None:
        return []

    if isinstance(data, list):
        # Could be list of candles directly
        if data and (isinstance(data[0], (list, tuple, dict))):
            return list(data)
        return []

    if isinstance(data, dict):
        for key in ("candles", "history", "data", "raw", "result"):
            if key in data and isinstance(data[key], list):
                return list(data[key])
        # Nested
        if "data" in data and isinstance(data["data"], dict):
            return extract_candles_from_history_payload(data["data"])

    return []

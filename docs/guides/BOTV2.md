# BinaryOptionsTools-v2 Integration

## Overview

The bot can use **BinaryOptionsToolsV2** as the live PocketOption backend
instead of (or in addition to) the built-in Socket.IO client.

| `LIVE_BACKEND` | Behavior |
|----------------|----------|
| `auto` (default) | Use BotV2 if the package is installed **and** `POCKETOPTION_SSID` is set; otherwise native |
| `botv2` | Force BotV2 (falls back to native with a log error if missing) |
| `native` | Force built-in `PocketOptionClient` |

## Install

```bash
# From PyPI (when wheels are available)
pip install BinaryOptionsToolsV2

# Or from project helper
pip install -r requirements-live.txt

# Or from GitHub releases / source – see:
# https://github.com/ChipaDevTeam/BinaryOptionsTools-v2
```

## Configure

```bash
# .env
POCKETOPTION_SSID=42["auth",{"session":"...","isDemo":1,"uid":123,"platform":1}]
POCKETOPTION_USER_ID=123
DEMO_MODE=true
LIVE_BACKEND=auto
```

Keep **DEMO_MODE=true** until you have verified candle fetch on a demo SSID.

## Architecture

```
MarketDataFetcher
       │
       ▼
create_broker_client()  ──► BotV2Client  (BinaryOptionsToolsV2)
                       └─► PocketOptionClient (native protocol.py)
```

Both expose:
- `connect()` / `disconnect()`
- `is_connected`
- `get_candles(asset, timeframe, count) → DataFrame`

`BotV2Client` probes several method names (`get_candles`, `history`,
`candles`, `get_candles_live`) so minor upstream API differences do not break the bot.

## Smoke test

```bash
python scripts/test_live_backend.py
```

Without a real SSID / package, the script reports availability and exits cleanly.

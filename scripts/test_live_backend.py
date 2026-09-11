#!/usr/bin/env python3
"""Smoke-test live backend selection (no Telegram token required)."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config.settings import Settings
from src.api.botv2_adapter import botv2_available, botv2_import_error
from src.api.factory import create_broker_client, resolve_backend
from src.api.data_fetcher import MarketDataFetcher


async def main() -> None:
    settings = Settings(require_token=False)
    backend = resolve_backend(settings)
    print(f"LIVE_BACKEND resolved : {backend}")
    print(f"BotV2 available       : {botv2_available()}")
    if not botv2_available():
        print(f"BotV2 import error    : {botv2_import_error()}")
    print(f"DEMO_MODE             : {settings.DEMO_MODE}")
    ssid = settings.POCKETOPTION_SSID or ""
    print(f"SSID configured       : {bool(ssid) and 'your_ssid' not in ssid.lower()}")

    client = create_broker_client(settings)
    print(f"Client class          : {type(client).__name__}")

    connected = await client.connect()
    print(f"Connected             : {connected}")

    fetcher = MarketDataFetcher(client=client, demo_mode=settings.DEMO_MODE or not connected)
    df = await fetcher.get_historical_data("EURUSD_otc", "1m", 50)
    print(f"Candles returned      : {len(df)} rows")
    if not df.empty:
        print(df.tail(3).to_string(index=False))

    await client.disconnect()
    print("Done.")


if __name__ == "__main__":
    asyncio.run(main())

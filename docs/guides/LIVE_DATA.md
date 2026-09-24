# Live PocketOption Data Setup

## 1. Capture your SSID

1. Open [PocketOption](https://pocketoption.com) and log in (prefer **demo** account first).
2. Press **F12** → **Network** → filter **WS**.
3. Refresh or navigate until you see a WebSocket frame starting with:
   ```
   42["auth",{"session":"...","isDemo":1,"uid":123456,"platform":1}]
   ```
4. Copy the **entire** frame into `.env`:
   ```bash
   POCKETOPTION_SSID=42["auth",{"session":"...","isDemo":1,"uid":123456,"platform":1}]
   POCKETOPTION_USER_ID=123456
   DEMO_MODE=true
   ```

## 2. Run with live scaffolding

```bash
# Still safe – DEMO_MODE=true uses demo SSID + falls back to synthetic data if WS fails
python -m src.bot.main
```

When `DEMO_MODE=false` and a valid SSID is present, the client will:
1. Connect to `wss://api-n.po.market/socket.io/...` (and fallbacks)
2. Send the auth frame
3. Request candles via `loadHistoryPeriod`
4. Parse responses into OHLCV DataFrames for the signal engine

If the live request fails, the data fetcher **falls back to demo OHLCV** so the bot never crashes.

## 3. Protocol notes

This is an **unofficial** integration based on community reverse-engineering.
Message formats (`42["auth",...]`, `loadHistoryPeriod`) can change without notice.
Prefer demo accounts and never risk funds you cannot afford to lose.

## 4. Optional third-party libraries

For production-grade connectivity you may also integrate:
- [BinaryOptionsTools-v2](https://github.com/ChipaDevTeam/BinaryOptionsTools-v2)
- [chema-creator/PocketOptionApi](https://github.com/chema-creator/PocketOptionApi)

Wire them into `MarketDataFetcher._fetch_live` if preferred.

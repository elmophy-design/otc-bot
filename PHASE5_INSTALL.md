# Phase 5 — Live Market Workspace

Phase 5 adds the professional market workspace layer.

## Added
- Broker-backed OHLC candle endpoint: `/api/market/candles`
- Live market chart in the scanner
- 10-second chart refresh
- Last price, trend, RSI and strength telemetry
- Clear indication that candles are broker data only
- No second BotV2 connection
- No synthetic candles

## Apply
Overwrite the matching files in your existing project. No database migration is required.

## Test
```powershell
python -m py_compile src/web/api.py
cd frontend
npm run build
```

## Architecture
Render browser -> Next.js server proxy -> Railway dashboard API -> existing bot runtime -> BotV2 market data.

The dashboard remains read-only for chart data; execution continues through the protected trade workflow.

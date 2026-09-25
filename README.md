OTC Intelligence — Live Market Scanner Phase 1

Apply from the repository root:
  .\.venv\Scripts\python.exe .\apply_live_scanner.py

Verify:
  .\.venv\Scripts\python.exe -m py_compile .\frontend\src\web\market_scanner.py
  .\.venv\Scripts\python.exe -m py_compile .\frontend\src\web\api.py

Endpoints:
  GET /api/market/status
  GET /api/market/assets
  GET /api/market/scanner?timeframe=1m
  GET /api/market/assets/{asset}?timeframe=1m

Timeframes: 1m, 5m, 15m, 30m, 1h.

The scanner uses MarketDataFetcher with demo_mode=False. It therefore does
not turn synthetic/demo candles into "LIVE" dashboard data. Broker failure,
stale data, or missing candles is reported as DATA_UNAVAILABLE.

This is read-only Phase 1. It does not place trades and does not modify the
broker core.

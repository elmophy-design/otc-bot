# OTC Intelligence — Phase 6

Phase 6 upgrades the Phase 5 terminal with advanced market intelligence while preserving the single BotV2 session architecture.

## Backend files

Replace:

- `src/web/market_scanner.py`
- `src/web/api.py`

## Frontend files

Replace:

- `frontend/components/dashboard.tsx`
- `frontend/frontend_api.ts`
- `frontend/app/globals.css`

## What is included

- Richer 0–100 scanner scoring
- Trend structure / EMA alignment
- RSI and momentum scoring
- MACD confirmation
- Price-action scoring
- ATR volatility assessment
- ADX market-regime detection
- Bollinger position / width analysis
- Higher-timeframe confirmation
- A/B/C/D setup quality grade
- Conflict warnings
- CALL / PUT / WAIT contextual direction
- Multi-indicator market chart
- EMA20 / EMA50 / EMA100 overlays
- Bollinger Bands
- RSI / MACD / ATR indicator cards
- Fresh signal confidence breakdown
- Entry-quality assessment
- Expiry suitability guidance
- Recent signal history timeline
- Pending trade lifecycle panel
- Settlement countdown when `expiry_at` is available

## Architecture safety

The scanner and chart reuse the existing bot-owned runtime. Phase 6 does **not** create another BotV2 connection and does not move `POCKETOPTION_SSID` to the dashboard.

The dashboard remains a read/preview/execute client of the Railway trading engine.

## Install

No new Python package is required by Phase 6 beyond the existing NumPy/Pandas/FastAPI stack already used by the project.

For the frontend:

```bash
cd frontend
npm install
npm run build
```

Then commit and push the replaced files.

## Important

The scanner score is an analytical context score, not a guarantee of trade outcome. The existing fresh signal engine, risk manager, explicit trade confirmation, and broker settlement remain authoritative.

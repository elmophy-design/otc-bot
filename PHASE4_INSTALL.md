# OTC Intelligence Premium Terminal — Phase 4

Phase 4 turns the dashboard into the professional terminal layer while preserving the existing Railway execution architecture.

## Files changed
- `frontend/components/dashboard.tsx`
- `frontend/app/globals.css`

## Architecture preserved
- Railway owns the single BotV2 broker session.
- Railway owns market data, signal generation, risk validation, execution and settlement.
- Render/Next.js is the premium UI and server-side API proxy.
- Broker SSID is never placed in the browser.

## UI capabilities
- Command-center terminal home
- Live market radar
- Scanner with timeframes and search
- Fresh signal desk
- Protected trade preview and explicit execution confirmation
- Settlement-aware trade history
- Daily/weekly/monthly analytics
- Control center
- System health

## Apply
Extract the ZIP into the existing project and overwrite matching files.

Then from `frontend`:

```powershell
npm install
npm run build
```

From project root:

```powershell
python -m py_compile src/web/*.py src/bot/main.py
```

No new broker credentials are required for this phase.

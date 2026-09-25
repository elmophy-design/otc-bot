# OTC Intelligence — Phase 3

Phase 3 turns the dashboard into a real operational terminal using the existing Railway bot runtime.

## Included
- Live overview from authoritative trade reports
- Daily / weekly / monthly analytics
- Trade audit trail
- Live scanner with timeframe selection
- Fresh signal generation for selected asset
- Trade preview + explicit confirmation + execution
- User management read view
- Control Center safety architecture
- System health telemetry
- Next.js server-side proxy so the dashboard key is not exposed to the browser

## Manual overwrite
Copy the contents of this folder into the existing project and overwrite matching files.

## Important
Do not put `DASHBOARD_BACKEND_KEY` or the broker SSID into `NEXT_PUBLIC_*` variables.

Render frontend environment:
- `DASHBOARD_BACKEND_URL=https://YOUR-RAILWAY-DOMAIN`
- `DASHBOARD_BACKEND_KEY=YOUR_RAILWAY_DASHBOARD_ADMIN_KEY`

Railway:
- `DASHBOARD_API_ENABLED=true`
- `DASHBOARD_ADMIN_KEY=YOUR_LONG_RANDOM_SECRET`
- `DASHBOARD_OPERATOR_ID=YOUR_TELEGRAM_OPERATOR_ID`
- `DASHBOARD_CORS_ORIGINS=https://YOUR-RENDER-DOMAIN`

The existing BotV2 session remains owned by Railway.

## Frontend
From `frontend/`:

```powershell
npm install
npm run build
```

## Python syntax
From project root:

```powershell
python -m py_compile src/web/api.py src/web/market_scanner.py src/web/runtime.py src/bot/main.py
```

## Execution safety
Dashboard execution does not bypass the existing broker client. The API performs fresh signal generation, balance checks, configured trade amount checks, risk manager validation, explicit confirmation and duplicate-execution protection before calling `place_trade`.

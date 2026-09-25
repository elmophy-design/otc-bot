# Premium Dashboard — Phase 1

This phase establishes the production architecture:

- Railway remains the **single owner of the BotV2 broker session**.
- The Telegram bot, signal engine, market data fetcher, settlement worker and trade storage remain in the Railway process.
- A small authenticated FastAPI dashboard API now runs **inside that same process**.
- Render hosts only the Next.js UI.
- Render does **not** receive `POCKETOPTION_SSID`.
- The dashboard API accepts `X-Dashboard-Key` and reuses the existing runtime objects.
- The browser never receives the dashboard secret; Next.js proxies requests server-side.

## Railway environment variables

Keep all existing Telegram/Broker variables unchanged and add:

```env
DASHBOARD_API_ENABLED=true
DASHBOARD_ADMIN_KEY=<long-random-secret>
DASHBOARD_OPERATOR_ID=<numeric-dashboard-operator-id>
DASHBOARD_TELEGRAM_CHAT_ID=<optional-telegram-chat-id>
```

`DASHBOARD_OPERATOR_ID` is used to create the same `TradeHistory` audit records used by Telegram execution. `DASHBOARD_TELEGRAM_CHAT_ID` controls where settlement notifications for dashboard trades are delivered; if omitted, the operator ID is used as the chat ID.

Railway should expose the service's HTTP port using its normal `PORT` variable. The application binds Uvicorn to `0.0.0.0:$PORT`.

## Render environment variables

Create these on the Render **web service** only:

```env
RAILWAY_DASHBOARD_API_URL=https://<your-railway-public-domain>
RAILWAY_DASHBOARD_KEY=<same value as Railway DASHBOARD_ADMIN_KEY>
```

Do **not** use `NEXT_PUBLIC_` for the key.

## API surface in this phase

Authenticated:

- `GET /dashboard/health`
- `GET /dashboard/market/status`
- `GET /dashboard/market/assets`
- `GET /dashboard/market/scanner?timeframe=1m`
- `GET /dashboard/market/assets/{asset}?timeframe=1m`
- `POST /dashboard/market/signal`
- `POST /dashboard/trades/preview`
- `POST /dashboard/trades/execute`
- `GET /dashboard/analytics/report?period=daily|weekly|monthly`
- `GET /dashboard/trades/recent?limit=25`

Public:

- `GET /health` — intentionally returns only `{"status":"ok"}` for platform health checks.

## Important architecture rule

Do not deploy `api.py` or `market_scanner.py` as a second broker-connected service on Render. Those older files create their own broker connection. The Phase 1 dashboard API is `src/dashboard/api.py` and is hosted by the existing Railway process.

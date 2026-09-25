# OTC Intelligence — Phase 2

## What this phase changes

- The Railway Telegram bot remains the owner of the single BotV2/broker session.
- The dashboard API is started inside that same Python process and reuses the bot's existing API client, data fetcher, signal engine and storage.
- The scanner no longer creates a second broker connection when running inside the bot.
- Dashboard Overview uses real TradeHistory/settlement data instead of hard-coded metrics.
- Analytics uses authoritative daily/weekly/monthly trade reports from the existing storage layer.
- Trade History shows real records.
- Users page reads the live database.
- System Health reads the live broker connection.
- Next.js now proxies dashboard requests server-side, so the dashboard key is not exposed as `NEXT_PUBLIC_*` browser configuration.
- Existing scanner/signal/preview/execute UI is retained and now routes through the same-origin proxy.

## Overwrite

Copy the contents of this ZIP into the repository root and overwrite the matching files.

## Railway variables

Set:

```env
DASHBOARD_API_ENABLED=true
DASHBOARD_ADMIN_KEY=<long-random-secret>
DASHBOARD_OPERATOR_ID=<admin-telegram-id>
DASHBOARD_CORS_ORIGINS=https://YOUR-RENDER-DOMAIN.onrender.com
```

Keep the existing PocketOption/BotV2 variables on Railway. Do not put the broker SSID on Render.

Railway supplies `PORT` automatically.

## Render variables

For the Next.js service set these as **server-side environment variables**:

```env
DASHBOARD_BACKEND_URL=https://YOUR-RAILWAY-PUBLIC-DOMAIN
DASHBOARD_BACKEND_KEY=<same-long-random-secret>
```

Do not create `NEXT_PUBLIC_DASHBOARD_API_KEY` in production.

## Local checks

Backend:

```powershell
python -m py_compile src/web/*.py src/bot/main.py
```

Frontend:

```powershell
cd frontend
npm install
npm run build
```

Then run the bot normally. The dashboard API should listen on Railway's `PORT`; locally it defaults to port 8000.

# Phase 7 Part 2 — Professional Decision Desk

Replace these files in the existing dashboard:

- `frontend/components/dashboard.tsx`
- `frontend/frontend_api.ts`
- `frontend/app/globals.css`

Adds the Professional Decision Desk, ranked opportunities, regime/confluence/quality/risk display, explanations, no-trade conditions, expiry recommendation, asset comparison, full pre-trade checklist, Phase 7 trade preview, and explicit Railway execution confirmation.

Actual broker execution remains on Railway through the existing BotV2 session. The Render dashboard does not create another broker session.

Verify from `frontend`:

```powershell
npm install
npm run build
```

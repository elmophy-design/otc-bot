# OTC Intelligence — Dashboard User Management

This patch adds an authenticated admin HTTP API for adding, listing, editing, and deleting registered Telegram users from the dashboard.

## Backend changes

1. Add `fastapi` and `uvicorn` to `requirements.txt`.
2. Add the `src/web/` files from this patch.
3. Insert the methods in `storage_methods.txt` into `src/data/storage.py` inside `DataStorage`.
4. Add the settings in `settings_insert.txt` inside `Settings._load_environment()`.

Set in `.env`:

```env
DASHBOARD_ADMIN_KEY=use-a-long-random-secret
DASHBOARD_CORS_ORIGINS=http://localhost:3000
```

Start the API:

```powershell
python -m src.web.run
```

API: `http://127.0.0.1:8000`

Endpoints:
- `GET /health`
- `GET /api/admin/users`
- `POST /api/admin/users`
- `GET /api/admin/users/{telegram_id}`
- `PATCH /api/admin/users/{telegram_id}`
- `DELETE /api/admin/users/{telegram_id}`

All admin routes require `X-Dashboard-Key`.

## Frontend

Copy `frontend_api.ts` to `frontend/lib/dashboard-api.ts` and add:

```env
NEXT_PUBLIC_DASHBOARD_API_URL=http://127.0.0.1:8000
NEXT_PUBLIC_DASHBOARD_API_KEY=<same local development key>
```

The existing Users page can then call `getUsers()` and `createUser()` from an Add User modal.

For production, do not expose an admin secret in browser JavaScript. Put the API behind an authenticated server-side proxy or identity-aware reverse proxy first.

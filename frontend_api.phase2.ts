const DASHBOARD_API_URL =
  process.env.NEXT_PUBLIC_DASHBOARD_API_URL || "http://127.0.0.1:8000";
const DASHBOARD_API_KEY = process.env.NEXT_PUBLIC_DASHBOARD_API_KEY || "";

async function dashboardRequest(path: string, init: RequestInit = {}) {
  const response = await fetch(`${DASHBOARD_API_URL}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      "X-Dashboard-Key": DASHBOARD_API_KEY,
      ...(init.headers || {}),
    },
    cache: "no-store",
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.detail || `Dashboard API error (${response.status})`);
  return body;
}

export type DashboardUser = {
  id: number;
  telegram_id: string;
  username?: string | null;
  first_name?: string | null;
  last_name?: string | null;
  created_at?: string | null;
  last_active?: string | null;
};

export async function getUsers(limit = 100): Promise<DashboardUser[]> {
  const body = await dashboardRequest(`/api/admin/users?limit=${limit}`);
  return body.users;
}

export async function createUser(input: {
  telegram_id: number;
  username?: string;
  first_name?: string;
  last_name?: string;
}): Promise<DashboardUser> {
  const body = await dashboardRequest("/api/admin/users", {
    method: "POST",
    body: JSON.stringify(input),
  });
  return body.user;
}

export async function updateUser(
  telegramId: string,
  input: { username?: string; first_name?: string; last_name?: string }
): Promise<DashboardUser> {
  const body = await dashboardRequest(`/api/admin/users/${telegramId}`, {
    method: "PATCH",
    body: JSON.stringify(input),
  });
  return body.user;
}

export async function deleteUser(telegramId: string) {
  return dashboardRequest(`/api/admin/users/${telegramId}`, { method: "DELETE" });
}

export type ScannerRow = {
  asset: string;
  market?: string;
  bias?: string;
  strength?: number | null;
  rsi?: number | null;
  macd?: number | null;
  trend?: string;
  volatility?: number | null;
  readiness?: string;
  price?: number | null;
  timestamp?: string | null;
  [key: string]: unknown;
};

export type ScannerResponse = {
  timeframe: string;
  status?: string;
  assets?: ScannerRow[];
  scanner?: ScannerRow[];
  rows?: ScannerRow[];
  last_update?: string | null;
  [key: string]: unknown;
};

export type MarketStatus = {
  status?: string;
  connected?: boolean;
  market_feed?: string;
  assets_tracked?: number;
  last_update?: string | null;
  [key: string]: unknown;
};

export async function getMarketStatus(): Promise<MarketStatus> {
  return dashboardRequest("/api/market/status");
}

export async function getMarketScanner(timeframe = "1m"): Promise<ScannerResponse> {
  return dashboardRequest(`/api/market/scanner?timeframe=${encodeURIComponent(timeframe)}`);
}

export async function getMarketAsset(asset: string, timeframe = "1m") {
  return dashboardRequest(
    `/api/market/assets/${encodeURIComponent(asset)}?timeframe=${encodeURIComponent(timeframe)}`
  );
}

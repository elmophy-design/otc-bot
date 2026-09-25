const DASHBOARD_PROXY = "/api/dashboard";

async function dashboardRequest(path: string, init: RequestInit = {}) {
  const response = await fetch(`${DASHBOARD_PROXY}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init.headers || {}),
    },
    cache: "no-store",
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(body.detail || `Dashboard API error (${response.status})`);
  }
  return body;
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
  updated_at?: string | null;
  [key: string]: unknown;
};

export type ScannerResponse = {
  timeframe: string;
  status?: string;
  assets_tracked?: number;
  ready?: number;
  assets?: ScannerRow[];
  scanner?: ScannerRow[];
  rows?: ScannerRow[];
  last_update?: string | null;
  updated_at?: string | null;
  [key: string]: unknown;
};

export type MarketStatus = {
  status?: string;
  connected?: boolean;
  demo_mode?: boolean;
  market_feed?: string;
  assets_tracked?: number;
  last_update?: string | null;
  updated_at?: string | null;
  [key: string]: unknown;
};

export type MarketSignal = {
  status: string;
  asset: string;
  timeframe: string;
  signal: {
    action: "CALL" | "PUT" | "NO_SIGNAL" | string;
    confidence?: number | null;
    reason?: string | null;
    entry_price?: number | null;
    timestamp?: string | null;
    indicator_snapshot?: Record<string, unknown>;
    votes?: Record<string, number>;
    confluence_score?: number | null;
    htf?: Record<string, unknown> | null;
    [key: string]: unknown;
  };
  generated_at?: string | null;
};

export type TradePreview = {
  allowed: boolean;
  reasons: string[];
  asset: string;
  timeframe: string;
  amount: number;
  duration: number;
  balance: number | null;
  signal: MarketSignal["signal"] | null;
  demo_mode: boolean;
};

export type TradeExecution = {
  success: boolean;
  trade_id: string;
  trade_history_id: number;
  asset: string;
  direction: "CALL" | "PUT";
  amount: number;
  duration: number;
  entry_price?: number | null;
  confidence: number;
  demo_mode: boolean;
  placed_at: string;
};

export async function getMarketStatus(): Promise<MarketStatus> {
  return dashboardRequest("/market/status");
}

export async function getMarketScanner(timeframe = "1m"): Promise<ScannerResponse> {
  return dashboardRequest(`/market/scanner?timeframe=${encodeURIComponent(timeframe)}`);
}

export async function getMarketAsset(asset: string, timeframe = "1m") {
  return dashboardRequest(
    `/market/assets/${encodeURIComponent(asset)}?timeframe=${encodeURIComponent(timeframe)}`,
  );
}

export async function generateMarketSignal(asset: string, timeframe = "1m"): Promise<MarketSignal> {
  return dashboardRequest(
    `/market/signal?asset=${encodeURIComponent(asset)}&timeframe=${encodeURIComponent(timeframe)}`,
    { method: "POST" },
  );
}

export async function previewTrade(input: {
  asset: string;
  timeframe: string;
  amount: number;
  duration: number;
}): Promise<TradePreview> {
  return dashboardRequest("/trades/preview", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export async function executeTrade(input: {
  asset: string;
  timeframe: string;
  amount: number;
  duration: number;
  direction: "CALL" | "PUT";
  confirm: boolean;
}): Promise<TradeExecution> {
  return dashboardRequest("/trades/execute", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export async function getAnalyticsReport(period: "daily" | "weekly" | "monthly" = "daily") {
  return dashboardRequest(`/analytics/report?period=${period}`);
}

export async function getRecentTrades(limit = 25) {
  return dashboardRequest(`/trades/recent?limit=${limit}`);
}

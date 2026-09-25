# frontend_api.ts additions

export async function getMarketStatus() {
  return dashboardRequest("/api/market/status");
}

export async function getMarketAssets(): Promise<string[]> {
  const body = await dashboardRequest("/api/market/assets");
  return body.assets;
}

export async function getMarketScanner(timeframe = "1m") {
  return dashboardRequest(`/api/market/scanner?timeframe=${encodeURIComponent(timeframe)}`);
}

export async function getMarketAsset(asset: string, timeframe = "1m") {
  return dashboardRequest(
    `/api/market/assets/${encodeURIComponent(asset)}?timeframe=${encodeURIComponent(timeframe)}`
  );
}

# Also fix the existing updateUser() call:
# method: "PATCH", body: JSON.stringify(input)

const API_BASE = "/api/dashboard";

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, { ...init, cache: "no-store", headers: { "Content-Type": "application/json", ...(init.headers || {}) } });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.detail || `Dashboard API error (${response.status})`);
  return body as T;
}

export type ScannerRow = { asset:string; market?:string; bias?:string; strength?:number|null; rsi?:number|null; macd?:number|null; trend?:string; volatility?:number|null; readiness?:string; price?:number|null; timestamp?:string|null; [key:string]:unknown };
export type Trade = { id:number; asset:string; direction:string; amount:number; result:string; profit_loss:number|null; payout:number|null; placed_at:string|null; expiry_at:string|null; closed_at:string|null; order_id?:string|null; settlement_source?:string|null; broker_result?:string|null; settlement_attempts?:number };
export type Report = { total:number; settled:number; wins:number; losses:number; draws:number; pending:number; unresolved:number; win_rate:number; stake:number; settled_stake:number; payout:number; net_pl:number; call:{total:number;wins:number;losses:number;draws:number;win_rate:number}; put:{total:number;wins:number;losses:number;draws:number;win_rate:number}; by_asset:Record<string,unknown>; trades:Trade[] };
export type Overview = { mode:string; broker_connected:boolean; assets_tracked:number; users:{count:number}; daily:Report; weekly:Report; monthly:Report; recent_trades:Trade[]; updated_at:string };

export async function getOverview(){ return request<Overview>("/dashboard/overview"); }
export async function getAnalytics(period:"daily"|"weekly"|"monthly"){ return request<{period:string;report:Report;updated_at:string}>(`/analytics?period=${period}`); }
export async function getMarketStatus(){ return request<any>("/market/status"); }
export async function getMarketScanner(timeframe="1m"){ return request<any>(`/market/scanner?timeframe=${encodeURIComponent(timeframe)}`); }
export async function getMarketAsset(asset:string,timeframe="1m"){ return request<any>(`/market/assets/${encodeURIComponent(asset)}?timeframe=${encodeURIComponent(timeframe)}`); }
export type Candle = { time:string|null; open:number; high:number; low:number; close:number; volume:number|null };
export async function getMarketCandles(asset:string,timeframe="1m",count=120){ return request<{status:string;asset:string;timeframe:string;count:number;candles:Candle[];updated_at:string}>(`/market/candles?asset=${encodeURIComponent(asset)}&timeframe=${encodeURIComponent(timeframe)}&count=${count}`); }
export async function getSignal(asset:string,timeframe="1m"){ return request<any>(`/market/signal?asset=${encodeURIComponent(asset)}&timeframe=${encodeURIComponent(timeframe)}`,{method:"POST"}); }
export async function previewTrade(payload:{asset:string;timeframe:string;amount:number;duration:number}){ return request<any>("/market/trade/preview",{method:"POST",body:JSON.stringify(payload)}); }
export async function executeTrade(payload:{asset:string;timeframe:string;amount:number;duration:number;confirm:boolean}){ return request<any>("/market/trade/execute",{method:"POST",body:JSON.stringify(payload)}); }
export async function getUsers(limit=500){ return request<any>(`/admin/users?limit=${limit}`); }
export async function getHealth(){ return request<any>("/health"); }

export async function getSignalHistory(limit=25){ return request<any>(`/market/signal/history?limit=${limit}`); }
export async function getPendingTrades(){ return request<any>("/market/pending"); }

// PHASE 7 — Professional Decision & Execution Layer
export async function getPhase7Decision(asset:string,timeframe="1m"){
  return request<any>(`/phase7/decision/${encodeURIComponent(asset)}?timeframe=${encodeURIComponent(timeframe)}`);
}
export async function getPhase7Opportunities(timeframe="1m",limit=10){
  return request<any>(`/phase7/opportunities?timeframe=${encodeURIComponent(timeframe)}&limit=${limit}`);
}
export async function getPhase7TradePreview(payload:{asset:string;timeframe:string;amount:number;duration:number}){
  return request<any>("/phase7/trade-preview",{method:"POST",body:JSON.stringify(payload)});
}
export async function getPhase7Compare(assets:string[],timeframe="1m"){
  return request<any>(`/phase7/compare?assets=${encodeURIComponent(assets.join(","))}&timeframe=${encodeURIComponent(timeframe)}`);
}
export async function getPhase7Journal(period:"daily"|"weekly"|"monthly"="daily",limit=100){
  return request<any>(`/phase7/journal?period=${period}&limit=${limit}`);
}

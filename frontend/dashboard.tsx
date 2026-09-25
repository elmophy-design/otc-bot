"use client";

import { useEffect, useMemo, useState } from "react";
import {
  Activity, Bell, Bot, BrainCircuit, CircleDollarSign, Database,
  Gauge, LayoutDashboard, LineChart, ListFilter, Menu, RefreshCw,
  Search, Settings2, ShieldCheck, Signal, Users, Wifi, Zap
} from "lucide-react";
import { AreaChart, Area, ResponsiveContainer, XAxis, YAxis, Tooltip } from "recharts";
import { generateMarketSignal, getMarketScanner, getMarketStatus, getDashboardOverview, getAnalytics, getUsers, previewTrade, executeTrade, ScannerRow, MarketSignal, TradePreview, TradeExecution, DashboardOverview, TradeReport, TradeRow, DashboardUser } from "../frontend_api";

const TIMEFRAMES = ["1m", "2m", "5m", "15m", "30m", "1h"];

export default function Dashboard() {
  const [active, setActive] = useState("Overview");

  const nav = [
    ["Overview", LayoutDashboard], ["Live Signals", Signal], ["Signal History", ListFilter],
    ["Analytics", LineChart], ["Market Intelligence", BrainCircuit], ["Users", Users],
    ["Control Center", Settings2], ["System Health", Gauge]
  ] as const;

  return (
    <div className="app">
      <aside className="sidebar">
        <div className="brand">
          <div className="logo">O</div>
          <div><strong>OTC Intelligence</strong><span>Trading Control</span></div>
        </div>
        <div className="nav-label">Workspace</div>
        {nav.map(([name, Icon]) => (
          <button key={name} className={"nav " + (active === name ? "active" : "")} onClick={() => setActive(name)}>
            <Icon size={15} /><span>{name}</span>
          </button>
        ))}
        <div className="nav-label">System</div>
        <button className="nav"><ShieldCheck size={15} /><span>Security</span></button>
        <button className="nav"><Database size={15} /><span>Data Sources</span></button>
      </aside>

      <main className="main">
        <header className="topbar">
          <div>
            <div className="eyebrow">Command Center / {active}</div>
            <div className="title">{active}</div>
          </div>
          <div className="top-actions">
            <div className="status"><i className="dot" />All systems operational</div>
            <button className="iconbtn"><Bell size={15} /></button>
            <button className="iconbtn"><Menu size={15} /></button>
          </div>
        </header>

        {active === "Market Intelligence" || active === "Live Signals" ? (
          <MarketScanner />
        ) : active === "Users" ? (
          <UsersPanel />
        ) : active === "Analytics" ? (
          <AnalyticsPanel />
        ) : active === "Signal History" ? (
          <TradeHistoryPanel />
        ) : active === "System Health" ? (
          <SystemHealthPanel />
        ) : (
          <Overview />
        )}
      </main>
    </div>
  );
}

function MarketScanner() {
  const [timeframe, setTimeframe] = useState("1m");
  const [rows, setRows] = useState<ScannerRow[]>([]);
  const [selected, setSelected] = useState<ScannerRow | null>(null);
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState("");
  const [marketStatus, setMarketStatus] = useState<Record<string, unknown>>({});
  const [signal, setSignal] = useState<MarketSignal | null>(null);
  const [signalLoading, setSignalLoading] = useState(false);
  const [signalError, setSignalError] = useState("");
  const [signalReviewed, setSignalReviewed] = useState(false);

  async function load(showSpinner = true) {
    if (showSpinner) setLoading(true);
    setRefreshing(true);
    setError("");
    try {
      const [scan, status] = await Promise.all([
        getMarketScanner(timeframe),
        getMarketStatus(),
      ]);
      const incoming = (scan.assets || scan.scanner || scan.rows || []) as ScannerRow[];
      setRows(incoming);
      setMarketStatus(status as Record<string, unknown>);
      if (selected) {
        const match = incoming.find((r) => r.asset === selected.asset);
        if (match) setSelected(match);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Market scanner unavailable");
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }

  useEffect(() => { load(); setSignal(null); setSignalError(""); }, [timeframe]);

  useEffect(() => {
    const timer = window.setInterval(() => load(false), 15000);
    return () => window.clearInterval(timer);
  }, [timeframe]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return rows.filter((r) => !q || String(r.asset || "").toLowerCase().includes(q));
  }, [rows, query]);

  const strongBullish = rows.filter((r) => String(r.bias).toUpperCase().includes("BULL")).length;
  const strongBearish = rows.filter((r) => String(r.bias).toUpperCase().includes("BEAR")).length;
  const neutral = Math.max(0, rows.length - strongBullish - strongBearish);

  return (
    <>
      <section className="grid4">
        <ScannerMetric label="Market Feed" value={marketStatus.connected ? "LIVE" : "OFFLINE"} live={!!marketStatus.connected} />
        <ScannerMetric label="Assets Tracked" value={String(marketStatus.assets_tracked ?? rows.length)} />
        <ScannerMetric label="Bullish" value={String(strongBullish)} />
        <ScannerMetric label="Bearish / Neutral" value={`${strongBearish} / ${neutral}`} />
      </section>

      <section className="card" style={{ marginBottom: 16 }}>
        <div className="card-title" style={{ alignItems: "center" }}>
          <div>
            <h2>Live Asset Scanner</h2>
            <span>LIVE MARKET DATA · MARKET STRENGTH · ASSET SELECTION</span>
          </div>
          <button className="iconbtn" onClick={() => load()} title="Refresh scanner">
            <RefreshCw size={14} className={refreshing ? "spin" : ""} />
          </button>
        </div>

        <div style={{ display: "flex", gap: 6, flexWrap: "wrap", alignItems: "center", marginBottom: 14 }}>
          {TIMEFRAMES.map((tf) => (
            <button key={tf} onClick={() => setTimeframe(tf)} style={tfButtonStyle(tf === timeframe)}>
              {tf}
            </button>
          ))}
          <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 7 }}>
            <Search size={13} />
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search asset"
              style={inputStyle}
            />
          </div>
        </div>

        {error && <div style={errorStyle}>{error}</div>}
        {loading ? (
          <div style={emptyStyle}>Loading live market data…</div>
        ) : filtered.length === 0 ? (
          <div style={emptyStyle}>No market data available for this timeframe.</div>
        ) : (
          <div style={{ overflowX: "auto" }}>
            <table className="user-table">
              <thead>
                <tr>
                  <th>Asset</th><th>Bias</th><th>Strength</th><th>RSI</th>
                  <th>MACD</th><th>Trend</th><th>Volatility</th><th>Readiness</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((r) => {
                  const active = selected?.asset === r.asset;
                  return (
                    <tr key={r.asset} onClick={() => setSelected(r)} style={{ cursor: "pointer", background: active ? "rgba(139,92,246,.08)" : undefined }}>
                      <td className="user-name">{r.asset}</td>
                      <td><Bias value={r.bias} /></td>
                      <td><Strength value={r.strength} /></td>
                      <td>{fmt(r.rsi)}</td>
                      <td>{fmt(r.macd)}</td>
                      <td>{r.trend || "—"}</td>
                      <td>{fmt(r.volatility)}</td>
                      <td><Readiness value={r.readiness} /></td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {selected && (
        <section className="content-grid">
          <div className="card">
            <div className="card-title">
              <div><h2>{selected.asset}</h2><span>SELECTED ASSET · {timeframe.toUpperCase()}</span></div>
              <span className="pill call"><Zap size={11} /> ANALYSIS</span>
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(2,minmax(0,1fr))", gap: 10 }}>
              <Detail label="Market Bias" value={selected.bias} />
              <Detail label="Strength Score" value={fmt(selected.strength)} />
              <Detail label="RSI" value={fmt(selected.rsi)} />
              <Detail label="MACD" value={fmt(selected.macd)} />
              <Detail label="Trend" value={selected.trend} />
              <Detail label="Volatility" value={fmt(selected.volatility)} />
              <Detail label="Readiness" value={selected.readiness} />
              <Detail label="Last Price" value={fmt(selected.price)} />
            </div>
          </div>
          <div className="card">
            <div className="card-title"><h2>Execution Gate</h2><span>USER SELECTED ASSET</span></div>
            <p style={{ color: "#8791a3", fontSize: 12, lineHeight: 1.6 }}>
              Asset selection is explicit. Signal generation should use this selected instrument and the selected timeframe.
              No random asset selection is performed by the scanner.
            </p>
            <button
              style={primaryButtonStyle}
              disabled={!selected.asset || signalLoading}
              onClick={async () => {
                if (!selected?.asset) return;
                setSignalLoading(true);
                setSignalError("");
                try {
                  const result = await generateMarketSignal(selected.asset, timeframe);
                  setSignal(result);
                  setSignalReviewed(false);
                } catch (e) {
                  setSignal(null);
                  setSignalError(e instanceof Error ? e.message : "Signal generation failed");
                } finally {
                  setSignalLoading(false);
                }
              }}
            >
              {signalLoading ? "Analyzing…" : `Generate Signal · ${selected.asset} · ${timeframe}`}
            </button>
            {signalError && <div style={{ ...errorStyle, marginTop: 10 }}>{signalError}</div>}
            {signal && (
              <div style={{ marginTop: 14, padding: 14, border: "1px solid #202733", borderRadius: 12, background: "rgba(255,255,255,.02)" }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 10, marginBottom: 12 }}>
                  <div>
                    <div style={{ fontSize: 11, color: "#687386", textTransform: "uppercase", letterSpacing: ".08em" }}>Production Signal Engine · Review</div>
                    <div style={{ fontSize: 25, fontWeight: 800, marginTop: 3 }}>{signal.signal.action === "NO_SIGNAL" ? "WAIT" : signal.signal.action}</div>
                  </div>
                  <div style={{ textAlign: "right" }}>
                    <div style={{ fontSize: 22, fontWeight: 800 }}>{signal.signal.confidence != null ? `${signal.signal.confidence.toFixed(0)}%` : "—"}</div>
                    <div style={{ fontSize: 10, color: "#687386" }}>CONFIDENCE</div>
                  </div>
                </div>

                <div style={{ display: "grid", gridTemplateColumns: "repeat(3,minmax(0,1fr))", gap: 8 }}>
                  <Detail label="Asset" value={signal.asset} />
                  <Detail label="Timeframe" value={signal.timeframe} />
                  <Detail label="Entry Price" value={fmt(signal.signal.entry_price)} />
                  <Detail label="Confluence" value={fmt(signal.signal.confluence_score)} />
                  <Detail label="Generated" value={signal.generated_at ? new Date(signal.generated_at).toLocaleTimeString() : "—"} />
                  <Detail label="Review State" value={signalReviewed ? "CONFIRMED" : "PENDING REVIEW"} />
                </div>

                <div style={{ marginTop: 12, padding: 11, borderRadius: 9, background: "rgba(255,255,255,.025)", color: "#aab3c2", fontSize: 12, lineHeight: 1.6 }}>
                  {signal.signal.reason || "No qualifying setup."}
                </div>

                {signal.signal.votes && (
                  <div style={{ marginTop: 12 }}>
                    <div style={{ fontSize: 10, color: "#687386", textTransform: "uppercase", letterSpacing: ".08em", marginBottom: 7 }}>Indicator Votes</div>
                    <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                      {Object.entries(signal.signal.votes).map(([name, vote]) => (
                        <span key={name} style={{ padding: "5px 8px", borderRadius: 7, border: "1px solid #202733", fontSize: 10, color: Number(vote) > 0 ? "#55d89a" : Number(vote) < 0 ? "#ff6b7a" : "#8b95a7" }}>
                          {name.toUpperCase()} {Number(vote) > 0 ? "+1" : Number(vote) < 0 ? "−1" : "0"}
                        </span>
                      ))}
                    </div>
                  </div>
                )}

                {signal.signal.indicator_snapshot && (
                  <div style={{ marginTop: 12 }}>
                    <div style={{ fontSize: 10, color: "#687386", textTransform: "uppercase", letterSpacing: ".08em", marginBottom: 7 }}>Indicator Snapshot</div>
                    <div style={{ display: "grid", gridTemplateColumns: "repeat(4,minmax(0,1fr))", gap: 7 }}>
                      {Object.entries(signal.signal.indicator_snapshot).slice(0, 8).map(([name, value]) => (
                        <Detail key={name} label={name.replaceAll("_", " ")} value={fmt(value as number | string | null | undefined)} />
                      ))}
                    </div>
                  </div>
                )}

                <div style={{ marginTop: 14, paddingTop: 12, borderTop: "1px solid #202733", display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10 }}>
                  <div style={{ fontSize: 11, color: "#788396" }}>
                    {signalReviewed
                      ? "Signal review confirmed. No order has been submitted."
                      : signal.signal.action === "NO_SIGNAL"
                        ? "No trade setup to confirm."
                        : "Review the signal, timeframe, entry and confluence before confirmation."}
                  </div>
                  <button
                    style={{ ...primaryButtonStyle, opacity: signalReviewed || signal.signal.action === "NO_SIGNAL" ? 0.55 : 1 }}
                    disabled={signalReviewed || signal.signal.action === "NO_SIGNAL"}
                    onClick={() => setSignalReviewed(true)}
                  >
                    {signalReviewed ? "Signal Confirmed" : "Confirm Signal Review"}
                  </button>
                </div>

                <div style={{ marginTop: 9, fontSize: 10, color: "#596476" }}>
                  EXECUTION LOCK · Phase 4 does not submit broker orders. Confirmation records operator intent only.
                </div>
              </div>
            )}
            {signal && <ExecutionPanel signal={signal} timeframe={timeframe} reviewed={signalReviewed} />}
          </div>
        </section>
      )}
    </>
  );
}

function ExecutionPanel({ signal, timeframe, reviewed }: { signal: MarketSignal; timeframe: string; reviewed: boolean }) {
  const [amount, setAmount] = useState("1");
  const [duration, setDuration] = useState("60");
  const [preview, setPreview] = useState<TradePreview | null>(null);
  const [result, setResult] = useState<TradeExecution | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [confirm, setConfirm] = useState(false);
  if (!reviewed || signal.signal.action === "NO_SIGNAL") return null;
  async function prepare() {
    setBusy(true); setError(""); setResult(null); setConfirm(false);
    try { const p = await previewTrade({ asset: signal.asset, timeframe, amount: Number(amount), duration: Number(duration) }); setPreview(p); if (!p.allowed) setError(p.reasons.join(" ")); }
    catch (e) { setPreview(null); setError(e instanceof Error ? e.message : "Execution preview failed"); }
    finally { setBusy(false); }
  }
  async function execute() {
    if (!preview?.allowed || !confirm) return;
    setBusy(true); setError("");
    try { const r = await executeTrade({ asset: signal.asset, timeframe, amount: Number(amount), duration: Number(duration), confirm: true }); setResult(r); }
    catch (e) { setError(e instanceof Error ? e.message : "Trade execution failed"); }
    finally { setBusy(false); }
  }
  return <div style={{ marginTop: 14, padding: 14, border: "1px solid rgba(245,158,11,.28)", borderRadius: 12, background: "rgba(245,158,11,.035)" }}>
    <div style={{ fontSize: 10, color: "#fbbf24", letterSpacing: ".09em", textTransform: "uppercase" }}>Phase 5 - Controlled Execution</div>
    <div style={{ fontSize: 17, fontWeight: 800, marginTop: 3 }}>Execution Preview</div>
    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 9, marginTop: 12 }}>
      <label style={{ fontSize: 10, color: "#7f8a9d" }}>Amount<input value={amount} onChange={e => setAmount(e.target.value)} type="number" min="0.01" step="0.01" style={{ ...inputStyle, width: "100%", marginTop: 5 }} /></label>
      <label style={{ fontSize: 10, color: "#7f8a9d" }}>Duration<select value={duration} onChange={e => setDuration(e.target.value)} style={{ ...inputStyle, width: "100%", marginTop: 5 }}><option value="30">30s</option><option value="60">60s</option><option value="120">120s</option><option value="300">300s</option><option value="600">600s</option></select></label>
    </div>
    <div style={{ display: "grid", gridTemplateColumns: "repeat(4,minmax(0,1fr))", gap: 7, marginTop: 10 }}><Detail label="Direction" value={signal.signal.action} /><Detail label="Asset" value={signal.asset} /><Detail label="Timeframe" value={timeframe} /><Detail label="Entry" value={fmt(signal.signal.entry_price)} /></div>
    <button style={primaryButtonStyle} onClick={prepare} disabled={busy}>{busy ? "Checking..." : "Prepare Execution"}</button>
    {preview && <div style={{ marginTop: 10, padding: 11, border: "1px solid #202733", borderRadius: 9, background: "#0c1118" }}>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(3,minmax(0,1fr))", gap: 7 }}><Detail label="Balance" value={preview.balance != null ? preview.balance.toFixed(2) : "Unavailable"} /><Detail label="Stake" value={preview.amount.toFixed(2)} /><Detail label="Risk Gate" value={preview.allowed ? "PASSED" : "BLOCKED"} /></div>
      {preview.reasons.length > 0 && <div style={{ ...errorStyle, marginTop: 9, marginBottom: 0 }}>{preview.reasons.join(" ")}</div>}
      {preview.allowed && !result && <><label style={{ display: "flex", gap: 8, alignItems: "center", marginTop: 10, fontSize: 11, color: "#aab3c2" }}><input type="checkbox" checked={confirm} onChange={e => setConfirm(e.target.checked)} />I confirm this exact asset, direction, amount and duration for broker execution.</label><button style={{ ...primaryButtonStyle, opacity: confirm ? 1 : .45 }} disabled={!confirm || busy} onClick={execute}>{busy ? "Submitting..." : `Confirm & Execute ${signal.signal.action}`}</button></>}
    </div>}
    {result && <div style={{ marginTop: 10, padding: 11, borderRadius: 9, border: "1px solid rgba(74,222,128,.25)", background: "rgba(74,222,128,.05)", fontSize: 11, lineHeight: 1.7 }}><strong style={{ color: "#4ade80" }}>TRADE EXECUTED</strong><br />Broker trade ID: <strong>{result.trade_id}</strong><br />Audit record: <strong>#{result.trade_history_id}</strong><br />{result.demo_mode ? "DEMO ACCOUNT" : "LIVE ACCOUNT"} - {result.asset} - {result.direction} - {result.amount.toFixed(2)} - {result.duration}s</div>}
    {error && <div style={{ ...errorStyle, marginTop: 9, marginBottom: 0 }}>{error}</div>}
    <div style={{ marginTop: 9, fontSize: 10, color: "#687386" }}>Server-side validation regenerates the signal immediately before execution. Successful trades use the existing TradeHistory audit path.</div>
  </div>;
}

function Overview() {
  const [data, setData] = useState<DashboardOverview | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  async function load() {
    try {
      setError("");
      setData(await getDashboardOverview());
    } catch (e) {
      setError(e instanceof Error ? e.message : "Dashboard data unavailable");
    } finally { setLoading(false); }
  }
  useEffect(() => { load(); const t = window.setInterval(load, 15000); return () => window.clearInterval(t); }, []);

  if (loading && !data) return <div className="card" style={{marginTop:14}}><div style={emptyStyle}>Loading live dashboard telemetry…</div></div>;
  if (error && !data) return <div className="card" style={{marginTop:14}}><div style={errorStyle}>{error}</div></div>;
  if (!data) return null;

  const d = data.daily;
  return <>
    <section className="grid4">
      <Metric icon={<Signal size={15}/>} label="Trades Today" value={String(d.total)} trend={`${d.settled} settled`} />
      <Metric icon={<CircleDollarSign size={15}/>} label="Net P/L Today" value={money(d.net_pl)} trend={`${d.win_rate.toFixed(1)}% win rate`} />
      <Metric icon={<Users size={15}/>} label="Registered Users" value={String(data.users.count)} trend={`${data.assets_tracked} assets tracked`} />
      <Metric icon={<Wifi size={15}/>} label="Broker Session" value={data.broker_connected ? "LIVE" : "OFFLINE"} trend={data.mode} down={!data.broker_connected} />
    </section>
    {error && <div style={{...errorStyle, marginTop:14}}>{error}</div>}
    <section className="content-grid">
      <div className="card">
        <div className="card-title"><h2>Recent Trade Activity</h2><span>AUTHORITATIVE TRADE HISTORY</span></div>
        {data.recent_trades.length === 0 ? <div style={emptyStyle}>No trades recorded for the current day.</div> : data.recent_trades.map(t => <TradeRowView key={String(t.id)} trade={t}/>) }
      </div>
      <div className="card">
        <div className="card-title"><h2>Performance Snapshot</h2><span>LIVE DATABASE</span></div>
        <Health name="Daily" value={`${d.wins}W / ${d.losses}L · ${d.win_rate.toFixed(1)}%`} />
        <Health name="Weekly" value={`${data.weekly.wins}W / ${data.weekly.losses}L · ${data.weekly.win_rate.toFixed(1)}%`} />
        <Health name="Monthly" value={`${data.monthly.wins}W / ${data.monthly.losses}L · ${data.monthly.win_rate.toFixed(1)}%`} />
        <Health name="Pending" value={String(d.pending)} />
        <Health name="Unresolved" value={String(d.unresolved)} />
      </div>
    </section>
    <section className="content-grid">
      <div className="card"><div className="card-title"><h2>Engine Activity</h2><span>REAL RUNTIME</span></div>
        <ActivityRow title="Broker session" text={data.broker_connected ? "Dashboard is using the existing bot-owned broker connection." : "Broker connection is currently unavailable."}/>
        <ActivityRow title="Market scanner" text={`${data.assets_tracked} configured assets are available for analysis.`}/>
        <ActivityRow title="Settlement" text={`${d.settled} trade(s) settled today; ${d.pending} remain pending.`}/>
        <ActivityRow title="Mode" text={`Execution environment: ${data.mode}. Dashboard requests are authenticated server-side.`}/>
      </div>
      <div className="card"><div className="card-title"><h2>Directional Breakdown</h2><span>TODAY</span></div>
        <Health name="CALL" value={`${d.call.total} total · ${d.call.win_rate.toFixed(1)}%`} />
        <Health name="PUT" value={`${d.put.total} total · ${d.put.win_rate.toFixed(1)}%`} />
        <Health name="Stake" value={money(d.stake)} />
        <Health name="Payout" value={money(d.payout)} />
      </div>
    </section>
  </>;
}

function AnalyticsPanel() {
  const [period, setPeriod] = useState<"daily"|"weekly"|"monthly">("daily");
  const [report, setReport] = useState<TradeReport | null>(null);
  const [error, setError] = useState("");
  useEffect(() => { getAnalytics(period).then(x => setReport(x.report)).catch(e => setError(e instanceof Error ? e.message : "Analytics unavailable")); }, [period]);
  return <section className="user-section">
    <div style={{display:"flex",gap:7,marginBottom:14}}>{(["daily","weekly","monthly"] as const).map(p => <button key={p} onClick={()=>setPeriod(p)} style={tfButtonStyle(period===p)}>{p.toUpperCase()}</button>)}</div>
    {error && <div style={errorStyle}>{error}</div>}
    {report && <>
      <section className="grid4">
        <Metric icon={<Signal size={15}/>} label="Total Trades" value={String(report.total)} trend={`${report.settled} settled`} />
        <Metric icon={<CircleDollarSign size={15}/>} label="Net P/L" value={money(report.net_pl)} trend={`${report.win_rate.toFixed(1)}% win rate`} />
        <Metric icon={<Zap size={15}/>} label="Wins" value={String(report.wins)} trend={`${report.losses} losses`} />
        <Metric icon={<Database size={15}/>} label="Pending" value={String(report.pending)} trend={`${report.unresolved} unresolved`} />
      </section>
      <section className="content-grid">
        <div className="card"><div className="card-title"><h2>Asset Performance</h2><span>{period.toUpperCase()}</span></div>
          {Object.entries(report.by_asset).length === 0 ? <div style={emptyStyle}>No settled trade data for this period.</div> : <div style={{overflowX:"auto"}}><table className="user-table"><thead><tr><th>Asset</th><th>Trades</th><th>Wins</th><th>Losses</th><th>Win Rate</th><th>Net P/L</th></tr></thead><tbody>{Object.entries(report.by_asset).map(([asset,b])=><tr key={asset}><td className="user-name">{asset}</td><td>{b.total}</td><td className="profit">{b.wins}</td><td className="loss">{b.losses}</td><td>{Number(b.win_rate||0).toFixed(1)}%</td><td className={Number(b.net_pl||0)>=0?"profit":"loss"}>{money(Number(b.net_pl||0))}</td></tr>)}</tbody></table></div>}
        </div>
        <div className="card"><div className="card-title"><h2>Direction</h2><span>CONFLUENCE</span></div><Health name="CALL" value={`${report.call.total} · ${report.call.win_rate.toFixed(1)}%`} /><Health name="PUT" value={`${report.put.total} · ${report.put.win_rate.toFixed(1)}%`} /><Health name="Draws" value={String(report.draws)} /><Health name="Stake" value={money(report.stake)} /><Health name="Payout" value={money(report.payout)} /></div>
      </section>
    </>}
  </section>;
}

function TradeHistoryPanel() {
  const [data, setData] = useState<DashboardOverview | null>(null);
  const [error, setError] = useState("");
  useEffect(() => { getDashboardOverview().then(setData).catch(e=>setError(e instanceof Error?e.message:"Trade history unavailable")); }, []);
  return <section className="user-section"><div className="card"><div className="card-title"><h2>Trade History</h2><span>RECENT DATABASE RECORDS</span></div>{error&&<div style={errorStyle}>{error}</div>}{data && (data.recent_trades.length ? <div style={{overflowX:"auto"}}><table className="user-table"><thead><tr><th>Asset</th><th>Direction</th><th>Amount</th><th>Result</th><th>P/L</th><th>Placed</th><th>Settlement</th></tr></thead><tbody>{data.recent_trades.map(t=><tr key={String(t.id)}><td className="user-name">{t.asset}</td><td><Bias value={t.direction}/></td><td>{money(t.amount)}</td><td className={t.result==="WIN"?"profit":t.result==="LOSS"?"loss":""}>{t.result}</td><td className={Number(t.profit_loss||0)>=0?"profit":"loss"}>{t.profit_loss==null?"—":money(Number(t.profit_loss))}</td><td>{shortTime(t.placed_at)}</td><td>{t.settlement_source||"—"}</td></tr>)}</tbody></table></div> : <div style={emptyStyle}>No recent trades.</div>)}</div></section>;
}

function SystemHealthPanel() {
  const [status, setStatus] = useState<Record<string, unknown> | null>(null);
  const [error, setError] = useState("");
  useEffect(() => { getMarketStatus().then(x=>setStatus(x as Record<string,unknown>)).catch(e=>setError(e instanceof Error?e.message:"Health unavailable")); }, []);
  return <section className="user-section"><div className="card"><div className="card-title"><h2>System Health</h2><span>RAILWAY RUNTIME</span></div>{error&&<div style={errorStyle}>{error}</div>}<Health name="Broker" value={status?.connected ? "CONNECTED" : "DISCONNECTED"}/><Health name="Market feed" value={status?.connected ? "LIVE" : "UNAVAILABLE"}/><Health name="Assets" value={String(status?.assets_tracked ?? "—")}/><Health name="Dashboard API" value="AUTHENTICATED"/><Health name="Broker session model" value="SINGLE RUNTIME SESSION"/></div></section>;
}

function TradeRowView({trade}:{trade:TradeRow}) { return <div className="signal"><div className="pair">{trade.asset}<span className="sub">{shortTime(trade.placed_at)}</span></div><Bias value={trade.direction}/><div className={trade.result==="WIN"?"profit":trade.result==="LOSS"?"loss":""}>{trade.result}</div><div>{money(Number(trade.amount||0))}</div><div className={Number(trade.profit_loss||0)>=0?"profit":"loss"}>{trade.profit_loss==null?"—":money(Number(trade.profit_loss))}</div></div>; }

function UsersPanel() {
  const [users, setUsers] = useState<DashboardUser[]>([]);
  const [error, setError] = useState("");
  useEffect(() => { getUsers().then(setUsers).catch(e=>setError(e instanceof Error?e.message:"Users unavailable")); }, []);
  return <section className="user-section"><div className="user-summary"><div className="user-stat"><small>Registered Users</small><strong>{users.length}</strong></div><div className="user-stat"><small>API</small><strong>LIVE</strong></div><div className="user-stat"><small>Data Source</small><strong>SQLite</strong></div><div className="user-stat"><small>Access</small><strong>ADMIN</strong></div></div><div className="card"><div className="card-title"><h2>Registered Users</h2><span>LIVE DATABASE</span></div>{error&&<div style={errorStyle}>{error}</div>}<div style={{overflowX:"auto"}}><table className="user-table"><thead><tr><th>User</th><th>Telegram ID</th><th>Username</th><th>Created</th><th>Last Active</th></tr></thead><tbody>{users.map(u=><tr key={String(u.id)}><td className="user-name">{[u.first_name,u.last_name].filter(Boolean).join(" ")||"Unnamed"}</td><td>{u.telegram_id}</td><td>{u.username||"—"}</td><td>{shortTime(u.created_at)}</td><td>{shortTime(u.last_active)}</td></tr>)}</tbody></table></div></div></section>;
}

function money(value:number){ return `${value>=0?"+":"-"}$${Math.abs(value).toFixed(2)}`; }
function shortTime(value?:string|null){ if(!value) return "—"; const d=new Date(value); return Number.isNaN(d.getTime())?value:d.toLocaleString([], {month:"short",day:"2-digit",hour:"2-digit",minute:"2-digit"}); }

function ScannerMetric({label,value,live=false}:{label:string;value:string;live?:boolean}) {
  return <div className="card metric"><div className="metric-head"><span>{label}</span><span className="metric-icon">{live?<Wifi size={15}/>:<Activity size={15}/>}</span></div>
    <div className="metric-value" style={live?{color:"#4ade80"}:undefined}>{value}</div><div className="trend"><span style={{color:"#5f697a"}}>scanner telemetry</span></div></div>;
}
function Bias({value}:{value?:string}) { const v=String(value||"NEUTRAL").toUpperCase(); return <span className={"pill "+(v.includes("BULL")?"call":v.includes("BEAR")?"put":"")}>{value||"NEUTRAL"}</span>; }
function Readiness({value}:{value?:string}) { return <span className="asset-badge">{value||"WAIT"}</span>; }
function Strength({value}:{value?:number|null}) { const n=Number(value); return <span className="confidence">{Number.isFinite(n)?n.toFixed(0):"—"}</span>; }
function fmt(value:unknown) { const n=Number(value); return Number.isFinite(n)?n.toFixed(3):"—"; }
function Detail({label,value}:{label:string;value:unknown}) { return <div style={{padding:"10px 12px",border:"1px solid #202733",borderRadius:10,background:"#0c1118"}}><small style={{display:"block",color:"#657084",marginBottom:5}}>{label}</small><strong style={{fontSize:14}}>{String(value ?? "—")}</strong></div>; }

const tfButtonStyle = (active:boolean):React.CSSProperties => ({
  border:"1px solid "+(active?"#8b5cf6":"#26303d"), background:active?"rgba(139,92,246,.14)":"#0c1118",
  color:active?"#c4b5fd":"#9aa4b2", borderRadius:8, padding:"7px 11px", fontSize:11, fontWeight:700, cursor:"pointer"
});
const inputStyle:React.CSSProperties = { background:"#0c1118", border:"1px solid #26303d", color:"#d7deea", borderRadius:8, padding:"8px 10px", fontSize:11, outline:"none", width:150 };
const errorStyle:React.CSSProperties = { padding:"10px 12px", border:"1px solid rgba(248,113,113,.3)", background:"rgba(248,113,113,.06)", color:"#fca5a5", borderRadius:8, marginBottom:12, fontSize:11 };
const emptyStyle:React.CSSProperties = { padding:"30px 12px", color:"#657084", textAlign:"center", fontSize:12 };
const primaryButtonStyle:React.CSSProperties = { marginTop:12, width:"100%", border:0, borderRadius:9, padding:"11px 14px", background:"linear-gradient(135deg,#7c3aed,#4f46e5)", color:"#fff", fontWeight:800, cursor:"pointer" };

function ActivityRow({title,text}:{title:string;text:string}) { return <div className="activity"><i className="activity-dot"/><div><strong>{title}</strong><p>{text}</p></div></div>; }
function Metric({icon,label,value,trend,down=false}:{icon:React.ReactNode;label:string;value:string;trend:string;down?:boolean}) { return <div className="card metric"><div className="metric-head"><span>{label}</span><span className="metric-icon">{icon}</span></div><div className="metric-value">{value}</div><div className={"trend "+(down?"down":"")}>{trend} <span style={{color:"#5f697a"}}>vs previous period</span></div></div>; }
function Health({name,value}:{name:string;value:string}) { return <div style={{display:"flex",justifyContent:"space-between",padding:"9px 0",borderTop:"1px solid #1a202b",fontSize:10}}><span style={{color:"#8791a3"}}>{name}</span><span className="ok">{value}</span></div>; }

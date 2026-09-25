"use client";

import { useEffect, useMemo, useState } from "react";
import {
  Activity, Bell, Bot, BrainCircuit, CircleDollarSign, Database,
  Gauge, LayoutDashboard, LineChart, ListFilter, Menu, RefreshCw,
  Search, Settings2, ShieldCheck, Signal, Users, Wifi, Zap
} from "lucide-react";
import { AreaChart, Area, ResponsiveContainer, XAxis, YAxis, Tooltip } from "recharts";
import { getMarketScanner, getMarketStatus, ScannerRow } from "../frontend_api";

const data = [
  { t: "08:00", v: 62 }, { t: "10:00", v: 68 }, { t: "12:00", v: 64 },
  { t: "14:00", v: 75 }, { t: "16:00", v: 72 }, { t: "18:00", v: 81 },
  { t: "20:00", v: 78 }, { t: "22:00", v: 86 }
];

const signals = [
  { pair: "EUR/USD OTC", dir: "CALL", confidence: "94%", tf: "1m", time: "22:41:08" },
  { pair: "GBP/JPY OTC", dir: "PUT", confidence: "91%", tf: "1m", time: "22:39:42" },
  { pair: "AUD/CAD OTC", dir: "CALL", confidence: "88%", tf: "5m", time: "22:36:19" },
  { pair: "USD/BRL OTC", dir: "CALL", confidence: "86%", tf: "1m", time: "22:31:54" },
  { pair: "USD/INR OTC", dir: "PUT", confidence: "84%", tf: "5m", time: "22:28:07" }
];

const users = [
  { name: "User_1048", daily: "+$184.50", monthly: "+$3,842.20", high: "EUR/USDOTC", highP: "+$92.40", low: "USD/BRL OTC", lowP: "+$8.10" },
  { name: "User_2176", daily: "+$96.80", monthly: "+$2,164.70", high: "GBP/JPY OTC", highP: "+$61.20", low: "AUD/CAD OTC", lowP: "+$4.60" },
  { name: "User_3309", daily: "+$241.30", monthly: "+$5,091.40", high: "EUR/GBPOTC", highP: "+$118.70", low: "USD/INR OTC", lowP: "+$6.30" },
  { name: "User_4421", daily: "+$72.40", monthly: "+$1,487.90", high: "AUD/USD OTC", highP: "+$44.80", low: "USD/BRL OTC", lowP: "+$3.20" }
];

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
        ) : active === "Users" ? <UsersPanel /> : (
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

  useEffect(() => { load(); }, [timeframe]);

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
            <button style={primaryButtonStyle} disabled={!selected.asset}>
              Generate Signal · {selected.asset} · {timeframe}
            </button>
          </div>
        </section>
      )}
    </>
  );
}

function Overview() {
  return (
    <>
      <section className="grid4">
        <Metric icon={<Signal size={15} />} label="Signals Today" value="1,284" trend="+12.8%" />
        <Metric icon={<CircleDollarSign size={15} />} label="Accuracy" value="87.6%" trend="+3.4%" />
        <Metric icon={<Users size={15} />} label="Active Users" value="2,841" trend="+8.1%" />
        <Metric icon={<Wifi size={15} />} label="API Latency" value="142 ms" trend="−18 ms" down />
      </section>
      <section className="content-grid">
        <div className="card">
          <div className="card-title"><h2>Live Signal Engine</h2><span>STREAMING</span></div>
          {signals.map((s) => (
            <div className="signal" key={s.time}>
              <div className="pair">{s.pair}<span className="sub">Multi-indicator consensus</span></div>
              <span className={"pill " + (s.dir === "CALL" ? "call" : "put")}>{s.dir}</span>
              <div className="confidence">{s.confidence}</div><div>{s.tf}</div><div className="sub">{s.time}</div>
            </div>
          ))}
        </div>
        <div className="card">
          <div className="card-title"><h2>Confidence Performance</h2><span>LAST 24H</span></div>
          <div className="chart"><ResponsiveContainer width="100%" height="100%">
            <AreaChart data={data}><defs><linearGradient id="confidenceGradient" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#8b5cf6" stopOpacity={0.35}/><stop offset="100%" stopColor="#8b5cf6" stopOpacity={0}/>
            </linearGradient></defs>
            <XAxis dataKey="t" tick={{ fill:"#657084",fontSize:9 }} axisLine={false} tickLine={false}/>
            <YAxis domain={[50,100]} tick={{ fill:"#657084",fontSize:9 }} axisLine={false} tickLine={false}/>
            <Tooltip contentStyle={{ background:"#0b1017",border:"1px solid #202735",borderRadius:8,fontSize:10 }}/>
            <Area type="monotone" dataKey="v" stroke="#8b5cf6" fill="url(#confidenceGradient)" strokeWidth={2}/></AreaChart>
          </ResponsiveContainer></div>
        </div>
      </section>
      <section className="content-grid">
        <div className="card"><div className="card-title"><h2>Engine Activity</h2><span>REAL-TIME</span></div>
          <ActivityRow title="Market data feed synchronized" text="Scanner-ready market data layer is connected to the dashboard API."/>
          <ActivityRow title="Asset selection enabled" text="Operators can select the instrument before requesting analysis."/>
          <ActivityRow title="Timeframe coverage" text="1m · 2m · 5m · 15m · 30m · 1h"/>
          <ActivityRow title="Risk manager" text="Existing broker and signal controls remain outside the dashboard UI."/>
        </div>
        <div className="card"><div className="card-title"><h2>System Snapshot</h2><span>HEALTH</span></div>
          <Health name="Signal Engine" value="99.8%"/><Health name="Market Data" value="99.9%"/>
          <Health name="Telegram Bot" value="100%"/><Health name="Database" value="99.9%"/>
        </div>
      </section>
    </>
  );
}

function UsersPanel() {
  return <section className="user-section">
    <div className="user-summary">
      <div className="user-stat"><small>Total Users</small><strong>2,841</strong></div>
      <div className="user-stat"><small>Daily Profit</small><strong className="profit">+$18,426</strong></div>
      <div className="user-stat"><small>Monthly Profit</small><strong className="profit">+$428,915</strong></div>
      <div className="user-stat"><small>Profitable Users</small><strong>87.6%</strong></div>
    </div>
    <div className="card"><div className="card-title"><h2>User Profit Intelligence</h2><span>DAILY / MONTHLY</span></div>
      <div style={{ overflowX:"auto" }}><table className="user-table"><thead><tr><th>User</th><th>Profit Today</th><th>Profit This Month</th><th>Highest-Winning Asset</th><th>Lowest-Winning Asset</th></tr></thead>
      <tbody>{users.map((u)=><tr key={u.name}><td className="user-name">{u.name}</td><td className="profit">{u.daily}</td><td className="profit">{u.monthly}</td><td><span className="asset-badge">{u.high}</span> <span className="profit">{u.highP}</span></td><td><span className="asset-badge">{u.low}</span> <span className="profit">{u.lowP}</span></td></tr>)}</tbody></table></div>
    </div>
  </section>;
}

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

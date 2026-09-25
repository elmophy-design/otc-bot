from pathlib import Path

ROOT = Path(__file__).resolve().parent
TARGET = ROOT / 'frontend' / 'components' / 'dashboard.tsx'

if not TARGET.exists():
    raise SystemExit(f'Missing target: {TARGET}')

text = TARGET.read_text(encoding='utf-8')

# 1) Add review state beside existing signal state.
old = '''  const [signal, setSignal] = useState<MarketSignal | null>(null);\n  const [signalLoading, setSignalLoading] = useState(false);\n  const [signalError, setSignalError] = useState("");'''
new = '''  const [signal, setSignal] = useState<MarketSignal | null>(null);\n  const [signalLoading, setSignalLoading] = useState(false);\n  const [signalError, setSignalError] = useState("");\n  const [signalReviewed, setSignalReviewed] = useState(false);'''
if old in text and 'signalReviewed' not in text:
    text = text.replace(old, new, 1)

# 2) Reset review whenever a fresh signal is generated.
old = '''                  const result = await generateMarketSignal(selected.asset, timeframe);\n                  setSignal(result);'''
new = '''                  const result = await generateMarketSignal(selected.asset, timeframe);\n                  setSignal(result);\n                  setSignalReviewed(false);'''
if old in text:
    text = text.replace(old, new, 1)

# 3) Replace the existing compact result block with a controlled review panel.
start = text.find('            {signal && (')
if start == -1:
    raise SystemExit('Could not find existing Phase 3 signal result block')
end_marker = '''              </div>\n            )}'''
end = text.find(end_marker, start)
if end == -1:
    raise SystemExit('Could not find end of existing Phase 3 signal result block')
end += len(end_marker)

replacement = '''            {signal && (\n              <div style={{ marginTop: 14, padding: 14, border: "1px solid #202733", borderRadius: 12, background: "rgba(255,255,255,.02)" }}>\n                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 10, marginBottom: 12 }}>\n                  <div>\n                    <div style={{ fontSize: 11, color: "#687386", textTransform: "uppercase", letterSpacing: ".08em" }}>Production Signal Engine · Review</div>\n                    <div style={{ fontSize: 25, fontWeight: 800, marginTop: 3 }}>{signal.signal.action === "NO_SIGNAL" ? "WAIT" : signal.signal.action}</div>\n                  </div>\n                  <div style={{ textAlign: "right" }}>\n                    <div style={{ fontSize: 22, fontWeight: 800 }}>{signal.signal.confidence != null ? `${signal.signal.confidence.toFixed(0)}%` : "—"}</div>\n                    <div style={{ fontSize: 10, color: "#687386" }}>CONFIDENCE</div>\n                  </div>\n                </div>\n\n                <div style={{ display: "grid", gridTemplateColumns: "repeat(3,minmax(0,1fr))", gap: 8 }}>\n                  <Detail label="Asset" value={signal.asset} />\n                  <Detail label="Timeframe" value={signal.timeframe} />\n                  <Detail label="Entry Price" value={fmt(signal.signal.entry_price)} />\n                  <Detail label="Confluence" value={fmt(signal.signal.confluence_score)} />\n                  <Detail label="Generated" value={signal.generated_at ? new Date(signal.generated_at).toLocaleTimeString() : "—"} />\n                  <Detail label="Review State" value={signalReviewed ? "CONFIRMED" : "PENDING REVIEW"} />\n                </div>\n\n                <div style={{ marginTop: 12, padding: 11, borderRadius: 9, background: "rgba(255,255,255,.025)", color: "#aab3c2", fontSize: 12, lineHeight: 1.6 }}>\n                  {signal.signal.reason || "No qualifying setup."}\n                </div>\n\n                {signal.signal.votes && (\n                  <div style={{ marginTop: 12 }}>\n                    <div style={{ fontSize: 10, color: "#687386", textTransform: "uppercase", letterSpacing: ".08em", marginBottom: 7 }}>Indicator Votes</div>\n                    <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>\n                      {Object.entries(signal.signal.votes).map(([name, vote]) => (\n                        <span key={name} style={{ padding: "5px 8px", borderRadius: 7, border: "1px solid #202733", fontSize: 10, color: Number(vote) > 0 ? "#55d89a" : Number(vote) < 0 ? "#ff6b7a" : "#8b95a7" }}>\n                          {name.toUpperCase()} {Number(vote) > 0 ? "+1" : Number(vote) < 0 ? "−1" : "0"}\n                        </span>\n                      ))}\n                    </div>\n                  </div>\n                )}\n\n                {signal.signal.indicator_snapshot && (\n                  <div style={{ marginTop: 12 }}>\n                    <div style={{ fontSize: 10, color: "#687386", textTransform: "uppercase", letterSpacing: ".08em", marginBottom: 7 }}>Indicator Snapshot</div>\n                    <div style={{ display: "grid", gridTemplateColumns: "repeat(4,minmax(0,1fr))", gap: 7 }}>\n                      {Object.entries(signal.signal.indicator_snapshot).slice(0, 8).map(([name, value]) => (\n                        <Detail key={name} label={name.replaceAll("_", " ")} value={fmt(value as number | string | null | undefined)} />\n                      ))}\n                    </div>\n                  </div>\n                )}\n\n                <div style={{ marginTop: 14, paddingTop: 12, borderTop: "1px solid #202733", display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10 }}>\n                  <div style={{ fontSize: 11, color: "#788396" }}>\n                    {signalReviewed\n                      ? "Signal review confirmed. No order has been submitted."\n                      : signal.signal.action === "NO_SIGNAL"\n                        ? "No trade setup to confirm."\n                        : "Review the signal, timeframe, entry and confluence before confirmation."}\n                  </div>\n                  <button\n                    style={{ ...primaryButtonStyle, opacity: signalReviewed || signal.signal.action === "NO_SIGNAL" ? 0.55 : 1 }}\n                    disabled={signalReviewed || signal.signal.action === "NO_SIGNAL"}\n                    onClick={() => setSignalReviewed(true)}\n                  >\n                    {signalReviewed ? "Signal Confirmed" : "Confirm Signal Review"}\n                  </button>\n                </div>\n\n                <div style={{ marginTop: 9, fontSize: 10, color: "#596476" }}>\n                  EXECUTION LOCK · Phase 4 does not submit broker orders. Confirmation records operator intent only.\n                </div>\n              </div>\n            )}'''
text = text[:start] + replacement + text[end:]

TARGET.write_text(text, encoding='utf-8')
print('Applied Phase 4: signal review + explicit confirmation gate. Broker execution remains locked.')

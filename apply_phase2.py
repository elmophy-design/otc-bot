from pathlib import Path
import re

ROOT = Path(__file__).resolve().parent
frontend = ROOT / "frontend"
api_ts = frontend / "frontend_api.ts"
dashboard = frontend / "components" / "dashboard.tsx"
scanner = frontend / "src" / "web" / "market_scanner.py"

if not frontend.exists():
    raise SystemExit("Run this script from the repository root (the folder containing frontend/).")

api_ts.write_text(Path(ROOT / "frontend_api.phase2.ts").read_text(encoding="utf-8"), encoding="utf-8")
dashboard.write_text(Path(ROOT / "dashboard.phase2.tsx").read_text(encoding="utf-8"), encoding="utf-8")

s = scanner.read_text(encoding="utf-8")
original = s

# Add 2m wherever the scanner declares the supported timeframe collection.
patterns = [
    (r'("1m"\s*,\s*)"5m"', r'\1"2m", "5m"'),
    (r'(\{"1m"\s*,\s*)"5m"', r'\1"2m", "5m"'),
    (r'(\["1m"\s*,\s*)"5m"', r'\1"2m", "5m"'),
    (r'("1m"\s*,\s*"5m"\s*,)', r'\1'),
]
for p, repl in patterns:
    s = re.sub(p, repl, s, count=1)

# Common tuple/list/set formatting.
if s == original:
    for needle in ['"1m", "5m", "15m"', "'1m', '5m', '15m'"]:
        if needle in s:
            s = s.replace(needle, needle.replace("1m", "1m\", \"2m", 1), 1)
            break

if s == original:
    raise SystemExit(
        "Could not locate the scanner timeframe list automatically. "
        "Open frontend/src/web/market_scanner.py and add 2m to its supported timeframe collection."
    )

scanner.write_text(s, encoding="utf-8")
print("Phase 2 frontend installed.")
print("2m timeframe added to market_scanner.py.")
print("frontend_api.ts updated, including PATCH user update.")
print("dashboard.tsx replaced with live scanner UI.")

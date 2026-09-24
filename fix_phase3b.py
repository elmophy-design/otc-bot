from pathlib import Path

path = Path("src/data/storage.py")
text = path.read_text(encoding="utf-8")

start_marker = "    def _aggregate_by_asset("
end_marker = "    def "

start = text.find(start_marker)

if start == -1:
    raise SystemExit("ERROR: _aggregate_by_asset() was not found.")

next_method = text.find(end_marker, start + len(start_marker))

if next_method == -1:
    raise SystemExit("ERROR: Could not locate the next method after _aggregate_by_asset().")

new_method = '''    def _aggregate_by_asset(
        self,
        rows: List[TradeHistory],
    ) -> Dict[str, Dict[str, Any]]:
        """Aggregate authoritative trade outcomes by asset.

        Only WIN/LOSS/DRAW count as settled outcomes.
        PENDING/SETTLING remain open.
        UNKNOWN/REQUIRES_RECONCILIATION remain unresolved.

        Win rate excludes draws and unresolved trades.
        """

        assets: Dict[str, Dict[str, Any]] = {}

        for row in rows:
            asset = str(row.asset or "UNKNOWN").upper()

            if asset not in assets:
                assets[asset] = {
                    "total": 0,
                    "settled": 0,
                    "wins": 0,
                    "losses": 0,
                    "draws": 0,
                    "pending": 0,
                    "unresolved": 0,
                    "win_rate": 0.0,
                    "stake": 0.0,
                    "settled_stake": 0.0,
                    "payout": 0.0,
                    "net_pl": 0.0,
                }

            bucket = assets[asset]

            bucket["total"] += 1
            bucket["stake"] += float(row.amount or 0)

            result = str(row.result or "PENDING").upper()

            if result == "WIN":
                bucket["wins"] += 1
                bucket["settled"] += 1
                bucket["settled_stake"] += float(row.amount or 0)

            elif result == "LOSS":
                bucket["losses"] += 1
                bucket["settled"] += 1
                bucket["settled_stake"] += float(row.amount or 0)

            elif result == "DRAW":
                bucket["draws"] += 1
                bucket["settled"] += 1
                bucket["settled_stake"] += float(row.amount or 0)

            elif result in ("PENDING", "SETTLING"):
                bucket["pending"] += 1

            elif result in (
                "UNKNOWN",
                "REQUIRES_RECONCILIATION",
            ):
                bucket["unresolved"] += 1

            if row.payout is not None:
                bucket["payout"] += float(row.payout)

            if result in ("WIN", "LOSS", "DRAW"):
                if row.profit_loss is not None:
                    bucket["net_pl"] += float(row.profit_loss)

                elif row.payout is not None:
                    bucket["net_pl"] += (
                        float(row.payout)
                        - float(row.amount or 0)
                    )

        for bucket in assets.values():
            decisive = bucket["wins"] + bucket["losses"]

            bucket["win_rate"] = round(
                (
                    100.0 * bucket["wins"] / decisive
                )
                if decisive
                else 0.0,
                2,
            )

            bucket["stake"] = round(bucket["stake"], 2)
            bucket["settled_stake"] = round(
                bucket["settled_stake"],
                2,
            )
            bucket["payout"] = round(
                bucket["payout"],
                2,
            )
            bucket["net_pl"] = round(
                bucket["net_pl"],
                2,
            )

        return assets

'''

text = text[:start] + new_method + text[next_method:]

path.write_text(text, encoding="utf-8")

print("SUCCESS: _aggregate_by_asset() updated.")

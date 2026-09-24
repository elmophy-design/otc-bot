from pathlib import Path

path = Path("src/api/botv2_adapter.py")
text = path.read_text(encoding="utf-8")

start_marker = "    @staticmethod\n    def _normalize_settlement("
start = text.find(start_marker)

if start == -1:
    raise SystemExit("ERROR: _normalize_settlement() start not found.")

# Find the next method after _normalize_settlement().
next_method = text.find("\n    async def ", start + len(start_marker))
next_static = text.find("\n    @staticmethod", start + len(start_marker))
next_def = text.find("\n    def ", start + len(start_marker))

candidates = [
    pos for pos in (next_method, next_static, next_def)
    if pos != -1
]

if not candidates:
    raise SystemExit(
        "ERROR: Could not find the next method after "
        "_normalize_settlement()."
    )

end = min(candidates)

new_method = '''    @staticmethod
    def _normalize_settlement(res: Any) -> dict:
        """Normalize broker settlement data.

        BinaryOptionsToolsV2 v0.2.14 uses profit as the authoritative
        settlement signal:

        profit > 0  -> WIN
        profit == 0 -> DRAW
        profit < 0  -> LOSS

        If an explicit broker result is also supplied, both sources
        must agree. Contradictory evidence is preserved as
        REQUIRES_RECONCILIATION and is never silently converted into
        WIN or LOSS.
        """

        payload = (
            res
            if isinstance(res, dict)
            else {"result": res}
        )

        raw_result = (
            payload.get("result")
            or payload.get("outcome")
            or payload.get("status")
            or payload.get("trade_result")
            or payload.get("trade_outcome")
        )

        explicit_result = None

        if raw_result is not None:
            value = str(raw_result).strip().upper()

            if value in {
                "WIN",
                "WON",
                "PROFIT",
                "SUCCESS",
                "TRUE",
            }:
                explicit_result = "WIN"

            elif value in {
                "LOSS",
                "LOST",
                "LOSE",
                "FAILED",
                "FAIL",
                "FALSE",
            }:
                explicit_result = "LOSS"

            elif value in {
                "DRAW",
                "TIE",
                "REFUND",
                "REFUNDED",
                "BREAKEVEN",
                "BREAK_EVEN",
            }:
                explicit_result = "DRAW"

        if explicit_result is None:
            for key in ("win", "won", "is_win"):
                if key in payload and isinstance(
                    payload[key],
                    bool,
                ):
                    explicit_result = (
                        "WIN"
                        if payload[key]
                        else "LOSS"
                    )
                    break

        numeric_profit = None

        for key in (
            "profit",
            "profit_loss",
            "pnl",
            "net_profit",
        ):
            if payload.get(key) is not None:
                try:
                    numeric_profit = float(payload[key])
                    break
                except (TypeError, ValueError):
                    pass

        profit_result = None

        if numeric_profit is not None:
            if numeric_profit > 0:
                profit_result = "WIN"
            elif numeric_profit < 0:
                profit_result = "LOSS"
            else:
                profit_result = "DRAW"

        if (
            explicit_result is not None
            and profit_result is not None
            and explicit_result != profit_result
        ):
            return {
                "result": "REQUIRES_RECONCILIATION",
                "raw_result": raw_result,
                "profit": numeric_profit,
                "settlement_conflict": True,
                "expected_result": profit_result,
                "raw": payload,
            }

        if explicit_result is not None:
            return {
                "result": explicit_result,
                "raw_result": raw_result,
                "profit": numeric_profit,
                "settlement_conflict": False,
                "raw": payload,
            }

        if profit_result is not None:
            return {
                "result": profit_result,
                "raw_result": raw_result,
                "profit": numeric_profit,
                "settlement_conflict": False,
                "raw": payload,
            }

        return {
            "result": "UNKNOWN",
            "raw_result": raw_result,
            "profit": None,
            "settlement_conflict": False,
            "raw": payload,
        }
'''

text = text[:start] + new_method + text[end:]

path.write_text(text, encoding="utf-8")

print("OK: _normalize_settlement() replaced.")
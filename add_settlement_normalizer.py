from pathlib import Path
import subprocess
import sys

target = Path("src/api/botv2_adapter.py")

text = target.read_text(encoding="utf-8")

if "_normalize_settlement" in text:
    print("SKIPPED: _normalize_settlement already exists.")
    raise SystemExit(0)

marker = "    async def disconnect(self) -> None:"

position = text.find(marker)

if position == -1:
    raise SystemExit(
        "ERROR: Could not find disconnect() method. "
        "No changes made."
    )

method = '''    @staticmethod
    def _normalize_settlement(res: Any) -> dict:
        """Normalize broker settlement data.

        BinaryOptionsToolsV2 v0.2.14 uses profit as the settlement
        signal:

        profit > 0  -> WIN
        profit == 0 -> DRAW
        profit < 0  -> LOSS

        If an explicit result is also supplied, both sources must agree.
        Contradictory evidence is preserved as
        REQUIRES_RECONCILIATION.
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
            value = payload.get(key)

            if value is None:
                continue

            try:
                numeric_profit = float(value)
                break
            except (TypeError, ValueError):
                continue

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

patched = text[:position] + method + text[position:]

target.write_text(patched, encoding="utf-8")

result = subprocess.run(
    [
        sys.executable,
        "-m",
        "py_compile",
        str(target),
    ],
    capture_output=True,
    text=True,
)

if result.returncode != 0:
    print("COMPILATION FAILED")
    print(result.stderr)
    raise SystemExit(1)

print("SUCCESS: settlement normalizer added and adapter compiles.")
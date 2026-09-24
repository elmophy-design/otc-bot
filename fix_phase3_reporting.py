from pathlib import Path

path = Path("src/data/storage.py")
text = path.read_text(encoding="utf-8")

start_marker = "    def get_trade_report("
end_marker = "    def _aggregate_by_asset("

start = text.find(start_marker)
end = text.find(end_marker, start)

if start == -1:
    raise SystemExit(
        "ERROR: get_trade_report() was not found. No changes were made."
    )

if end == -1:
    raise SystemExit(
        "ERROR: _aggregate_by_asset() boundary was not found. "
        "No changes were made."
    )

new_function = '''    def get_trade_report(
        self,
        start_at: datetime,
        end_at: datetime,
        user_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Return one authoritative trade report for a half-open UTC period.

        Reporting rules:
        - WIN/LOSS/DRAW are settled outcomes.
        - PENDING/SETTLING are still open.
        - UNKNOWN/REQUIRES_RECONCILIATION are unresolved.
        - Win rate excludes draws and unresolved trades.
        - A real zero net P/L is different from missing P/L.
        - Broker supplied profit_loss is preferred.
        - Payout-minus-stake is used only when profit_loss is absent.
        """
        session = self.db.get_session()

        empty = {
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
            "call": {
                "total": 0,
                "wins": 0,
                "losses": 0,
                "draws": 0,
                "win_rate": 0.0,
            },
            "put": {
                "total": 0,
                "wins": 0,
                "losses": 0,
                "draws": 0,
                "win_rate": 0.0,
            },
            "by_asset": {},
            "trades": [],
        }

        try:
            query = (
                session.query(TradeHistory)
                .filter(TradeHistory.placed_at >= start_at)
                .filter(TradeHistory.placed_at < end_at)
            )

            if user_id is not None:
                user = (
                    session.query(User)
                    .filter_by(telegram_id=str(user_id))
                    .first()
                )

                if user is None:
                    return empty

                query = query.filter(TradeHistory.user_id == user.id)

            rows = query.order_by(TradeHistory.placed_at.asc()).all()

            if not rows:
                return empty

            wins = sum(r.result == "WIN" for r in rows)
            losses = sum(r.result == "LOSS" for r in rows)
            draws = sum(r.result == "DRAW" for r in rows)

            pending = sum(
                r.result in ("PENDING", "SETTLING")
                for r in rows
            )

            unresolved = sum(
                r.result in ("UNKNOWN", "REQUIRES_RECONCILIATION")
                for r in rows
            )

            settled = wins + losses + draws

            stake = sum(float(r.amount or 0) for r in rows)

            settled_stake = sum(
                float(r.amount or 0)
                for r in rows
                if r.result in ("WIN", "LOSS", "DRAW")
            )

            payout = sum(
                float(r.payout or 0)
                for r in rows
                if r.payout is not None
            )

            # IMPORTANT:
            # Do not use `if not net` here.
            # Zero can be a legitimate net P/L.
            net_pl = 0.0

            for row in rows:
                if row.result not in ("WIN", "LOSS", "DRAW"):
                    continue

                if row.profit_loss is not None:
                    net_pl += float(row.profit_loss)

                elif row.payout is not None:
                    net_pl += (
                        float(row.payout)
                        - float(row.amount or 0)
                    )

            decisive = wins + losses

            report = {
                "total": len(rows),
                "settled": settled,
                "wins": wins,
                "losses": losses,
                "draws": draws,
                "pending": pending,
                "unresolved": unresolved,
                "win_rate": round(
                    (100.0 * wins / decisive)
                    if decisive
                    else 0.0,
                    2,
                ),
                "stake": round(stake, 2),
                "settled_stake": round(settled_stake, 2),
                "payout": round(payout, 2),
                "net_pl": round(net_pl, 2),
                "call": {
                    "total": 0,
                    "wins": 0,
                    "losses": 0,
                    "draws": 0,
                    "win_rate": 0.0,
                },
                "put": {
                    "total": 0,
                    "wins": 0,
                    "losses": 0,
                    "draws": 0,
                    "win_rate": 0.0,
                },
                "by_asset": self._aggregate_by_asset(rows),
                "trades": [],
            }

            for row in rows:
                direction = str(row.direction or "").upper()

                if direction not in ("CALL", "PUT"):
                    continue

                bucket = report[direction.lower()]
                bucket["total"] += 1

                if row.result == "WIN":
                    bucket["wins"] += 1

                elif row.result == "LOSS":
                    bucket["losses"] += 1

                elif row.result == "DRAW":
                    bucket["draws"] += 1

            for direction in ("call", "put"):
                bucket = report[direction]
                decisive_direction = (
                    bucket["wins"] + bucket["losses"]
                )

                bucket["win_rate"] = round(
                    (
                        100.0
                        * bucket["wins"]
                        / decisive_direction
                    )
                    if decisive_direction
                    else 0.0,
                    2,
                )

            for row in rows:
                report["trades"].append(
                    {
                        "id": row.id,
                        "asset": row.asset,
                        "direction": row.direction,
                        "amount": float(row.amount or 0),
                        "result": row.result,
                        "profit_loss": (
                            float(row.profit_loss)
                            if row.profit_loss is not None
                            else None
                        ),
                        "payout": (
                            float(row.payout)
                            if row.payout is not None
                            else None
                        ),
                        "placed_at": (
                            row.placed_at.isoformat()
                            if row.placed_at
                            else None
                        ),
                        "expiry_at": (
                            row.expiry_at.isoformat()
                            if row.expiry_at
                            else None
                        ),
                        "closed_at": (
                            row.closed_at.isoformat()
                            if row.closed_at
                            else None
                        ),
                        "order_id": row.order_id,
                        "settlement_source": row.settlement_source,
                        "broker_result": row.broker_result,
                        "settlement_attempts": int(
                            row.settlement_attempts or 0
                        ),
                    }
                )

            return report

        finally:
            session.close()


'''

new_text = text[:start] + new_function + text[end:]

path.write_text(new_text, encoding="utf-8")

print("PHASE 3 REPORTING PATCH APPLIED")
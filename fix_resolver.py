from pathlib import Path

path = Path("src/data/storage.py")
text = path.read_text(encoding="utf-8")

start_marker = "    async def resolve_pending_trades("
end_marker = "    def get_trade_report("

start = text.index(start_marker)
end = text.index(end_marker, start)

new_method = '''    async def resolve_pending_trades(
        self,
        api_client: Any,
        data_fetcher: Any = None,
        grace_seconds: int = 5,
    ) -> List[Dict[str, Any]]:
        """Resolve due trades using broker settlement only.

        Broker settlement is authoritative.

        Local candle prices are never used to manufacture WIN/LOSS/DRAW.

        Settlement states:
            PENDING
            SETTLING
            WIN
            LOSS
            DRAW
            UNKNOWN
            REQUIRES_RECONCILIATION

        A broker contradiction is preserved as
        REQUIRES_RECONCILIATION and is never silently converted into
        WIN or LOSS.
        """
        now = datetime.utcnow()
        session = self.db.get_session()
        just_closed: List[Dict[str, Any]] = []

        terminal = {"WIN", "LOSS", "DRAW"}
        unresolved = {"UNKNOWN", "REQUIRES_RECONCILIATION"}

        try:
            due = (
                session.query(TradeHistory)
                .filter(
                    TradeHistory.result.in_(
                        (
                            "PENDING",
                            "SETTLING",
                            "UNKNOWN",
                            "REQUIRES_RECONCILIATION",
                        )
                    )
                )
                .filter(TradeHistory.expiry_at != None)
                .filter(TradeHistory.expiry_at <= now)
                .limit(200)
                .all()
            )

            for row in due:
                if row.expiry_at:
                    elapsed = (now - row.expiry_at).total_seconds()
                    if elapsed < grace_seconds:
                        continue

                # Preserve the state before entering SETTLING.
                previous_result = str(row.result or "PENDING").upper()

                # A previously reconciled trade must not be automatically
                # changed unless a fresh broker response provides evidence.
                if previous_result in terminal:
                    continue

                row.settlement_attempts = int(row.settlement_attempts or 0) + 1
                row.last_settlement_at = now
                row.result = "SETTLING"

                try:
                    if not row.order_id:
                        row.result = "REQUIRES_RECONCILIATION"
                        row.broker_result = "MISSING_ORDER_ID"
                        row.settlement_source = "missing_order_id"
                        continue

                    if not hasattr(api_client, "check_win"):
                        row.result = "REQUIRES_RECONCILIATION"
                        row.broker_result = "CHECK_WIN_UNAVAILABLE"
                        row.settlement_source = "missing_check_win"
                        continue

                    res = await api_client.check_win(
                        row.order_id,
                        timeout=20,
                    )

                    if not isinstance(res, dict):
                        res = {"result": "UNKNOWN", "raw": res}

                    broker_result = str(
                        res.get("result") or "UNKNOWN"
                    ).upper()

                    raw_result = res.get("raw_result")
                    row.broker_result = str(
                        raw_result if raw_result is not None
                        else broker_result
                    )[:100]

                    # Store broker profit whenever supplied.
                    if res.get("profit") is not None:
                        try:
                            row.profit_loss = float(res["profit"])
                        except (TypeError, ValueError):
                            logger.warning(
                                "Invalid broker profit for trade %s: %r",
                                row.id,
                                res.get("profit"),
                            )

                    # --------------------------------------------------
                    # CONTRADICTION
                    # --------------------------------------------------
                    if broker_result == "REQUIRES_RECONCILIATION":
                        row.result = "REQUIRES_RECONCILIATION"
                        row.settlement_source = "broker_check_win_conflict"
                        logger.error(
                            "Broker settlement contradiction for trade "
                            "%s order=%s raw_result=%s profit=%s",
                            row.id,
                            row.order_id,
                            raw_result,
                            res.get("profit"),
                        )
                        continue

                    # --------------------------------------------------
                    # DEFINITIVE BROKER RESULT
                    # --------------------------------------------------
                    if broker_result in terminal:
                        # If a previous terminal result somehow exists,
                        # never silently overwrite it.
                        if previous_result in terminal:
                            if previous_result != broker_result:
                                logger.error(
                                    "Settlement conflict for trade %s: "
                                    "existing=%s broker=%s",
                                    row.id,
                                    previous_result,
                                    broker_result,
                                )
                                row.result = "REQUIRES_RECONCILIATION"
                                row.settlement_source = (
                                    "terminal_result_conflict"
                                )
                                continue

                            # Same terminal result: idempotent.
                            row.result = previous_result
                        else:
                            row.result = broker_result

                        row.settlement_source = "broker_check_win"

                        if res.get("payout") is not None:
                            try:
                                row.payout = float(res["payout"])
                            except (TypeError, ValueError):
                                logger.warning(
                                    "Invalid broker payout for trade %s: %r",
                                    row.id,
                                    res.get("payout"),
                                )

                        # If broker supplied profit, it is authoritative.
                        # Otherwise calculate from payout only when available.
                        if (
                            row.profit_loss is None
                            and row.payout is not None
                        ):
                            row.profit_loss = (
                                float(row.payout)
                                - float(row.amount or 0)
                            )

                        row.closed_at = now

                        just_closed.append(
                            {
                                "id": row.id,
                                "telegram_id": row.telegram_id,
                                "chat_id": row.chat_id,
                                "asset": row.asset,
                                "direction": row.direction,
                                "amount": row.amount,
                                "result": row.result,
                                "order_id": row.order_id,
                                "profit_loss": row.profit_loss,
                            }
                        )
                        continue

                    # --------------------------------------------------
                    # UNKNOWN / TEMPORARY BROKER RESPONSE
                    # --------------------------------------------------
                    if broker_result in unresolved or not broker_result:
                        row.result = "PENDING"
                        row.settlement_source = "broker_pending"
                        continue

                    # Any unrecognized broker response must remain
                    # unresolved rather than being guessed.
                    row.result = "PENDING"
                    row.settlement_source = "broker_unrecognized"

                except Exception:
                    logger.exception(
                        "Failed to resolve trade id=%s order=%s",
                        row.id,
                        row.order_id,
                    )

                    # Temporary API/client failure:
                    # retry later. Do not manufacture a result.
                    row.result = "PENDING"
                    row.settlement_source = "broker_retry"

            session.commit()

        finally:
            session.close()

        return just_closed

'''

path.write_text(text[:start] + new_method + text[end:], encoding="utf-8")

print("RESOLVER PATCH APPLIED")
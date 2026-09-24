"""Data Persistence with SQLAlchemy"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy import func

from ..models.database import DatabaseManager
from ..models.schemas import Base, SignalHistory, TradeHistory, User
from ..utils.logger import get_logger

logger = get_logger(__name__)


class DataStorage:
    """Professional Data Storage with minimal analytics support."""

    def __init__(self):
        self.db = DatabaseManager()
        Base.metadata.create_all(self.db.engine)

    def _ensure_user(self, user_id: int, username: Optional[str] = None) -> Optional[int]:
        session = self.db.get_session()
        try:
            user = session.query(User).filter_by(telegram_id=str(user_id)).first()
            if user is None:
                user = User(telegram_id=str(user_id), username=username or "")
                session.add(user)
                session.commit()
                session.refresh(user)
            return user.id
        except Exception as exc:
            logger.exception("Failed to ensure user %s: %s", user_id, exc)
            session.rollback()
            return None
        finally:
            session.close()

    def save_signal(self, user_id: int, asset: str, signal: Dict[str, Any]) -> bool:
        """Save signal to database and keep an auditable signal history."""
        try:
            user_db_id = self._ensure_user(user_id)
            if user_db_id is None:
                return False

            session = self.db.get_session()
            action = str(signal.get("action") or "NO_SIGNAL")
            confidence = float(signal.get("confidence") or 0.0)
            entry_price = signal.get("entry_price")
            signal_record = SignalHistory(
                user_id=user_db_id,
                asset=asset or signal.get("asset", "unknown"),
                action=action,
                confidence=confidence,
                entry_price=float(entry_price) if entry_price is not None else None,
                signal_data={
                    "reason": signal.get("reason"),
                    "indicator_snapshot": signal.get("indicator_snapshot"),
                    "votes": signal.get("votes"),
                    "htf": signal.get("htf"),
                    "timestamp": signal.get("timestamp"),
                },
            )
            session.add(signal_record)
            session.commit()
            session.close()
            logger.info("Saved signal for user %s asset %s action=%s", user_id, asset, action)
            return True
        except Exception as exc:
            logger.exception("Failed to save signal for user %s: %s", user_id, exc)
            return False

    def get_recent_signals(self, user_id: int, limit: int = 10) -> List[Dict[str, Any]]:
        """Return recent signals for a user."""
        session = self.db.get_session()
        try:
            user = session.query(User).filter_by(telegram_id=str(user_id)).first()
            if user is None:
                return []
            rows = (
                session.query(SignalHistory)
                .filter_by(user_id=user.id)
                .order_by(SignalHistory.created_at.desc())
                .limit(limit)
                .all()
            )
            return [
                {
                    "id": row.id,
                    "asset": row.asset,
                    "action": row.action,
                    "confidence": row.confidence,
                    "entry_price": row.entry_price,
                    "created_at": row.created_at.isoformat() if row.created_at else None,
                    "reason": (row.signal_data or {}).get("reason"),
                }
                for row in rows
            ]
        finally:
            session.close()

    def get_performance_summary(self, user_id: int, limit: int = 10) -> Dict[str, Any]:
        """Return a performance snapshot for recent user signals."""
        recent = self.get_recent_signals(user_id, limit=limit)
        total_signals = len(recent)
        call_count = sum(1 for item in recent if str(item.get("action") or "").upper() == "CALL")
        put_count = sum(1 for item in recent if str(item.get("action") or "").upper() == "PUT")
        no_signal_count = total_signals - call_count - put_count
        avg_confidence = (
            sum(float(item.get("confidence") or 0.0) for item in recent) / total_signals
            if total_signals
            else 0.0
        )

        return {
            "total_signals": total_signals,
            "call_count": call_count,
            "put_count": put_count,
            "no_signal_count": no_signal_count,
            "avg_confidence": round(avg_confidence, 2),
            "recent_signals": recent,
        }

    def get_daily_summary(self, user_id: int, limit: int = 10) -> Dict[str, Any]:
        """Return a concise daily summary of the user's recent signal activity."""
        summary = self.get_performance_summary(user_id, limit=limit)
        recent = summary.get("recent_signals") or []
        best_asset = None
        best_confidence = -1.0
        for item in recent:
            asset = item.get("asset")
            confidence = float(item.get("confidence") or 0.0)
            if confidence > best_confidence:
                best_confidence = confidence
                best_asset = asset

        return {
            "signal_count": summary.get("total_signals", 0),
            "call_count": summary.get("call_count", 0),
            "put_count": summary.get("put_count", 0),
            "avg_confidence": summary.get("avg_confidence", 0.0),
            "best_asset": best_asset,
            "best_confidence": round(best_confidence, 2),
        }

    def get_user_stats(self) -> Dict[str, Any]:
        """Return a small operational snapshot for admin dashboards."""
        users = self.list_all_users(limit=5)
        return {
            "total_users": len(users),
            "recent_users": users,
        }

    def list_all_users(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """Return registered users for admin operations and dashboard views."""
        session = self.db.get_session()
        try:
            query = session.query(User).order_by(User.created_at.desc())
            if limit is not None:
                query = query.limit(limit)
            rows = query.all()
            return [
                {
                    "telegram_id": row.telegram_id,
                    "username": row.username,
                    "first_name": row.first_name,
                    "last_active": row.last_active.isoformat() if row.last_active else None,
                }
                for row in rows
            ]
        finally:
            session.close()

    # ------------------------------------------------------------------
    # Executed trade tracking (separate from generated-signal history)
    # ------------------------------------------------------------------

    def save_trade(
        self,
        user_id: int,
        chat_id: int,
        asset: str,
        direction: str,
        amount: float,
        duration_secs: int,
        order_id: str,
        entry_price: Optional[float],
    ) -> Optional[int]:
        """Record a just-placed trade as PENDING. Returns the row id."""
        try:
            user_db_id = self._ensure_user(user_id)
            if user_db_id is None:
                return None

            session = self.db.get_session()
            now = datetime.utcnow()
            trade = TradeHistory(
                user_id=user_db_id,
                telegram_id=str(user_id),
                chat_id=str(chat_id),
                asset=asset,
                direction=direction,
                amount=amount,
                duration_secs=duration_secs,
                order_id=str(order_id) if order_id is not None else None,
                entry_price=entry_price,
                placed_at=now,
                expiry_at=now + timedelta(seconds=duration_secs),
                result="PENDING",
            )
            session.add(trade)
            session.commit()
            session.refresh(trade)
            trade_id = trade.id
            session.close()
            return trade_id
        except Exception:
            logger.exception("Failed to save trade for user %s asset %s", user_id, asset)
            return None

    async def resolve_pending_trades(
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

    def get_trade_report(
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


    def _aggregate_by_asset(
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

    def get_trade_stats(self, user_id: Optional[int] = None, limit: int = 10) -> Dict[str, Any]:
        """Win/loss stats for executed trades (optionally scoped to one user)."""
        session = self.db.get_session()
        try:
            query = session.query(TradeHistory)
            if user_id is not None:
                user = session.query(User).filter_by(telegram_id=str(user_id)).first()
                if user is None:
                    return {"total_closed": 0, "wins": 0, "losses": 0, "win_rate": 0.0, "recent": []}
                query = query.filter(TradeHistory.user_id == user.id)

            recent_rows = query.order_by(TradeHistory.placed_at.desc()).limit(limit).all()
            closed = [r for r in recent_rows if r.result in ("WIN", "LOSS")]
            wins = sum(1 for r in closed if r.result == "WIN")
            losses = sum(1 for r in closed if r.result == "LOSS")
            total = wins + losses
            return {
                "total_closed": total,
                "wins": wins,
                "losses": losses,
                "win_rate": round(100.0 * wins / total, 2) if total else 0.0,
                "recent": [
                    {
                        "asset": r.asset,
                        "direction": r.direction,
                        "amount": r.amount,
                        "result": r.result,
                        "placed_at": r.placed_at.isoformat() if r.placed_at else None,
                    }
                    for r in recent_rows
                ],
            }
        finally:
            session.close()

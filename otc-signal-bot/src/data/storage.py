"""Data Persistence with SQLAlchemy"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from sqlalchemy import func

from ..models.database import DatabaseManager
from ..models.schemas import Base, SignalHistory, User
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

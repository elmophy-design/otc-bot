from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from src.api.botv2_adapter import BotV2Client
from src.data.storage import DataStorage
from src.models.database import DatabaseManager
from src.models.schemas import TradeHistory


def test_settlement_normalization_preserves_win_loss():
    assert BotV2Client._normalize_settlement(
        {"result": "WIN"}
    )["result"] == "WIN"

    assert BotV2Client._normalize_settlement(
        {"result": "LOSS"}
    )["result"] == "LOSS"

    assert BotV2Client._normalize_settlement(
        {"result": "WON"}
    )["result"] == "WIN"

    assert BotV2Client._normalize_settlement(
        {"result": "LOST"}
    )["result"] == "LOSS"


async def _create_due_trade(storage, user_id: int, order_id: str):
    trade_id = storage.save_trade(
        user_id=user_id,
        chat_id=user_id,
        asset="EURUSD_otc",
        direction="CALL",
        amount=10.0,
        duration_secs=60,
        order_id=order_id,
        entry_price=1.1000,
    )

    assert trade_id is not None

    session = storage.db.get_session()
    try:
        trade = session.query(TradeHistory).filter(
            TradeHistory.id == trade_id
        ).one()

        # Make the synthetic trade expired so the resolver will process it.
        trade.expiry_at = datetime.utcnow() - timedelta(seconds=60)
        trade.result = "PENDING"

        session.commit()
    finally:
        session.close()

    return trade_id


@pytest.mark.asyncio
async def test_broker_loss_is_recorded_as_loss(tmp_path, monkeypatch):
    db_path = tmp_path / "settlement_loss.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")

    DatabaseManager._instance = None
    storage = DataStorage()

    trade_id = await _create_due_trade(
        storage,
        user_id=999001,
        order_id="TEST-LOSS-001",
    )

    class FakeBroker:
        async def check_win(self, order_id, timeout=20):
            assert order_id == "TEST-LOSS-001"
            return {
                "result": "LOSS",
                "raw_result": "LOSS",
                "profit": -10.0,
            }

    closed = await storage.resolve_pending_trades(
        FakeBroker(),
        None,
        grace_seconds=0,
    )

    assert len(closed) == 1
    assert closed[0]["result"] == "LOSS"
    assert closed[0]["profit_loss"] == -10.0

    session = storage.db.get_session()
    try:
        trade = session.query(TradeHistory).filter(
            TradeHistory.id == trade_id
        ).one()

        assert trade.result == "LOSS"
        assert trade.broker_result == "LOSS"
        assert trade.settlement_source == "broker_check_win"
        assert trade.profit_loss == -10.0
        assert trade.closed_at is not None
    finally:
        session.close()


@pytest.mark.asyncio
async def test_broker_win_is_recorded_as_win(tmp_path, monkeypatch):
    db_path = tmp_path / "settlement_win.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")

    DatabaseManager._instance = None
    storage = DataStorage()

    trade_id = await _create_due_trade(
        storage,
        user_id=999002,
        order_id="TEST-WIN-001",
    )

    class FakeBroker:
        async def check_win(self, order_id, timeout=20):
            assert order_id == "TEST-WIN-001"
            return {
                "result": "WIN",
                "raw_result": "WIN",
                "profit": 8.5,
            }

    closed = await storage.resolve_pending_trades(
        FakeBroker(),
        None,
        grace_seconds=0,
    )

    assert len(closed) == 1
    assert closed[0]["result"] == "WIN"
    assert closed[0]["profit_loss"] == 8.5

    session = storage.db.get_session()
    try:
        trade = session.query(TradeHistory).filter(
            TradeHistory.id == trade_id
        ).one()

        assert trade.result == "WIN"
        assert trade.broker_result == "WIN"
        assert trade.settlement_source == "broker_check_win"
        assert trade.profit_loss == 8.5
        assert trade.closed_at is not None
    finally:
        session.close()


@pytest.mark.asyncio
async def test_unresolved_broker_result_does_not_become_win_or_loss(
    tmp_path,
    monkeypatch,
):
    db_path = tmp_path / "settlement_pending.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")

    DatabaseManager._instance = None
    storage = DataStorage()

    trade_id = await _create_due_trade(
        storage,
        user_id=999003,
        order_id="TEST-PENDING-001",
    )

    class FakeBroker:
        async def check_win(self, order_id, timeout=20):
            assert order_id == "TEST-PENDING-001"
            return {
                "result": "UNKNOWN",
                "raw_result": "UNKNOWN",
            }

    closed = await storage.resolve_pending_trades(
        FakeBroker(),
        None,
        grace_seconds=0,
    )

    assert closed == []

    session = storage.db.get_session()
    try:
        trade = session.query(TradeHistory).filter(
            TradeHistory.id == trade_id
        ).one()

        assert trade.result == "PENDING"
        assert trade.broker_result == "UNKNOWN"
        assert trade.closed_at is None
        assert trade.settlement_source == "broker_pending"
        assert trade.settlement_attempts == 1
    finally:
        session.close()

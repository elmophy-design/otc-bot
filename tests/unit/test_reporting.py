from datetime import datetime, timedelta

from src.models.database import DatabaseManager
from src.data.storage import DataStorage
from src.models.schemas import TradeHistory


def make_storage(monkeypatch, tmp_path):
    db_path = tmp_path / "reporting.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    DatabaseManager._instance = None
    return DataStorage()


def add_trade(
    storage,
    *,
    user_id,
    result,
    amount,
    profit_loss=None,
    payout=None,
    direction="CALL",
    asset="EURUSD_otc",
    placed_at=None,
):
    trade = storage.save_trade(
        user_id=user_id,
        chat_id=user_id,
        asset=asset,
        direction=direction,
        amount=amount,
        duration_secs=60,
        order_id=f"ORDER-{user_id}-{amount}-{result}",
        entry_price=1.1000,
    )

    session = storage.db.get_session()

    try:
        row = (
    	 session.query(TradeHistory)
   	.filter(TradeHistory.id == trade)
        .one()
)
        row.placed_at = placed_at or datetime.utcnow()
        row.result = result
        row.profit_loss = profit_loss
        row.payout = payout

        if result in ("WIN", "LOSS", "DRAW"):
            row.closed_at = row.placed_at + timedelta(seconds=60)

        session.commit()

        return row.id

    finally:
        session.close()


def test_report_counts_and_win_rate(monkeypatch, tmp_path):
    storage = make_storage(monkeypatch, tmp_path)

    user_id = 100001

    add_trade(
        storage,
        user_id=user_id,
        result="WIN",
        amount=10,
        profit_loss=8,
        payout=18,
        direction="CALL",
        placed_at=datetime(2026, 9, 5, 10, 0),
    )

    add_trade(
        storage,
        user_id=user_id,
        result="LOSS",
        amount=10,
        profit_loss=-10,
        payout=0,
        direction="CALL",
        placed_at=datetime(2026, 9, 5, 11, 0),
    )

    add_trade(
        storage,
        user_id=user_id,
        result="DRAW",
        amount=10,
        profit_loss=0,
        payout=10,
        direction="PUT",
        placed_at=datetime(2026, 9, 5, 12, 0),
    )

    add_trade(
        storage,
        user_id=user_id,
        result="PENDING",
        amount=10,
        direction="PUT",
        placed_at=datetime(2026, 9, 5, 13, 0),
    )

    report = storage.get_trade_report(
        datetime(2026, 9, 1),
        datetime(2026, 10, 1),
        user_id=user_id,
    )

    assert report["total"] == 4
    assert report["settled"] == 3
    assert report["wins"] == 1
    assert report["losses"] == 1
    assert report["draws"] == 1
    assert report["pending"] == 1

    # Draw is excluded from decisive win rate.
    assert report["win_rate"] == 50.0

    assert report["stake"] == 40.0
    assert report["settled_stake"] == 30.0

    # +8 -10 +0 = -2
    assert report["net_pl"] == -2.0

    assert report["call"]["total"] == 2
    assert report["call"]["wins"] == 1
    assert report["call"]["losses"] == 1
    assert report["call"]["win_rate"] == 50.0

    assert report["put"]["total"] == 2
    assert report["put"]["wins"] == 0
    assert report["put"]["losses"] == 0
    assert report["put"]["draws"] == 1


def test_zero_profit_is_not_treated_as_missing(
    monkeypatch,
    tmp_path,
):
    storage = make_storage(monkeypatch, tmp_path)

    user_id = 100002

    add_trade(
        storage,
        user_id=user_id,
        result="DRAW",
        amount=20,
        profit_loss=0.0,
        payout=None,
        direction="CALL",
        placed_at=datetime(2026, 9, 10, 10, 0),
    )

    report = storage.get_trade_report(
        datetime(2026, 9, 1),
        datetime(2026, 10, 1),
        user_id=user_id,
    )

    assert report["settled"] == 1
    assert report["draws"] == 1
    assert report["net_pl"] == 0.0


def test_unresolved_is_not_loss(
    monkeypatch,
    tmp_path,
):
    storage = make_storage(monkeypatch, tmp_path)

    user_id = 100003

    add_trade(
        storage,
        user_id=user_id,
        result="REQUIRES_RECONCILIATION",
        amount=50,
        direction="PUT",
        placed_at=datetime(2026, 9, 15, 10, 0),
    )

    report = storage.get_trade_report(
        datetime(2026, 9, 1),
        datetime(2026, 10, 1),
        user_id=user_id,
    )

    assert report["total"] == 1
    assert report["settled"] == 0
    assert report["wins"] == 0
    assert report["losses"] == 0
    assert report["unresolved"] == 1
    assert report["win_rate"] == 0.0
    assert report["net_pl"] == 0.0
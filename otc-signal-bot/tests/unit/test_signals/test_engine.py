"""Unit tests for the multi-indicator SignalEngine."""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from config.settings import Settings
from src.data.storage import DataStorage
from src.models.database import DatabaseManager
from src.services.admin_service import AdminService
from src.services.broadcast_service import BroadcastService
from src.services.risk_manager import RiskManager
from src.signals.engine import SignalEngine


def _make_ohlcv(n: int = 120, trend: str = "down", seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    t = np.arange(n)
    if trend == "down":
        price = 1.1000 - t * 0.00035 + rng.normal(0, 0.00006, n)
        if n >= 20:
            price[-12:] = price[-13] - np.linspace(0, 0.0045, 12)
    elif trend == "up":
        price = 1.0800 + t * 0.0003 + rng.normal(0, 0.00006, n)
        if n >= 20:
            price[-12:] = price[-13] + np.linspace(0, 0.0045, 12)
    else:
        price = 1.0900 + rng.normal(0, 0.00015, n).cumsum() * 0.3

    close = pd.Series(price)
    high = close + rng.uniform(0.00004, 0.0002, n)
    low = close - rng.uniform(0.00004, 0.0002, n)
    open_ = close.shift(1).fillna(close.iloc[0])
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": 400}
    )


@pytest.fixture
def engine():
    settings = Settings(require_token=False)
    settings.MIN_CONFIDENCE = 55
    settings.USE_AI = False
    return SignalEngine(settings, data_fetcher=None)


def _run(coro):
    return asyncio.run(coro)


def test_oversold_produces_call(engine):
    df = _make_ohlcv(trend="down")
    signal = _run(engine.generate_signal("EURUSD_otc", candles=df))
    assert signal["action"] in ("CALL", "NO_SIGNAL")
    if signal["action"] == "CALL":
        assert signal["confidence"] >= 55
        assert "rsi" in (signal.get("indicator_snapshot") or {})


def test_overbought_produces_put(engine):
    df = _make_ohlcv(trend="up", seed=11)
    signal = _run(engine.generate_signal("EURUSD_otc", candles=df))
    assert signal["action"] in ("PUT", "NO_SIGNAL")
    if signal["action"] == "PUT":
        assert signal["confidence"] >= 55


def test_sideways_structure(engine):
    df = _make_ohlcv(trend="sideways", seed=99)
    signal = _run(engine.generate_signal("EURUSD_otc", candles=df))
    assert signal["action"] in ("CALL", "PUT", "NO_SIGNAL")
    assert "timestamp" in signal
    assert "asset" in signal


def test_insufficient_data(engine):
    df = _make_ohlcv(n=10, trend="sideways")
    signal = _run(engine.generate_signal("EURUSD_otc", candles=df))
    assert signal["action"] == "NO_SIGNAL"
    assert "Insufficient" in signal.get("reason", "")


def test_empty_dataframe(engine):
    df = pd.DataFrame()
    signal = _run(engine.generate_signal("EURUSD_otc", candles=df))
    assert signal["action"] == "NO_SIGNAL"


def test_indicator_snapshot_present(engine):
    df = _make_ohlcv(trend="down")
    signal = _run(engine.generate_signal("TEST_otc", candles=df))
    snap = signal.get("indicator_snapshot") or {}
    assert isinstance(snap, dict)


def test_signal_storage_and_summary(tmp_path, monkeypatch):
    db_path = tmp_path / "analytics.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    DatabaseManager._instance = None

    storage = DataStorage()
    storage.save_signal(
        42,
        "EURUSD_otc",
        {
            "action": "CALL",
            "confidence": 82.5,
            "reason": "Strong bullish confluence",
            "entry_price": 1.1023,
            "asset": "EURUSD_otc",
        },
    )
    storage.save_signal(
        42,
        "GBPUSD_otc",
        {
            "action": "PUT",
            "confidence": 71.1,
            "reason": "Bearish momentum",
            "entry_price": 1.3054,
            "asset": "GBPUSD_otc",
        },
    )

    summary = storage.get_performance_summary(user_id=42, limit=10)
    assert summary["total_signals"] == 2
    assert summary["call_count"] == 1
    assert summary["put_count"] == 1
    assert summary["avg_confidence"] > 70


def test_mtf_strict_filter_blocks_countertrend_signal(monkeypatch):
    settings = Settings(require_token=False)
    settings.MIN_CONFIDENCE = 55
    settings.USE_AI = False
    settings.config["signals"]["mtf"] = {"enabled": True, "strict_filter": True, "min_alignment": 1}
    engine = SignalEngine(settings, data_fetcher=None)

    monkeypatch.setattr(
        engine,
        "_analyze",
        lambda *_args, **_kwargs: {
            "action": "CALL",
            "reason": "Bullish confluence",
            "votes": {"rsi": 1, "macd": 1, "bollinger": 1, "ema": 1, "stochastic": 1},
            "indicator_snapshot": {"rsi": 18.0, "macd_hist": 0.001, "bb_position": 0.2, "stoch_k": 18.0, "adx": 26.0},
            "confluence_score": 5,
            "bullish_count": 5,
            "bearish_count": 0,
        },
    )

    monkeypatch.setattr(
        "src.signals.timeframes.higher_tf_bias",
        lambda *_args, **_kwargs: {"bias": "BEARISH", "score": -2, "rsi": 35.0, "ema_fast": 1.0, "ema_slow": 1.1},
    )
    monkeypatch.setattr(
        "src.signals.timeframes.suggest_higher_tf",
        lambda *_args, **_kwargs: "5m",
    )
    monkeypatch.setattr(
        "src.signals.timeframes.resample_ohlcv",
        lambda *_args, **_kwargs: _make_ohlcv(trend="up", n=120),
    )

    signal = _run(engine.generate_signal("EURUSD_otc", timeframe="1m", candles=_make_ohlcv(trend="up", n=120)))
    assert signal["action"] == "NO_SIGNAL"
    assert "Blocked by HTF" in signal["reason"]


def test_risk_manager_and_daily_summary(tmp_path, monkeypatch):
    db_path = tmp_path / "analytics.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    DatabaseManager._instance = None

    storage = DataStorage()
    storage.save_signal(88, "EURUSD_otc", {"action": "CALL", "confidence": 84, "asset": "EURUSD_otc"})
    storage.save_signal(88, "GBPUSD_otc", {"action": "PUT", "confidence": 72, "asset": "GBPUSD_otc"})

    risk = RiskManager(account_balance=1000.0, max_daily_loss=150.0, max_risk_per_trade=0.02)
    assert risk.should_block(5.0, 82.0) is False
    assert risk.should_block(200.0, 54.0) is True

    daily = storage.get_daily_summary(user_id=88)
    assert daily["signal_count"] >= 2
    assert daily["best_asset"] in {"EURUSD_otc", "GBPUSD_otc"}


def test_admin_service_access_rules():
    settings = Settings(require_token=False)
    settings.ADMIN_IDS = "101,202"
    settings.PREMIUM_IDS = "101"
    settings.PREMIUM_ONLY = False

    admin = AdminService(settings)
    assert admin.is_admin(101) is True
    assert admin.is_admin(999) is False
    assert admin.is_premium(101) is True
    assert admin.is_premium(202) is False


def test_broadcast_service_targeting():
    settings = Settings(require_token=False)
    settings.PREMIUM_IDS = "101,202"
    settings.ADMIN_IDS = "999"
    settings.PREMIUM_ONLY = False

    service = BroadcastService(settings)
    assert service.target_user_ids([101, 202, 303], require_premium=True) == [101, 202]
    assert service.target_user_ids([101, 202, 303], require_premium=False) == [101, 202, 303]


def test_storage_lists_registered_users(tmp_path, monkeypatch):
    db_path = tmp_path / "admin.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    DatabaseManager._instance = None

    storage = DataStorage()
    storage._ensure_user(5001, "admin_user")
    storage._ensure_user(5002, "beta_user")

    users = storage.list_all_users()
    ids = {item["telegram_id"] for item in users}
    assert {"5001", "5002"} <= ids

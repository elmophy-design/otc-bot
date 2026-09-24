#!/usr/bin/env python3
"""
Run a walk-forward backtest of the SignalEngine on demo (or provided) data.

Usage:
  python scripts/run_backtest.py
  python scripts/run_backtest.py --asset BTCUSD_otc --bars 500 --expiry 3
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config.settings import Settings
from src.api.data_fetcher import MarketDataFetcher
from src.signals.backtest import BacktestEngine
from src.signals.engine import SignalEngine


async def main() -> None:
    parser = argparse.ArgumentParser(description="OTC Signal Bot – Backtest")
    parser.add_argument("--asset", default="EURUSD_otc")
    parser.add_argument("--bars", type=int, default=400)
    parser.add_argument("--expiry", type=int, default=3, help="Expiry in bars")
    parser.add_argument("--stake", type=float, default=10.0)
    parser.add_argument("--payout", type=float, default=0.80)
    parser.add_argument("--min-confidence", type=float, default=65)
    parser.add_argument("--no-ai", action="store_true")
    args = parser.parse_args()

    settings = Settings(require_token=False)
    settings.MIN_CONFIDENCE = args.min_confidence
    settings.USE_AI = not args.no_ai

    fetcher = MarketDataFetcher(demo_mode=True)
    # Generate a longer series for backtesting
    data = await fetcher.get_historical_data(args.asset, count=args.bars)

    engine = SignalEngine(settings, data_fetcher=None)
    bt = BacktestEngine(
        {
            "initial_balance": 1000.0,
            "stake": args.stake,
            "payout": args.payout,
            "expiry_bars": args.expiry,
            "warmup": 50,
            "min_confidence": args.min_confidence,
        }
    )

    print(f"\nBacktesting {args.asset}  bars={len(data)}  expiry={args.expiry}")
    print("-" * 50)
    result = await bt.run(data, engine, asset=args.asset)
    stats = result.to_dict()

    for k, v in stats.items():
        print(f"  {k:20s}: {v}")

    if result.trades:
        print("\nLast 5 trades:")
        for t in result.trades[-5:]:
            flag = "WIN " if t.won else "LOSS"
            print(
                f"  [{flag}] {t.direction:4s}  entry={t.entry_price:.5f}  "
                f"exit={t.exit_price:.5f}  pnl={t.pnl:+.2f}  conf={t.confidence:.0f}%"
            )
    print()


if __name__ == "__main__":
    asyncio.run(main())

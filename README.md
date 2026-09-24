# OTC Signal Bot v2.0

Professional Telegram bot that generates **CALL / PUT / NO_SIGNAL** trading signals for OTC assets using multi-indicator Technical Analysis (and optional ML hybrid mode).

## Features

- **Multi-indicator TA engine** — RSI, MACD, Bollinger Bands, EMA stack, Stochastic, ADX
- **Strict confluence rules** — requires multiple indicators to agree; never forces a trade
- **Honest NO_SIGNAL** — returns clearly when conditions are not met
- **Hybrid ML mode** (optional) — on-the-fly Gradient Boosting classifier that can confirm or softly override TA
- **Demo mode** — realistic synthetic OHLCV so you can develop and test without live broker credentials
- **Async Telegram bot** — paginated asset menus, rich HTML messages, robust error handling
- **Configurable** — YAML + environment variables

## Quick Start

### 1. Install dependencies

```bash
cd otc-signal-bot
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Configure

```bash
cp .env.example .env
# Edit .env and set at least:
#   TELEGRAM_BOT_TOKEN=your_real_token
#   DEMO_MODE=true
```

### 3. Run offline engine test

```bash
python scripts/test_signal_engine.py
```

### 4. Start the bot

```bash
python -m src.bot.main
```

Open Telegram, send `/start` to your bot, pick an asset, and receive a signal.

## Architecture

```
User (Telegram)
    ↓
Bot handlers  →  SignalEngine  →  MarketDataFetcher
                      ↓                    ↓
               Technical Indicators    Demo / Live OHLCV
               + optional MLPredictor
                      ↓
               ConfidenceScorer
                      ↓
               Formatted message → User
```

### Signal decision logic (summary)

1. Compute RSI, MACD, Bollinger, EMA, Stochastic, ADX
2. Each indicator casts a vote (+1 CALL / −1 PUT / 0 neutral)
3. Require ≥ 3 agreeing votes and net ≥ ±2
4. Extreme RSI softens lagging MACD/EMA so mean-reversion is not blocked
5. Confidence scored from confluence + extremity + ADX
6. (Hybrid) ML vote can confirm or, when TA is silent, produce a high-confidence signal
7. Final gate: confidence ≥ `MIN_CONFIDENCE` (default 70)

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `TELEGRAM_BOT_TOKEN` | — | Required for the bot |
| `DEMO_MODE` | `true` | Use synthetic data when live feed unavailable |
| `MIN_CONFIDENCE` | `70` | Minimum confidence to emit CALL/PUT |
| `USE_AI` | `false` | Enable hybrid ML layer |
| `TECH_WEIGHT` | `0.7` | Weight of TA vs ML when blending |

See `config/signals.yaml` and `config/development.yaml` for indicator parameters and asset lists.

## Project layout

```
otc-signal-bot/
├── config/           # YAML settings + Settings class
├── src/
│   ├── api/          # PocketOption client + data fetcher
│   ├── bot/          # Telegram handlers, keyboards, main
│   ├── signals/      # Engine, indicators, confidence, ML, strategies
│   ├── services/     # Signal service (caching)
│   └── utils/        # Formatters, logger
├── scripts/          # Offline test harness
├── tests/            # Unit tests
└── requirements.txt
```

## Testing

```bash
# Engine unit tests (pytest)
pip install pytest
pytest tests/unit/test_signals/ -v

# Manual pipeline test
python scripts/test_signal_engine.py
```

## Risk notice

This software is for educational and research purposes.  
**Always test on a demo account first.** Past indicator confluence does not guarantee future results. Use proper risk management.

## Next upgrades (roadmap)

- Real PocketOption historical candle protocol
- Persistent ML model save/load (joblib)
- Full backtesting engine with metrics
- PineScript strategy transpilation helpers
- Multi-timeframe confluence
```

## Backtesting

Walk-forward backtest of the signal engine on demo data:

```bash
python scripts/run_backtest.py
python scripts/run_backtest.py --asset BTCUSD_otc --bars 500 --expiry 3 --min-confidence 65
```

Metrics reported: total trades, win rate, return %, max drawdown, profit factor, average confidence.

## Docker

```bash
# Build and run (requires .env with TELEGRAM_BOT_TOKEN)
docker compose up -d --build

# Logs
docker compose logs -f bot

# Stop
docker compose down
```

Models and logs are persisted via volumes (`./models`, `./logs`).

## ML model persistence

When hybrid mode trains a model it is automatically saved to `models/gb_direction.joblib` and reloaded on the next start.

## Roadmap status

| Item | Status |
|------|--------|
| Multi-indicator TA engine | ✅ |
| Strict NO_SIGNAL | ✅ |
| Async Telegram UI | ✅ |
| Demo data layer | ✅ |
| Hybrid ML (train + persist) | ✅ |
| Walk-forward backtester | ✅ |
| Docker packaging | ✅ |
| Live PocketOption candles | ✅ Scaffolding + BotV2 adapter |
| Multi-timeframe confluence | ✅ |
| PineScript helpers | ⏳ Planned |


## Live data & PineScript

- **Live setup:** see [docs/guides/LIVE_DATA.md](docs/guides/LIVE_DATA.md) (SSID capture, protocol notes)
- **PineScript helpers:** see [docs/guides/PINESCRIPT.md](docs/guides/PINESCRIPT.md)


## Live backend (BinaryOptionsTools-v2)

```bash
pip install -r requirements-live.txt   # optional
# LIVE_BACKEND=auto|botv2|native
python scripts/test_live_backend.py
```

See [docs/guides/BOTV2.md](docs/guides/BOTV2.md).

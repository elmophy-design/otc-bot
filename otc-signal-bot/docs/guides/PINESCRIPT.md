# PineScript Helpers

Location: `src/signals/pinescript/`

This is **not** a full Pine → Python compiler. It provides familiar
TradingView-style operators so you can port common strategies quickly.

## Operators (`PineHelper`)

| Pine | Python |
|------|--------|
| `ta.crossover(a,b)` | `PineHelper.crossover(a,b)` |
| `ta.crossunder(a,b)` | `PineHelper.crossunder(a,b)` |
| `ta.rising(s,n)` | `PineHelper.rising(s,n)` |
| `ta.sma(s,n)` | `PineHelper.sma(s,n)` |
| `ta.ema(s,n)` | `PineHelper.ema(s,n)` |
| `ta.rsi(s,n)` | `PineHelper.rsi(s,n)` |
| `ta.macd(...)` | `PineHelper.macd(...)` |

## Built-in strategy votes

```python
from src.signals.pinescript import pine_strategy_vote

vote = pine_strategy_vote(ohlcv_df, style="rsi_macd")
# → {"action": "CALL"|"PUT"|"NEUTRAL", "strength": 0-1, "reason": "..."}
```

Styles: `rsi_macd` (default), `ema_cross`, `supertrend_lite`.

## Registry

`PineStyleStrategy` is registered in `StrategyRegistry` as `"pine"`.

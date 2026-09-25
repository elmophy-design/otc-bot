# OTC Dashboard — Phase 3: Production Signal Engine

This phase connects the dashboard's selected asset + timeframe to the existing production `SignalEngine`.

## What changed

- Added `POST /api/market/signal?asset=...&timeframe=...`.
- Reuses the scanner's existing live broker/data-fetcher connection; it does not create a second broker connection for the signal request.
- Calls `src.signals.engine.SignalEngine` with the live candles.
- Returns the engine's real `CALL`, `PUT`, or `NO_SIGNAL` result, confidence, reason, entry price, confluence, indicators, and timestamp.
- **No trade is placed by this endpoint.** It is analysis-only.
- Dashboard's **Generate Signal** button now calls the API and displays the returned result.

## Apply

From the repository root:

```powershell
python .\phase3\apply_phase3.py
```

Or, after extracting this package, run the included `apply_phase3.py` from the package directory with the repository root as its parent directory.

## Verify

```powershell
.\.venv\Scripts\python.exe -m py_compile .\frontend\src\web\api.py
.\.venv\Scripts\python.exe -m pytest
cd .\frontend
npm run build
cd ..
```

The endpoint requires the existing `X-Dashboard-Key` authentication used by the dashboard API.

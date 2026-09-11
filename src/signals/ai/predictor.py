"""Simple but real ML-based signal predictor (scikit-learn)."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from ...utils.logger import get_logger

logger = get_logger(__name__)

try:
    from sklearn.ensemble import GradientBoostingClassifier
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler

    SKLEARN_AVAILABLE = True
except ImportError:
    SKLEARN_AVAILABLE = False
    logger.warning("scikit-learn not available – ML predictor disabled")


class MLPredictor:
    """
    Lightweight gradient-boosting classifier that predicts
    short-term direction (CALL / PUT / NEUTRAL) from technical features.

    Can train on-the-fly from recent OHLCV history.
    """

    FEATURE_COLS = [
        "rsi",
        "macd_hist",
        "bb_position",
        "stoch_k",
        "adx",
        "ema_slope",
        "price_change_1",
        "price_change_3",
        "volatility",
    ]

    def __init__(self, settings: Any = None):
        self.settings = settings
        self.is_trained = False
        self.pipeline: Optional[Any] = None
        self.min_train_rows = 80

        model_dir = Path("models")
        if settings and hasattr(settings, "config"):
            ml_cfg = (settings.config.get("signals") or {}).get("ml") or {}
            model_dir = Path(ml_cfg.get("model_path", "models"))
        self.model_path = model_dir / "gb_direction.joblib"
        # Attempt to load a previously saved model
        self.load()

    async def predict(
        self, data: pd.DataFrame, indicators: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """
        Return:
          {action: CALL|PUT|NEUTRAL, confidence: 0-100, method: str, proba: {...}}
        """
        if not SKLEARN_AVAILABLE:
            return self._neutral("sklearn_unavailable")

        if data is None or len(data) < 30:
            return self._neutral("insufficient_data")

        features = self._build_feature_row(data, indicators)
        if features is None:
            return self._neutral("feature_error")

        if not self.is_trained:
            trained = self._try_train_from_history(data)
            if not trained:
                return self._neutral("model_not_trained")

        try:
            X = np.array([features], dtype=float)
            proba = self.pipeline.predict_proba(X)[0]
            classes = list(self.pipeline.classes_)
            proba_map = {str(c): float(p) for c, p in zip(classes, proba)}

            best_label = classes[int(np.argmax(proba))]
            confidence = float(np.max(proba)) * 100.0

            action_map = {1: "CALL", -1: "PUT", 0: "NEUTRAL"}
            action = action_map.get(int(best_label), "NEUTRAL")

            if confidence < 55 or action == "NEUTRAL":
                return {
                    "action": "NEUTRAL",
                    "confidence": round(confidence, 1),
                    "method": "ml",
                    "proba": proba_map,
                }

            return {
                "action": action,
                "confidence": round(min(confidence, 95.0), 1),
                "method": "ml",
                "proba": proba_map,
            }
        except Exception as e:
            logger.warning("ML predict failed: %s", e)
            return self._neutral(f"predict_error: {e}")

    def train(self, X: np.ndarray, y: np.ndarray) -> bool:
        """Train the pipeline from feature matrix + labels."""
        if not SKLEARN_AVAILABLE:
            return False
        if len(X) < self.min_train_rows:
            logger.info(
                "Not enough rows to train ML model (%d < %d)",
                len(X),
                self.min_train_rows,
            )
            return False

        try:
            self.pipeline = Pipeline(
                [
                    ("scaler", StandardScaler()),
                    (
                        "clf",
                        GradientBoostingClassifier(
                            n_estimators=80,
                            max_depth=3,
                            learning_rate=0.08,
                            random_state=42,
                        ),
                    ),
                ]
            )
            self.pipeline.fit(X, y)
            self.is_trained = True
            logger.info("ML model trained on %d samples", len(X))
            self.save()  # persist for next run
            return True
        except Exception as e:
            logger.error("ML training failed: %s", e)
            return False

    def _try_train_from_history(self, data: pd.DataFrame) -> bool:
        """Build supervised samples from the OHLCV window and train."""
        try:
            X_list: List[List[float]] = []
            y_list: List[int] = []

            df = data.copy()
            df.columns = [str(c).lower() for c in df.columns]
            close = df["close"].values
            n = len(close)
            if n < self.min_train_rows + 5:
                return False

            for i in range(25, n - 4):
                window = df.iloc[: i + 1]
                feats = self._build_feature_row(window, None)
                if feats is None:
                    continue
                future_ret = (close[i + 3] - close[i]) / (abs(close[i]) + 1e-12)
                if future_ret > 0.0008:
                    label = 1
                elif future_ret < -0.0008:
                    label = -1
                else:
                    label = 0
                X_list.append(feats)
                y_list.append(label)

            if len(X_list) < self.min_train_rows:
                return False

            X = np.array(X_list, dtype=float)
            y = np.array(y_list, dtype=int)
            return self.train(X, y)
        except Exception as e:
            logger.warning("On-the-fly ML training failed: %s", e)
            return False

    def _build_feature_row(
        self, data: pd.DataFrame, indicators: Optional[Dict]
    ) -> Optional[List[float]]:
        """Compute a single feature vector from the latest bar."""
        try:
            from ..technical.indicators import TechnicalIndicators

            df = data.copy()
            df.columns = [str(c).lower() for c in df.columns]
            close = df["close"]

            if indicators is None:
                ind = TechnicalIndicators.compute_all(df)
            else:
                ind = indicators

            def last(s, default=0.0):
                if s is None or len(s) == 0 or pd.isna(s.iloc[-1]):
                    return default
                return float(s.iloc[-1])

            rsi = last(ind.get("rsi"), 50)
            macd_hist = last(ind.get("macd_hist"), 0)
            bb_upper = last(ind.get("bb_upper"), float(close.iloc[-1]))
            bb_lower = last(ind.get("bb_lower"), float(close.iloc[-1]))
            bb_range = bb_upper - bb_lower
            bb_pos = (
                (float(close.iloc[-1]) - bb_lower) / bb_range
                if bb_range > 1e-12
                else 0.5
            )
            stoch_k = last(ind.get("stoch_k"), 50)
            adx = last(ind.get("adx"), 20)

            ema_fast = last(ind.get("ema_fast"), float(close.iloc[-1]))
            ema_slow = last(ind.get("ema_slow"), float(close.iloc[-1]))
            ema_slope = (ema_fast - ema_slow) / (abs(ema_slow) + 1e-12)

            price_change_1 = 0.0
            price_change_3 = 0.0
            if len(close) >= 2:
                price_change_1 = (close.iloc[-1] - close.iloc[-2]) / (
                    abs(close.iloc[-2]) + 1e-12
                )
            if len(close) >= 4:
                price_change_3 = (close.iloc[-1] - close.iloc[-4]) / (
                    abs(close.iloc[-4]) + 1e-12
                )

            vol = float(close.pct_change().tail(14).std() or 0)

            return [
                rsi,
                macd_hist,
                float(bb_pos),
                stoch_k,
                adx,
                float(ema_slope),
                float(price_change_1),
                float(price_change_3),
                vol,
            ]
        except Exception as e:
            logger.debug("Feature build failed: %s", e)
            return None

    @staticmethod
    def _neutral(reason: str) -> Dict[str, Any]:
        return {
            "action": "NEUTRAL",
            "confidence": 0.0,
            "method": reason,
            "proba": {},
        }

    def save(self, path: Optional[Path] = None) -> bool:
        """Persist the trained pipeline to disk (joblib)."""
        if not self.is_trained or self.pipeline is None:
            return False
        path = path or self.model_path
        try:
            import joblib

            path.parent.mkdir(parents=True, exist_ok=True)
            joblib.dump(self.pipeline, path)
            logger.info("ML model saved to %s", path)
            return True
        except Exception as e:
            logger.warning("Could not save ML model: %s", e)
            return False

    def load(self, path: Optional[Path] = None) -> bool:
        """Load a previously trained pipeline from disk."""
        path = path or self.model_path
        if not path.exists():
            return False
        try:
            import joblib

            self.pipeline = joblib.load(path)
            self.is_trained = True
            logger.info("ML model loaded from %s", path)
            return True
        except Exception as e:
            logger.warning("Could not load ML model: %s", e)
            return False

"""Signal Generation Service with caching."""
from __future__ import annotations

from typing import Any, Dict, Optional

from ..utils.logger import get_logger

logger = get_logger(__name__)


class SignalService:
    """Thin service layer around the SignalEngine with optional cache."""

    def __init__(self, signal_engine: Any, cache: Any = None):
        self.signal_engine = signal_engine
        self.cache = cache
        self.default_ttl = 45  # seconds

    async def get_signal(
        self,
        asset: str,
        user_id: Optional[str] = None,
        timeframe: str = "1m",
    ) -> Dict[str, Any]:
        """Return a signal, using cache when available."""
        cache_key = f"signal:{asset}:{timeframe}"

        if self.cache is not None:
            try:
                cached = self.cache.get(cache_key)
                if cached:
                    logger.debug("Cache hit for %s", asset)
                    return cached
            except Exception:
                pass

        signal = await self.signal_engine.generate_signal(asset, timeframe=timeframe)

        if self.cache is not None and signal.get("action") != "NO_SIGNAL":
            try:
                self.cache.set(cache_key, signal, ttl=self.default_ttl)
            except Exception:
                pass

        return signal

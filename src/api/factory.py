"""
Broker client factory.

LIVE_BACKEND:
  auto   – prefer BinaryOptionsToolsV2 if installed + SSID present, else native
  botv2  – force BotV2 adapter (error/fallback if missing)
  native – force built-in Socket.IO client (src.api.client)
"""
from __future__ import annotations

import os
from typing import Any, Protocol, runtime_checkable

from ..utils.logger import get_logger
from .botv2_adapter import BotV2Client, botv2_available, botv2_import_error
from .client import PocketOptionClient

logger = get_logger(__name__)


@runtime_checkable
class BrokerClient(Protocol):
    is_connected: bool

    async def connect(self) -> bool: ...
    async def disconnect(self) -> None: ...
    async def get_candles(self, asset: str, timeframe=..., count: int = ...) -> Any: ...


def resolve_backend(settings: Any) -> str:
    explicit = (
        getattr(settings, "LIVE_BACKEND", None)
        or os.getenv("LIVE_BACKEND", "auto")
    ).strip().lower()
    if explicit in ("botv2", "native", "auto"):
        return explicit
    return "auto"


def create_broker_client(settings: Any) -> Any:
    """
    Return a client with connect/disconnect/get_candles.
    Never raises solely because BotV2 is missing when backend=auto.
    """
    backend = resolve_backend(settings)
    ssid = getattr(settings, "POCKETOPTION_SSID", None) or ""
    has_ssid = bool(str(ssid).strip()) and "your_" not in str(ssid).lower()

    if backend == "botv2":
        if not botv2_available():
            logger.error(
                "LIVE_BACKEND=botv2 but BinaryOptionsToolsV2 is not installed: %s",
                botv2_import_error(),
            )
            logger.info("Falling back to native PocketOptionClient")
            return PocketOptionClient(settings)
        logger.info("Using BinaryOptionsToolsV2 backend")
        return BotV2Client(settings)

    if backend == "native":
        logger.info("Using native PocketOptionClient backend")
        return PocketOptionClient(settings)

    # auto
    if botv2_available() and has_ssid:
        logger.info("LIVE_BACKEND=auto -> BinaryOptionsToolsV2 (SSID present)")
        return BotV2Client(settings)

    if botv2_available() and not has_ssid:
        logger.info(
            "LIVE_BACKEND=auto -> BotV2 installed but no SSID; using native client"
        )
    elif not botv2_available():
        logger.info(
            "LIVE_BACKEND=auto -> BinaryOptionsToolsV2 not available (%s); using native",
            botv2_import_error(),
        )

    return PocketOptionClient(settings)

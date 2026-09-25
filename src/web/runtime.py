"""Runtime bindings shared by the Telegram bot and dashboard API.

The dashboard must never create a second broker session.  The Telegram bot
creates the broker client once, then binds that live client/data fetcher/signal
engine here for read/preview/execute API calls.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional


@dataclass
class DashboardRuntime:
    settings: Any
    api_client: Any
    data_fetcher: Any
    signal_engine: Any
    storage: Any
    application: Any = None


_runtime: Optional[DashboardRuntime] = None


def bind_runtime(
    *, settings: Any, api_client: Any, data_fetcher: Any, signal_engine: Any,
    storage: Any, application: Any = None,
) -> DashboardRuntime:
    global _runtime
    _runtime = DashboardRuntime(
        settings=settings,
        api_client=api_client,
        data_fetcher=data_fetcher,
        signal_engine=signal_engine,
        storage=storage,
        application=application,
    )
    return _runtime


def get_runtime() -> DashboardRuntime:
    if _runtime is None:
        raise RuntimeError("Dashboard runtime has not been bound by the trading bot")
    return _runtime

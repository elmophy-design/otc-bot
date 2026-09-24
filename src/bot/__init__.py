"""Telegram Bot Module"""

from .handlers import start_command, help_command
from .keyboards import AssetKeyboardBuilder
from .pagination import PaginationManager


def __getattr__(name):
    """Lazy-load OTCTradingBot to avoid importing main during package startup."""
    if name == "OTCTradingBot":
        from .main import OTCTradingBot
        return OTCTradingBot

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "OTCTradingBot",
    "start_command",
    "help_command",
    "AssetKeyboardBuilder",
    "PaginationManager",
]

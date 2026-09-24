"""API Data Models"""
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

@dataclass
class Candle:
    """OHLCV Candlestick"""
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float

@dataclass
class Tick:
    """Real-time Price Tick"""
    asset: str
    price: float
    timestamp: datetime
    volume: Optional[float] = None

@dataclass
class Order:
    """Trade Order"""
    asset: str
    direction: str
    amount: float
    entry_price: float
    expiry_time: datetime
    order_id: Optional[str] = None
    status: str = 'pending'

"""WebSocket Connection Manager"""
from typing import Optional, Callable
from ..utils.logger import get_logger

logger = get_logger(__name__)

class WebSocketConnection:
    """Manages WebSocket connections with auto-reconnect"""
    
    def __init__(self, url: str, auto_reconnect: bool = True):
        self.url = url
        self.auto_reconnect = auto_reconnect
        self.is_connected = False
        self.reconnect_attempts = 0
        self.max_reconnect_attempts = 5

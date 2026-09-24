"""Cache Management with Redis Support"""
import json
from typing import Any, Optional
from datetime import datetime, timedelta
from ..utils.logger import get_logger

logger = get_logger(__name__)

class CacheManager:
    """Professional Cache Manager"""
    
    _instance = None
    _cache = {}
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(CacheManager, cls).__new__(cls)
        return cls._instance
    
    def get(self, key: str, default: Any = None) -> Any:
        """Get from cache"""
        if key in self._cache:
            value, expiry = self._cache[key]
            if expiry is None or expiry > datetime.now():
                return value
        return default
    
    def set(self, key: str, value: Any, ttl: int = 300) -> bool:
        """Set in cache with TTL"""
        expiry = datetime.now() + timedelta(seconds=ttl)
        self._cache[key] = (value, expiry)
        return True
    
    def delete(self, key: str) -> bool:
        """Delete from cache"""
        if key in self._cache:
            del self._cache[key]
            return True
        return False
    
    def clear(self) -> bool:
        """Clear cache"""
        self._cache.clear()
        return True

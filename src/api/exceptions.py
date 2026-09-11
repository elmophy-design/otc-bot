"""Custom API Exceptions"""

class APIError(Exception):
    """Base API exception"""
    pass

class ConnectionError(APIError):
    """Connection error"""
    pass

class AuthenticationError(APIError):
    """Authentication error"""
    pass

class DataFetchError(APIError):
    """Data fetching error"""
    pass

class RateLimitError(APIError):
    """Rate limit exceeded"""
    pass

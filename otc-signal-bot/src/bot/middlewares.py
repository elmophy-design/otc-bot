"""Bot Middlewares"""
from typing import Dict
from collections import defaultdict
from ..utils.logger import get_logger

logger = get_logger(__name__)

class RateLimitMiddleware:
    """Rate limiting to prevent abuse"""
    
    def __init__(self, limit: int = 10, period: int = 60):
        self.limit = limit
        self.period = period
        self.user_requests: Dict[int, list] = defaultdict(list)
    
    async def __call__(self, update, context):
        """Check rate limit"""
        if not update.effective_user:
            return True
        
        import time
        user_id = update.effective_user.id
        current_time = time.time()
        
        # Clean old requests
        self.user_requests[user_id] = [
            t for t in self.user_requests[user_id]
            if current_time - t < self.period
        ]
        
        # Check limit
        if len(self.user_requests[user_id]) >= self.limit:
            logger.warning(f"Rate limit exceeded for user {user_id}")
            return False
        
        self.user_requests[user_id].append(current_time)
        return True

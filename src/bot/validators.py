"""Input Validation Utilities"""
import re

class BotValidators:
    """Validation utilities for bot inputs"""
    
    @staticmethod
    def validate_asset(asset: str) -> bool:
        """Validate asset symbol format"""
        if not asset:
            return False
        if not asset.endswith('_otc'):
            return False
        pattern = r'^[A-Z0-9_]+_otc$'
        return bool(re.match(pattern, asset))
    
    @staticmethod
    def validate_amount(amount: float, min_amount: float = 1.0, max_amount: float = 100.0) -> tuple:
        """Validate trade amount"""
        if amount <= 0:
            return False, "Amount must be positive"
        if amount < min_amount:
            return False, f"Minimum amount is ${min_amount:.2f}"
        if amount > max_amount:
            return False, f"Maximum amount is ${max_amount:.2f}"
        return True, "Valid"

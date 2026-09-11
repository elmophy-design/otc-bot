"""Admin and premium access controls for the Telegram bot."""
from __future__ import annotations

from typing import Iterable


class AdminService:
    """Simple role-based access control for admin and premium users."""

    def __init__(self, settings):
        self.settings = settings
        self.admin_ids = self._parse_csv(getattr(settings, "ADMIN_IDS", ""))
        self.premium_ids = self._parse_csv(getattr(settings, "PREMIUM_IDS", ""))
        self.premium_only = bool(getattr(settings, "PREMIUM_ONLY", False))

    @staticmethod
    def _parse_csv(value: str) -> set[int]:
        if not value:
            return set()
        return {int(item.strip()) for item in str(value).split(",") if item.strip()}

    def is_admin(self, user_id: int) -> bool:
        return int(user_id) in self.admin_ids

    def is_premium(self, user_id: int) -> bool:
        return int(user_id) in self.premium_ids

    def can_access(self, user_id: int, premium_required: bool = False) -> bool:
        if self.is_admin(user_id):
            return True
        if premium_required or self.premium_only:
            return self.is_premium(user_id)
        return True

    def dashboard_summary(self, user_id: int) -> dict:
        return {
            "user_id": user_id,
            "is_admin": self.is_admin(user_id),
            "is_premium": self.is_premium(user_id),
            "has_access": self.can_access(user_id),
        }

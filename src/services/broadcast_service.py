"""Broadcasting and premium targeting for Telegram announcements."""
from __future__ import annotations

from typing import Iterable, List


class BroadcastService:
    """Route admin messages to the correct audience based on role and access rules."""

    def __init__(self, settings):
        self.settings = settings
        self.premium_ids = self._parse_ids(getattr(settings, "PREMIUM_IDS", ""))
        self.admin_ids = self._parse_ids(getattr(settings, "ADMIN_IDS", ""))

    @staticmethod
    def _parse_ids(value: str) -> set[int]:
        if not value:
            return set()
        return {int(item.strip()) for item in str(value).split(",") if item.strip()}

    def target_user_ids(
        self,
        user_ids: Iterable[int],
        require_premium: bool = False,
        include_admins: bool = True,
    ) -> List[int]:
        targets = []
        for user_id in user_ids:
            uid = int(user_id)
            if include_admins and uid in self.admin_ids:
                targets.append(uid)
                continue
            if require_premium and uid not in self.premium_ids:
                continue
            if not require_premium or uid in self.premium_ids:
                targets.append(uid)
        return targets

    def build_message(self, text: str, premium_only: bool = False) -> str:
        prefix = "🔔 Premium Alert" if premium_only else "📣 Broadcast"
        return f"{prefix}\n\n{text}"

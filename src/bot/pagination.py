"""Pagination Manager for Asset Lists"""
from __future__ import annotations

from typing import List


class PaginationManager:
    """Manages pagination and category filtering for asset lists."""

    def __init__(self, settings):
        self.settings = settings
        self.assets_per_page = 8

    def get_all_assets(self) -> List[str]:
        """Return the full OTC asset list."""
        return list(getattr(self.settings, "OTC_ASSETS", []) or [])

    def get_assets_by_category(self, category: str) -> List[str]:
        """Get assets filtered by category (or all)."""
        if not category or category == "all":
            return self.get_all_assets()

        categories = {}
        if hasattr(self.settings, "config") and isinstance(self.settings.config, dict):
            categories = (
                self.settings.config.get("assets", {}).get("categories", {}) or {}
            )
        return list(categories.get(category, []))

    def get_total_pages(self, assets: List[str]) -> int:
        if not assets:
            return 0
        return (len(assets) + self.assets_per_page - 1) // self.assets_per_page

    def get_page_assets(self, assets: List[str], page: int) -> List[str]:
        if not assets:
            return []
        start = page * self.assets_per_page
        end = min(start + self.assets_per_page, len(assets))
        return assets[start:end]

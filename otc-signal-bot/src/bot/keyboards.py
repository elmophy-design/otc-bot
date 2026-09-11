"""Inline Keyboard Builders"""
from __future__ import annotations

from typing import List, Optional

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


class AssetKeyboardBuilder:
    """Professional keyboard builder with pagination support."""

    def __init__(self, settings):
        self.settings = settings
        self.assets_per_page = 8

    def build_main_menu(self) -> InlineKeyboardMarkup:
        keyboard = [
            [
                InlineKeyboardButton("💱 Forex", callback_data="category_forex"),
                InlineKeyboardButton("🥇 Metals", callback_data="category_metals"),
            ],
            [
                InlineKeyboardButton("₿ Crypto", callback_data="category_crypto"),
                InlineKeyboardButton("📊 All Assets", callback_data="category_all"),
            ],
            [
                InlineKeyboardButton("📊 My Analytics", callback_data="analytics_inline"),
                InlineKeyboardButton("🛡 Admin", callback_data="admin_menu"),
            ],
            [
                InlineKeyboardButton("❓ Help", callback_data="help_inline"),
            ],
        ]
        return InlineKeyboardMarkup(keyboard)

    def build_asset_list(
        self,
        assets: List[str],
        page: int = 0,
        category: str = "all",
    ) -> InlineKeyboardMarkup:
        """Build a paginated list of assets."""
        if not assets:
            return self.build_back_button()

        start = page * self.assets_per_page
        end = min(start + self.assets_per_page, len(assets))
        page_assets = assets[start:end]

        keyboard: List[List[InlineKeyboardButton]] = []
        row: List[InlineKeyboardButton] = []

        for asset in page_assets:
            display = asset.replace("_otc", "").replace("_", "/")
            row.append(
                InlineKeyboardButton(
                    f"📊 {display}",
                    callback_data=f"signal_{asset}",
                )
            )
            if len(row) == 2:
                keyboard.append(row)
                row = []
        if row:
            keyboard.append(row)

        # Navigation
        total_pages = max(
            1, (len(assets) + self.assets_per_page - 1) // self.assets_per_page
        )
        nav: List[InlineKeyboardButton] = []
        if page > 0:
            nav.append(
                InlineKeyboardButton(
                    "⬅️ Prev", callback_data=f"page_{category}_{page - 1}"
                )
            )
        nav.append(
            InlineKeyboardButton(
                f"📄 {page + 1}/{total_pages}", callback_data="noop"
            )
        )
        if page < total_pages - 1:
            nav.append(
                InlineKeyboardButton(
                    "Next ➡️", callback_data=f"page_{category}_{page + 1}"
                )
            )
        if nav:
            keyboard.append(nav)

        keyboard.append(
            [InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]
        )
        return InlineKeyboardMarkup(keyboard)

    # Backward-compatible alias
    def build_asset_pagination(
        self, assets: List[str], page: int = 0, category: str = "all"
    ) -> InlineKeyboardMarkup:
        return self.build_asset_list(assets, page=page, category=category)

    def build_signal_actions(self, asset: str) -> InlineKeyboardMarkup:
        keyboard = [
            [
                InlineKeyboardButton(
                    "🔄 Refresh", callback_data=f"signal_{asset}"
                ),
            ],
            [
                InlineKeyboardButton(
                    "🔙 Assets", callback_data="category_all"
                ),
                InlineKeyboardButton(
                    "🏠 Menu", callback_data="main_menu"
                ),
            ],
        ]
        return InlineKeyboardMarkup(keyboard)

    def build_back_button(self) -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(
            [[InlineKeyboardButton("🔙 Back", callback_data="main_menu")]]
        )

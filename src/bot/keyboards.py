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

    def build_signal_actions(
        self, asset: str, action: Optional[str] = None
    ) -> InlineKeyboardMarkup:
        keyboard: List[List[InlineKeyboardButton]] = []

        # Trade buttons only when we have a clear CALL/PUT
        if action in ("CALL", "PUT"):
            keyboard.append(
                [
                    InlineKeyboardButton(
                        f"✅ Execute {action}",
                        callback_data=f"trade_{action}_{asset}",
                    ),
                ]
            )

        # Analysis timeframe selector
        keyboard.append(
            [
                InlineKeyboardButton("1m", callback_data=f"tf_1m_{asset}"),
                InlineKeyboardButton("5m", callback_data=f"tf_5m_{asset}"),
                InlineKeyboardButton("15m", callback_data=f"tf_15m_{asset}"),
            ]
        )

        keyboard.append(
            [
                InlineKeyboardButton(
                    "🔄 Refresh", callback_data=f"signal_{asset}"
                ),
            ]
        )
        keyboard.append(
            [
                InlineKeyboardButton(
                    "🔙 Assets", callback_data="category_all"
                ),
                InlineKeyboardButton(
                    "🏠 Menu", callback_data="main_menu"
                ),
            ]
        )
        return InlineKeyboardMarkup(keyboard)

    AMOUNT_PRESETS = [200, 500, 1000, 1600, 3000, 5000]

    def build_amount_selector(
        self, asset: str, direction: str
    ) -> InlineKeyboardMarkup:
        """Choose the trade stake before picking an expiry."""
        buttons = [
            InlineKeyboardButton(
                f"${amt:,}", callback_data=f"amt_{amt}_{direction}_{asset}"
            )
            for amt in self.AMOUNT_PRESETS
        ]
        # 3 per row
        rows = [buttons[i : i + 3] for i in range(0, len(buttons), 3)]
        rows.append(
            [InlineKeyboardButton("❌ Cancel", callback_data=f"signal_{asset}")]
        )
        return InlineKeyboardMarkup(rows)

    def build_expiry_selector(
        self, asset: str, direction: str, amount: float
    ) -> InlineKeyboardMarkup:
        """Choose trade expiry duration before placing the order."""
        options = [
            ("30s", 30),
            ("1m", 60),
            ("2m", 120),
            ("5m", 300),
        ]
        amt_str = f"{amount:g}"  # e.g. 1000 not 1000.0
        row = [
            InlineKeyboardButton(
                label,
                callback_data=f"expiry_{direction}_{secs}_{amt_str}_{asset}",
            )
            for label, secs in options
        ]
        keyboard = [
            row,
            [
                InlineKeyboardButton(
                    "❌ Cancel", callback_data=f"signal_{asset}"
                )
            ],
        ]
        return InlineKeyboardMarkup(keyboard)

    def build_back_button(self) -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(
            [[InlineKeyboardButton("🔙 Back", callback_data="main_menu")]]
        )

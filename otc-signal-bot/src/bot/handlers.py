"""Bot Handlers for Commands and Callbacks"""
from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from config.settings import get_settings
from ..data.storage import DataStorage
from ..services.admin_service import AdminService
from ..services.broadcast_service import BroadcastService
from ..utils.formatters import format_signal_message
from ..utils.logger import get_logger
from .keyboards import AssetKeyboardBuilder
from .pagination import PaginationManager

logger = get_logger(__name__)
settings = get_settings()
keyboard_builder = AssetKeyboardBuilder(settings)
pagination_manager = PaginationManager(settings)


async def analytics_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Display a professional performance summary for the current user."""
    user = update.effective_user
    if user is None:
        await update.message.reply_text("Unable to identify the current user.")
        return

    admin_service = context.bot_data.get("admin_service") or AdminService(settings)
    storage = context.bot_data.get("storage") or DataStorage()

    # Premium gating: admins always have access; others need premium
    if not admin_service.is_admin(user.id) and not admin_service.is_premium(user.id):
        await update.message.reply_text(
            "🔒 <b>Premium Feature</b>\n\nAnalytics are available to premium members only.\n"
            "Please contact an admin to upgrade your account.",
            parse_mode="HTML",
        )
        return

    summary = storage.get_performance_summary(user.id, limit=10)

    recent = summary.get("recent_signals") or []
    lines = [
        "📊 <b>Signal Performance Summary</b>",
        f"Total signals: <b>{summary.get('total_signals', 0)}</b>",
        f"CALL: <b>{summary.get('call_count', 0)}</b>  |  PUT: <b>{summary.get('put_count', 0)}</b>  |  NO_SIGNAL: <b>{summary.get('no_signal_count', 0)}</b>",
        f"Average confidence: <b>{summary.get('avg_confidence', 0):.1f}%</b>",
        "",
        "<b>Recent signals</b>",
    ]

    if not recent:
        lines.append("No signal history yet.")
    else:
        for item in recent[:5]:
            asset = item.get("asset", "Unknown")
            action = item.get("action", "NO_SIGNAL")
            confidence = item.get("confidence", 0)
            lines.append(f"• {asset}: <b>{action}</b> ({confidence:.1f}%)")

    if getattr(update, "callback_query", None) is not None:
        await update.callback_query.edit_message_text("\n".join(lines), parse_mode="HTML")
    else:
        await update.message.reply_text("\n".join(lines), parse_mode="HTML")


async def analytics_inline_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Callback wrapper for analytics requests from the main menu."""
    await analytics_command(update, context)


async def admin_dashboard_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /admin command - route to admin menu."""
    user = update.effective_user
    if user is None:
        await update.message.reply_text("Unable to identify the current user.")
        return

    admin_service = context.bot_data.get("admin_service") or AdminService(settings)
    if not admin_service.can_access(user.id):
        await update.message.reply_text("⛔ <b>Access denied</b>\nOnly admins can access this dashboard.", parse_mode="HTML")
        return

    storage = context.bot_data.get("storage") or DataStorage()
    stats = storage.get_user_stats()
    premium_count = len(admin_service.premium_ids)
    admin_count = len(admin_service.admin_ids)

    lines = [
        "🛡 <b>Admin Control Panel</b>",
        "",
        "<b>Bot Status</b>",
        f"• Total users: <b>{stats.get('total_users', 0)}</b>",
        f"• Premium members: <b>{premium_count}</b>",
        f"• Admin accounts: <b>{admin_count}</b>",
        "",
        "<b>Actions</b>",
        "Select an option below to manage the bot.",
    ]

    keyboard = [
        [InlineKeyboardButton("📊 User List", callback_data="admin_users")],
        [InlineKeyboardButton("📢 Send Broadcast", callback_data="admin_broadcast")],
        [InlineKeyboardButton("⚙️ Bot Settings", callback_data="admin_settings")],
        [InlineKeyboardButton("📝 Operation Logs", callback_data="admin_logs")],
        [InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")],
    ]

    await update.message.reply_text(
        "\n".join(lines),
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command."""
    user = update.effective_user
    demo = getattr(settings, "DEMO_MODE", True)
    mode_badge = "🧪 DEMO" if demo else "🔴 LIVE"

    welcome = f"""
🎯 <b>OTC Signal Bot v2.0</b>  {mode_badge}

Welcome {user.first_name}! 👋

Professional trading signals powered by:
• 📊 Multi-indicator Technical Analysis
• 📈 RSI · MACD · Bollinger · EMA · Stochastic · ADX
• ⏳ Strict NO_SIGNAL when conditions are unclear

<b>Quick Start:</b>
1. Tap <b>📊 All Assets</b> or a category
2. Select an asset
3. Receive an instant, honest signal

⚠️ <i>Always use proper risk management. Demo first.</i>
""".strip()

    await update.message.reply_text(
        welcome,
        parse_mode="HTML",
        reply_markup=keyboard_builder.build_main_menu(),
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /help command."""
    help_text = """
<b>📖 Help Guide</b>

<b>How to get signals</b>
1️⃣ Tap <b>📊 All Assets</b> or a category
2️⃣ Choose an asset
3️⃣ Receive the analysis instantly

<b>Signal Types</b>
📈 <b>CALL</b> — confluence expects price to rise
📉 <b>PUT</b> — confluence expects price to fall
⏳ <b>NO_SIGNAL</b> — indicators disagree or are weak

The engine requires multiple indicators to agree before emitting a CALL or PUT. This keeps the bot honest.

<i>Use /start to return to the main menu.</i>
""".strip()
    if getattr(update, "callback_query", None) is not None:
        await update.callback_query.edit_message_text(help_text, parse_mode="HTML")
    else:
        await update.message.reply_text(help_text, parse_mode="HTML")


async def help_inline_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Callback wrapper for help requests from the main menu."""
    await help_command(update, context)


async def broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin-only broadcast command that sends a message to registered users."""
    user = update.effective_user
    if user is None:
        await update.message.reply_text("Unable to identify the current user.")
        return

    admin_service = context.bot_data.get("admin_service") or AdminService(settings)
    if not admin_service.can_access(user.id):
        await update.message.reply_text("⛔ <b>Access denied</b>\nOnly admins can send broadcasts.", parse_mode="HTML")
        return

    message_text = " ".join(context.args).strip()
    if not message_text:
        await update.message.reply_text(
            "Usage: /broadcast <message>\nExample: /broadcast Market update: EURUSD is active.",
            parse_mode="HTML",
        )
        return

    storage = context.bot_data.get("storage") or DataStorage()
    broadcast_service = context.bot_data.get("broadcast_service") or BroadcastService(settings)
    recipients = storage.list_all_users()
    user_ids = [int(item.get("telegram_id", 0)) for item in recipients if item.get("telegram_id")]
    targets = broadcast_service.target_user_ids(user_ids, require_premium=False, include_admins=True)

    sent = 0
    failed = 0
    payload = broadcast_service.build_message(message_text, premium_only=False)

    for target_id in targets:
        try:
            await context.bot.send_message(chat_id=target_id, text=payload, parse_mode="HTML")
            sent += 1
        except Exception:
            failed += 1

    await update.message.reply_text(
        f"📣 Broadcast complete\nSent: <b>{sent}</b>\nFailed: <b>{failed}</b>\nTargeted users: <b>{len(targets)}</b>",
        parse_mode="HTML",
    )


async def signal_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle signal request for a specific asset."""
    query = update.callback_query
    await query.answer()

    asset = (query.data or "").replace("signal_", "").strip()
    if not asset:
        await query.edit_message_text("❌ Invalid asset selected.")
        return

    await query.edit_message_text(
        f"🔍 Analyzing <b>{asset}</b>…",
        parse_mode="HTML",
    )

    try:
        signal_engine = context.bot_data.get("signal_engine")
        if signal_engine is None:
            # Lazy fallback (should rarely happen if main.py initialized correctly)
            from ..api.factory import create_broker_client
            from ..api.data_fetcher import MarketDataFetcher
            from ..signals.engine import SignalEngine

            api_client = create_broker_client(settings)
            await api_client.connect()
            data_fetcher = MarketDataFetcher(
                api_client, demo_mode=getattr(settings, "DEMO_MODE", True)
            )
            signal_engine = SignalEngine(settings, data_fetcher)
            context.bot_data["signal_engine"] = signal_engine
            context.bot_data["api_client"] = api_client

        signal = await signal_engine.generate_signal(asset)
        storage = context.bot_data.get("storage") or DataStorage()
        user_id = query.from_user.id if query.from_user else 0
        if user_id:
            storage.save_signal(user_id, asset, signal)
        message = format_signal_message(signal)

        await query.edit_message_text(
            message,
            parse_mode="HTML",
            reply_markup=keyboard_builder.build_signal_actions(asset),
        )

    except Exception as e:
        logger.exception("Signal error for %s", asset)
        await query.edit_message_text(
            f"⚠️ Error analyzing <b>{asset}</b>.\n<code>{str(e)[:120]}</code>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "🔄 Retry", callback_data=f"signal_{asset}"
                        ),
                        InlineKeyboardButton(
                            "🔙 Back", callback_data="main_menu"
                        ),
                    ]
                ]
            ),
        )


async def category_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle category selection."""
    query = update.callback_query
    await query.answer()

    category = (query.data or "").replace("category_", "").strip()
    assets = pagination_manager.get_assets_by_category(category)

    if not assets:
        await query.edit_message_text(
            "⚠️ No assets found in this category.",
            reply_markup=keyboard_builder.build_back_button(),
        )
        return

    await query.edit_message_text(
        f"📂 <b>{category.title()}</b> assets\nSelect one to analyze:",
        parse_mode="HTML",
        reply_markup=keyboard_builder.build_asset_list(assets, page=0, category=category),
    )


async def pagination_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle pagination of asset lists."""
    query = update.callback_query
    await query.answer()

    # Expected format: page_{category}_{page_number} or page_all_{page_number}
    parts = (query.data or "").split("_")
    try:
        if len(parts) >= 3:
            category = parts[1]
            page = int(parts[2])
        else:
            category = "all"
            page = 0
    except (ValueError, IndexError):
        category = "all"
        page = 0

    if category == "all":
        assets = pagination_manager.get_all_assets()
    else:
        assets = pagination_manager.get_assets_by_category(category)

    await query.edit_message_text(
        f"📂 <b>{category.title()}</b> assets (page {page + 1})",
        parse_mode="HTML",
        reply_markup=keyboard_builder.build_asset_list(
            assets, page=page, category=category
        ),
    )


async def admin_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Display admin menu with operational actions."""
    query = update.callback_query
    await query.answer()

    user = query.from_user
    if user is None:
        await query.edit_message_text("Unable to identify the current user.")
        return

    admin_service = context.bot_data.get("admin_service") or AdminService(settings)
    if not admin_service.can_access(user.id):
        await query.edit_message_text("⛔ <b>Access denied</b>\nOnly admins can access this menu.", parse_mode="HTML")
        return

    storage = context.bot_data.get("storage") or DataStorage()
    stats = storage.get_user_stats()
    premium_count = len(admin_service.premium_ids)
    admin_count = len(admin_service.admin_ids)

    lines = [
        "🛡 <b>Admin Control Panel</b>",
        "",
        "<b>Bot Status</b>",
        f"• Total users: <b>{stats.get('total_users', 0)}</b>",
        f"• Premium members: <b>{premium_count}</b>",
        f"• Admin accounts: <b>{admin_count}</b>",
        "",
        "<b>Actions</b>",
        "Select an option below to manage the bot.",
    ]

    keyboard = [
        [InlineKeyboardButton("📊 User List", callback_data="admin_users")],
        [InlineKeyboardButton("📢 Send Broadcast", callback_data="admin_broadcast")],
        [InlineKeyboardButton("⚙️ Bot Settings", callback_data="admin_settings")],
        [InlineKeyboardButton("📝 Operation Logs", callback_data="admin_logs")],
        [InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")],
    ]

    await query.edit_message_text(
        "\n".join(lines),
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def admin_users_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show registered users and their premium status."""
    query = update.callback_query
    await query.answer()

    user = query.from_user
    admin_service = context.bot_data.get("admin_service") or AdminService(settings)
    if not admin_service.can_access(user.id):
        await query.edit_message_text("⛔ Access denied", parse_mode="HTML")
        return

    storage = context.bot_data.get("storage") or DataStorage()
    users = storage.list_all_users(limit=20)

    lines = ["👥 <b>Registered Users (Last 20)</b>", ""]
    for user_data in users:
        telegram_id = user_data.get("telegram_id", "unknown")
        username = user_data.get("username") or user_data.get("first_name") or "unknown"
        is_premium = telegram_id in {str(uid) for uid in admin_service.premium_ids}
        badge = "💎" if is_premium else "🆓"
        lines.append(f"{badge} {username} ({telegram_id})")

    keyboard = [
        [InlineKeyboardButton("🔙 Back", callback_data="admin_menu")],
        [InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")],
    ]

    await query.edit_message_text(
        "\n".join(lines),
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def admin_broadcast_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Prompt admin to send a broadcast message."""
    query = update.callback_query
    await query.answer()

    user = query.from_user
    admin_service = context.bot_data.get("admin_service") or AdminService(settings)
    if not admin_service.can_access(user.id):
        await query.edit_message_text("⛔ Access denied", parse_mode="HTML")
        return

    lines = [
        "📢 <b>Send Broadcast Message</b>",
        "",
        "Reply to this message with your broadcast text.",
        "The message will be sent to all registered users.",
    ]

    keyboard = [
        [InlineKeyboardButton("🔙 Back", callback_data="admin_menu")],
        [InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")],
    ]

    await query.edit_message_text(
        "\n".join(lines),
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def admin_settings_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show bot settings and configuration status."""
    query = update.callback_query
    await query.answer()

    user = query.from_user
    admin_service = context.bot_data.get("admin_service") or AdminService(settings)
    if not admin_service.can_access(user.id):
        await query.edit_message_text("⛔ Access denied", parse_mode="HTML")
        return

    demo_mode = getattr(settings, "DEMO_MODE", True)
    min_confidence = getattr(settings, "MIN_CONFIDENCE", 70)
    premium_only = getattr(settings, "PREMIUM_ONLY", False)

    lines = [
        "⚙️ <b>Bot Configuration</b>",
        "",
        "<b>Trading Mode</b>",
        f"• Demo mode: <b>{'ON' if demo_mode else 'OFF'}</b>",
        "",
        "<b>Signal Engine</b>",
        f"• Min confidence: <b>{min_confidence}%</b>",
        "",
        "<b>Access Control</b>",
        f"• Premium only: <b>{'ON' if premium_only else 'OFF'}</b>",
    ]

    keyboard = [
        [InlineKeyboardButton("🔙 Back", callback_data="admin_menu")],
        [InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")],
    ]

    await query.edit_message_text(
        "\n".join(lines),
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def admin_logs_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show recent operation logs for the bot."""
    query = update.callback_query
    await query.answer()

    user = query.from_user
    admin_service = context.bot_data.get("admin_service") or AdminService(settings)
    if not admin_service.can_access(user.id):
        await query.edit_message_text("⛔ Access denied", parse_mode="HTML")
        return

    storage = context.bot_data.get("storage") or DataStorage()
    recent_signals = storage.get_recent_signals(user_id=user.id, limit=10)

    lines = [
        "📝 <b>Recent Operations</b>",
        f"Last {len(recent_signals)} signals processed:",
        "",
    ]

    if not recent_signals:
        lines.append("No activity yet.")
    else:
        for sig in recent_signals:
            asset = sig.get("asset", "?")
            action = sig.get("action", "?")
            confidence = sig.get("confidence", 0)
            created = sig.get("created_at", "?")
            lines.append(f"• {asset} → {action} ({confidence:.0f}%) at {created[:10]}")

    keyboard = [
        [InlineKeyboardButton("🔙 Back", callback_data="admin_menu")],
        [InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")],
    ]

    await query.edit_message_text(
        "\n".join(lines),
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )

"""Bot Handlers for Commands and Callbacks"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

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
async def _safe_reply(update: Update, text: str, **kwargs):
    """
    Safely respond to any Telegram update.

    Handles normal messages, callback queries, and updates
    that do not contain a message.
    """
    try:
        message = update.effective_message

        if message is not None:
            return await message.reply_text(text, **kwargs)

        query = update.callback_query

        if query is not None:
            return await query.edit_message_text(text, **kwargs)

        logger.warning(
            "No reply target available for Telegram update_id=%s",
            getattr(update, "update_id", None),
        )

    except Exception:
        logger.exception(
            "Failed to send Telegram response for update_id=%s",
            getattr(update, "update_id", None),
        )

    return None
# Per-asset signal cooldown (professional anti-spam)
_signal_cooldown: dict[str, datetime] = {}
COOLDOWN_MINUTES = 3

# When each (user, asset) last saw a fresh signal generated — used to
# block executing a trade against a stale quote if too much time has
# passed between "Analyze" and tapping "Execute".
_signal_freshness: dict[tuple[int, str], datetime] = {}
SIGNAL_STALE_SECONDS = 90

# Rotating quarter-circle frames give a genuine spinning-icon effect as
# the message is edited in place while analysis runs.
_SPINNER_FRAMES = ["◐", "◓", "◑", "◒"]


async def _run_with_spinner(query, label: str, coro):
    """Run `coro` while editing `query`'s message with a rotating icon in
    front of `label` every ~900ms, so long-running analysis/fetch calls
    show visible progress instead of a static message. Returns whatever
    `coro` resolves to (exceptions propagate after the spinner stops)."""
    stop = asyncio.Event()

    async def _spin():
        i = 0
        while not stop.is_set():
            frame = _SPINNER_FRAMES[i % len(_SPINNER_FRAMES)]
            try:
                await query.edit_message_text(f"{frame} {label}", parse_mode="HTML")
            except Exception:
                pass  # "message not modified" / rate limit - just skip a frame
            i += 1
            try:
                await asyncio.wait_for(stop.wait(), timeout=0.9)
            except asyncio.TimeoutError:
                pass

    task = asyncio.create_task(_spin())
    try:
        return await coro
    finally:
        stop.set()
        await task


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
    trade_stats = storage.get_trade_stats(user_id=user.id, limit=10)

    recent = summary.get("recent_signals") or []
    lines = [
        "📊 <b>Signal Performance Summary</b>",
        f"Total signals: <b>{summary.get('total_signals', 0)}</b>",
        f"CALL: <b>{summary.get('call_count', 0)}</b>  |  PUT: <b>{summary.get('put_count', 0)}</b>  |  NO_SIGNAL: <b>{summary.get('no_signal_count', 0)}</b>",
        f"Average confidence: <b>{summary.get('avg_confidence', 0):.1f}%</b>",
        "",
        "<b>Executed trades</b>",
        f"Closed: <b>{trade_stats.get('total_closed', 0)}</b>  |  "
        f"Win rate: <b>{trade_stats.get('win_rate', 0):.1f}%</b> "
        f"({trade_stats.get('wins', 0)}W / {trade_stats.get('losses', 0)}L)",
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

    report_keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📅 Daily Report", callback_data="daily_report"),
            InlineKeyboardButton("📆 Weekly Report", callback_data="weekly_report"),
        ],
        [
            InlineKeyboardButton("🗓 Monthly Report", callback_data="monthly_report"),
        ],
        [
            InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu"),
        ],
    ])

    if getattr(update, "callback_query", None) is not None:
        await update.callback_query.edit_message_text(
            "\n".join(lines),
            parse_mode="HTML",
            reply_markup=report_keyboard,
        )
    else:
        await update.message.reply_text(
            "\n".join(lines),
            parse_mode="HTML",
            reply_markup=report_keyboard,
        )


def _period_bounds(kind: str):
    """Return UTC-naive bounds for the requested Africa/Lagos period."""
    tz = ZoneInfo("Africa/Lagos")
    now = datetime.now(tz)

    if kind == "daily":
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        label = "Today"
    elif kind == "weekly":
        start = (
            now - timedelta(days=now.weekday())
        ).replace(hour=0, minute=0, second=0, microsecond=0)
        label = "This Week"
    elif kind == "monthly":
        start = now.replace(
            day=1,
            hour=0,
            minute=0,
            second=0,
            microsecond=0,
        )
        label = "This Month"
    else:
        raise ValueError(f"Unsupported report period: {kind}")

    end = now

    return (
        start.astimezone(timezone.utc).replace(tzinfo=None),
        end.astimezone(timezone.utc).replace(tzinfo=None),
        label,
    )


async def _period_report(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    kind: str,
):
    """Render a trade report for a Telegram command or callback."""
    user = update.effective_user
    if user is None:
        await _safe_reply(update, "Unable to identify the current user.")
        return

    try:
        storage = context.bot_data.get("storage") or DataStorage()
        start, end, label = _period_bounds(kind)

        report = storage.get_trade_report(
            start,
            end,
            user_id=user.id,
        )

        lines = [
            f"📊 <b>{label} Trading Report</b>",
            "",
            f"Trades: <b>{report['total']}</b>",
            f"Settled: <b>{report['settled']}</b>",
            (
                f"Wins: <b>{report['wins']}</b> | "
                f"Losses: <b>{report['losses']}</b> | "
                f"Draws: <b>{report['draws']}</b>"
            ),
            f"Win rate: <b>{report['win_rate']:.2f}%</b>",
            (
                f"Pending: <b>{report['pending']}</b> | "
                f"Unresolved: <b>{report['unresolved']}</b>"
            ),
            "",
            f"Stake: <b>{report['stake']:.2f}</b>",
            f"Payout: <b>{report['payout']:.2f}</b>",
            f"Net P/L: <b>{report['net_pl']:.2f}</b>",
            "",
            (
                f"CALL: {report['call']['wins']}/"
                f"{report['call']['total']} wins"
            ),
            (
                f"PUT: {report['put']['wins']}/"
                f"{report['put']['total']} wins"
            ),
        ]

        if report["by_asset"]:
            lines += ["", "<b>By asset</b>"]
            for asset, values in sorted(report["by_asset"].items()):
                lines.append(
                    f"• {asset}: "
                    f"{values['wins']}W/"
                    f"{values['losses']}L | "
                    f"P/L {values['net_pl']:.2f}"
                )

        if kind == "weekly":
            lines += [
                "",
                "<i>Week starts Monday 00:00, Africa/Lagos.</i>",
            ]

        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("📅 Daily", callback_data="daily_report"),
                InlineKeyboardButton("📆 Weekly", callback_data="weekly_report"),
                InlineKeyboardButton("🗓 Monthly", callback_data="monthly_report"),
            ],
            [
                InlineKeyboardButton("📊 Analytics", callback_data="analytics_inline"),
            ],
            [
                InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu"),
            ],
        ])

        if update.callback_query is not None:
            await update.callback_query.edit_message_text(
                "\n".join(lines),
                parse_mode="HTML",
                reply_markup=keyboard,
            )
        else:
            await update.message.reply_text(
                "\n".join(lines),
                parse_mode="HTML",
                reply_markup=keyboard,
            )

    except Exception:
        logger.exception(
            "Failed to generate %s trade report for user %s",
            kind,
            user.id,
        )

        await _safe_reply(
            update,
            "⚠️ Unable to generate this report right now. "
            "Please try again shortly.",
        )


async def daily_report_command(update, context):
    await _period_report(update, context, "daily")


async def weekly_report_command(update, context):
    await _period_report(update, context, "weekly")


async def monthly_report_command(update, context):
    await _period_report(update, context, "monthly")


async def daily_report_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await _period_report(update, context, "daily")


async def weekly_report_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await _period_report(update, context, "weekly")


async def monthly_report_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await _period_report(update, context, "monthly")



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

    await _safe_reply(
        update,
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

    # Per-asset cooldown (anti-spam)
    now = datetime.now(timezone.utc)
    last = _signal_cooldown.get(asset)
    if last and (now - last) < timedelta(minutes=COOLDOWN_MINUTES):
        remaining = max(1, COOLDOWN_MINUTES - int((now - last).total_seconds() // 60))
        await query.edit_message_text(
            f"⏳ <b>{asset}</b> is on cooldown.\n"
            f"Please wait ~{remaining} more minute(s) before requesting another signal.",
            parse_mode="HTML",
            reply_markup=keyboard_builder.build_signal_actions(asset),
        )
        return

    try:
        async def _do_analysis():
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
            return await signal_engine.generate_signal(asset)

        signal = await _run_with_spinner(query, f"Analyzing <b>{asset}</b>…", _do_analysis())

        # Record cooldown only for real CALL/PUT
        if signal.get("action") in ("CALL", "PUT"):
            _signal_cooldown[asset] = datetime.now(timezone.utc)

        storage = context.bot_data.get("storage") or DataStorage()
        user_id = query.from_user.id if query.from_user else 0
        if user_id:
            storage.save_signal(user_id, asset, signal)
            if signal.get("action") in ("CALL", "PUT"):
                _signal_freshness[(user_id, asset)] = datetime.now(timezone.utc)
        message = format_signal_message(signal)

        await query.edit_message_text(
            message,
            parse_mode="HTML",
            reply_markup=keyboard_builder.build_signal_actions(asset, signal.get("action")),
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


async def timeframe_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Re-run analysis for an asset on a different timeframe (tf_{tf}_{asset})."""
    query = update.callback_query
    await query.answer()

    try:
        _, tf, asset = (query.data or "").split("_", 2)
    except ValueError:
        await query.answer("❌ Invalid timeframe request.", show_alert=True)
        return

    try:
        signal_engine = context.bot_data.get("signal_engine")
        if signal_engine is None:
            await query.edit_message_text("⚠️ Signal engine unavailable. Try again shortly.")
            return

        signal = await _run_with_spinner(
            query, f"Analyzing <b>{asset}</b> ({tf})…",
            signal_engine.generate_signal(asset, timeframe=tf),
        )

        storage = context.bot_data.get("storage") or DataStorage()
        user_id = query.from_user.id if query.from_user else 0
        if user_id:
            storage.save_signal(user_id, asset, signal)
            if signal.get("action") in ("CALL", "PUT"):
                _signal_freshness[(user_id, asset)] = datetime.now(timezone.utc)

        message = format_signal_message(signal)
        await query.edit_message_text(
            message,
            parse_mode="HTML",
            reply_markup=keyboard_builder.build_signal_actions(asset, signal.get("action")),
        )
    except Exception:
        logger.exception("Timeframe switch failed for %s (%s)", asset, tf)
        await query.edit_message_text(
            f"⚠️ Could not analyze <b>{asset}</b> on {tf}.",
            parse_mode="HTML",
            reply_markup=keyboard_builder.build_signal_actions(asset),
        )


async def trade_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """User tapped 'Execute CALL/PUT' — show the expiry picker before
    actually placing anything (trade_{action}_{asset})."""
    query = update.callback_query
    await query.answer()

    try:
        _, direction, asset = (query.data or "").split("_", 2)
    except ValueError:
        await query.answer("❌ Invalid trade request.", show_alert=True)
        return

    api_client = context.bot_data.get("api_client")
    demo = bool(getattr(settings, "DEMO_MODE", True))
    user_id = query.from_user.id if query.from_user else 0

    if api_client is None:
        await query.edit_message_text(
            "⚠️ No broker connection is active right now.",
            parse_mode="HTML",
            reply_markup=keyboard_builder.build_signal_actions(asset, direction),
        )
        return

    # Staleness guard: don't let someone execute against a quote/analysis
    # that's minutes old by the time they finish tapping through menus.
    seen_at = _signal_freshness.get((user_id, asset))
    if seen_at:
        age = (datetime.now(timezone.utc) - seen_at).total_seconds()
        if age > SIGNAL_STALE_SECONDS:
            await query.edit_message_text(
                f"⏳ That analysis is {int(age)}s old — the market has likely "
                f"moved. Please refresh the signal before executing.",
                parse_mode="HTML",
                reply_markup=keyboard_builder.build_signal_actions(asset),
            )
            return

    mode_note = (
        "🧪 <b>DEMO account</b> — no real funds at risk."
        if demo
        else "🔴 <b>LIVE account — real money will be traded.</b>"
    )
    await query.edit_message_text(
        f"{mode_note}\n\nChoose a stake for the <b>{direction}</b> trade on "
        f"<b>{asset}</b>:",
        parse_mode="HTML",
        reply_markup=keyboard_builder.build_amount_selector(asset, direction),
    )


async def amount_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """User picked a stake — show the expiry picker (amt_{value}_{direction}_{asset})."""
    query = update.callback_query
    await query.answer()

    try:
        _, amount, direction, asset = (query.data or "").split("_", 3)
        amount = float(amount)
    except ValueError:
        await query.answer("❌ Invalid amount request.", show_alert=True)
        return

    min_amt = float(getattr(settings, "MIN_TRADE_AMOUNT", 1.0))
    max_amt = float(getattr(settings, "MAX_TRADE_AMOUNT", 1_000_000.0))
    if amount < min_amt or amount > max_amt:
        await query.edit_message_text(
            f"⚠️ ${amount:,.0f} is outside your configured range "
            f"(${min_amt:,.0f}–${max_amt:,.0f}). Adjust MIN/MAX_TRADE_AMOUNT "
            f"in .env if this should be allowed.",
            parse_mode="HTML",
            reply_markup=keyboard_builder.build_amount_selector(asset, direction),
        )
        return

    await query.edit_message_text(
        f"Stake: <b>${amount:,.0f}</b>\n\nChoose an expiry for the "
        f"<b>{direction}</b> trade on <b>{asset}</b>:",
        parse_mode="HTML",
        reply_markup=keyboard_builder.build_expiry_selector(asset, direction, amount),
    )


async def expiry_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """User picked an expiry — actually place the trade
    (expiry_{direction}_{secs}_{amount}_{asset})."""
    query = update.callback_query
    await query.answer()

    try:
        _, direction, secs, amount, asset = (query.data or "").split("_", 4)
        secs = int(secs)
        amount = float(amount)
    except ValueError:
        await query.answer("❌ Invalid expiry request.", show_alert=True)
        return

    api_client = context.bot_data.get("api_client")
    if api_client is None:
        await query.edit_message_text(
            "⚠️ No broker connection is active right now.",
            reply_markup=keyboard_builder.build_signal_actions(asset, direction),
        )
        return

    demo = bool(getattr(settings, "DEMO_MODE", True))

    await query.edit_message_text(
        f"⏳ Placing <b>{direction}</b> on <b>{asset}</b> "
        f"(${amount:.2f}, {secs}s expiry)…",
        parse_mode="HTML",
    )

    # Grab a fresh quote right before placing — this is the price we'll
    # compare against at expiry if the broker's own check_win() isn't
    # available, and it closes the "stale price" gap between analysis
    # and execution.
    entry_price = None
    data_fetcher = context.bot_data.get("data_fetcher")
    if data_fetcher is not None:
        try:
            candles = await data_fetcher.get_historical_data(asset, "1m", count=1)
            if candles is not None and not candles.empty:
                entry_price = float(candles["close"].iloc[-1])
        except Exception:
            logger.warning("Could not fetch fresh entry price for %s before trade", asset)

    try:
        result = await api_client.place_trade(asset, direction, amount, secs)
    except Exception as e:
        logger.exception("place_trade raised for %s %s", asset, direction)
        result = {"success": False, "error": str(e)}

    if not result.get("success"):
        await query.edit_message_text(
            f"❌ Trade failed for <b>{asset}</b>.\n<code>{str(result.get('error'))[:150]}</code>",
            parse_mode="HTML",
            reply_markup=keyboard_builder.build_signal_actions(asset, direction),
        )
        return

    mode_note = "🧪 DEMO" if demo else "🔴 LIVE"
    order_id = result.get("order_id") or result.get("trade_id")

    user_id = query.from_user.id if query.from_user else 0
    chat_id = query.message.chat_id if query.message else user_id
    storage = context.bot_data.get("storage") or DataStorage()
    if user_id:
        # Save the trade even if the broker does not return a parseable order ID.
        # The settlement worker requires an authoritative broker ID/result and
        # will preserve unresolved trades for reconciliation rather than guessing.
        storage.save_trade(
            user_id=user_id,
            chat_id=chat_id,
            asset=asset,
            direction=direction,
            amount=amount,
            duration_secs=secs,
            order_id=order_id,
            entry_price=entry_price,
        )

    await query.edit_message_text(
        f"✅ <b>{mode_note} trade placed</b>\n\n"
        f"{direction} <b>{asset}</b>  |  ${amount:.2f}  |  {secs}s expiry\n"
        f"Order ID: <code>{order_id or 'n/a'}</code>\n\n"
        "I'll message you here with WIN/LOSS as soon as it settles.",
        parse_mode="HTML",
        reply_markup=keyboard_builder.build_signal_actions(asset),
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



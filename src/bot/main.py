"""Main Telegram Bot Application"""
from __future__ import annotations

import asyncio
import signal
import sys
from typing import Optional

from telegram.ext import Application, CallbackQueryHandler, CommandHandler

from config.settings import get_settings
from ..api.factory import create_broker_client, resolve_backend
from ..api.data_fetcher import MarketDataFetcher
from ..api.botv2_adapter import botv2_available
from ..data.storage import DataStorage
from ..services.admin_service import AdminService
from ..services.broadcast_service import BroadcastService
from ..signals.engine import SignalEngine
from ..utils.logger import get_logger
from .handlers import (
    admin_broadcast_callback,
    admin_dashboard_command,
    admin_logs_callback,
    admin_menu_callback,
    admin_settings_callback,
    admin_users_callback,
    analytics_command,
    analytics_inline_callback,
    daily_report_command,
    weekly_report_command,
    monthly_report_command,
    daily_report_callback,
    weekly_report_callback,
    monthly_report_callback,
    broadcast_command,
    category_callback,
    help_command,
    help_inline_callback,
    pagination_callback,
    signal_callback,
    start_command,
    trade_callback,
    amount_callback,
    expiry_callback,
    timeframe_callback,
)

logger = get_logger(__name__)


class OTCTradingBot:
    """Professional Trading Bot with Async Architecture."""

    def __init__(self):
        self.settings = get_settings()
        self.application: Optional[Application] = None
        self.is_running = False
        self.api_client = None
        self.data_fetcher: Optional[MarketDataFetcher] = None
        self.signal_engine: Optional[SignalEngine] = None

        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

    async def initialize(self) -> Application:
        """Initialize bot with all components (demo-safe)."""
        try:
            demo = getattr(self.settings, "DEMO_MODE", True)
            backend = resolve_backend(self.settings)
            logger.info(
                "Broker backend=%s botv2_available=%s demo_mode=%s",
                backend,
                botv2_available(),
                demo,
            )

            # API client via factory (BotV2 or native)
            self.api_client = create_broker_client(self.settings)
            connected = await self.api_client.connect()
            if connected:
                logger.info("✅ API Client connected (%s)", type(self.api_client).__name__)
            else:
                logger.info("ℹ️  Running without live API connection (synthetic/demo data)")

            # Data fetcher – always available; synthetic fallback if not connected
            self.data_fetcher = MarketDataFetcher(
                client=self.api_client,
                demo_mode=demo or not connected,
            )

            # Signal engine
            self.signal_engine = SignalEngine(self.settings, self.data_fetcher)
            logger.info("✅ Signal engine ready (multi-indicator TA)")

            # Telegram application
            token = self.settings.TELEGRAM_BOT_TOKEN
            if not token or token.startswith("your_"):
                raise ValueError(
                    "TELEGRAM_BOT_TOKEN is missing or still a placeholder. "
                    "Set a real token in .env"
                )

            self.application = (
                Application.builder().token(token).build()
            )

            # Make core services available to handlers
            self.application.bot_data["api_client"] = self.api_client
            self.application.bot_data["data_fetcher"] = self.data_fetcher
            self.application.bot_data["signal_engine"] = self.signal_engine
            self.application.bot_data["settings"] = self.settings
            self.application.bot_data["storage"] = DataStorage()
            self.application.bot_data["admin_service"] = AdminService(self.settings)
            self.application.bot_data["broadcast_service"] = BroadcastService(self.settings)

            self._register_handlers()

            # Periodic job: resolve PENDING executed trades into WIN/LOSS
            # once their expiry has passed, and push the result to the
            # user on Telegram.
            if self.application.job_queue is not None:
                self.application.job_queue.run_repeating(
                    self._resolve_trades_job,
                    interval=15,
                    first=15,
                    name="resolve_pending_trades",
                )
            else:
                logger.warning(
                    "JobQueue unavailable (install 'python-telegram-bot[job-queue]') "
                    "- trade WIN/LOSS results will not auto-post to Telegram."
                )

            logger.info("✅ Bot initialized successfully")
            return self.application

        except Exception as e:
            logger.error("❌ Initialization failed: %s", e)
            raise

    async def _resolve_trades_job(self, context) -> None:
        """JobQueue callback: settle due trades and DM the outcome."""
        try:
            storage = self.application.bot_data.get("storage")
            api_client = self.application.bot_data.get("api_client")
            data_fetcher = self.application.bot_data.get("data_fetcher")
            if storage is None or api_client is None:
                return

            closed = await storage.resolve_pending_trades(api_client, data_fetcher)
            for trade in closed:
                chat_id = trade.get("chat_id")
                if not chat_id:
                    continue
                result = trade.get("result", "UNKNOWN")
                icon = {"WIN": "✅", "LOSS": "❌"}.get(result, "❔")
                text = (
                    f"{icon} <b>{result}</b>  —  {trade.get('direction')} "
                    f"<b>{trade.get('asset')}</b>  (${trade.get('amount', 0):.2f})"
                )
                try:
                    await self.application.bot.send_message(
                        chat_id=int(chat_id), text=text, parse_mode="HTML"
                    )
                except Exception:
                    logger.exception("Failed to notify chat %s of trade result", chat_id)
        except Exception:
            logger.exception("resolve_pending_trades job failed")

    def _register_handlers(self) -> None:
        assert self.application is not None
        self.application.add_handler(CommandHandler("start", start_command))
        self.application.add_handler(CommandHandler("help", help_command))
        self.application.add_handler(CommandHandler("analytics", analytics_command))
        self.application.add_handler(CommandHandler("daily", daily_report_command))
        self.application.add_handler(CommandHandler("weekly", weekly_report_command))
        self.application.add_handler(CommandHandler("monthly", monthly_report_command))
        self.application.add_handler(CommandHandler("admin", admin_dashboard_command))
        self.application.add_handler(CommandHandler("broadcast", broadcast_command))
        self.application.add_handler(
            CallbackQueryHandler(signal_callback, pattern=r"^signal_")
        )
        self.application.add_handler(
            CallbackQueryHandler(trade_callback, pattern=r"^trade_")
        )
        self.application.add_handler(
            CallbackQueryHandler(amount_callback, pattern=r"^amt_")
        )
        self.application.add_handler(
            CallbackQueryHandler(expiry_callback, pattern=r"^expiry_")
        )
        self.application.add_handler(
            CallbackQueryHandler(timeframe_callback, pattern=r"^tf_")
        )
        # Admin menu and sub-actions
        self.application.add_handler(
            CallbackQueryHandler(admin_menu_callback, pattern=r"^admin_menu$")
        )
        self.application.add_handler(
            CallbackQueryHandler(admin_users_callback, pattern=r"^admin_users$")
        )
        self.application.add_handler(
            CallbackQueryHandler(admin_broadcast_callback, pattern=r"^admin_broadcast$")
        )
        self.application.add_handler(
            CallbackQueryHandler(admin_settings_callback, pattern=r"^admin_settings$")
        )
        self.application.add_handler(
            CallbackQueryHandler(admin_logs_callback, pattern=r"^admin_logs$")
        )
        # Analytics and help
        self.application.add_handler(
            CallbackQueryHandler(analytics_inline_callback, pattern=r"^analytics_inline$")
        )
        self.application.add_handler(
            CallbackQueryHandler(daily_report_callback, pattern=r"^daily_report$")
        )
        self.application.add_handler(
            CallbackQueryHandler(weekly_report_callback, pattern=r"^weekly_report$")
        )
        self.application.add_handler(
            CallbackQueryHandler(monthly_report_callback, pattern=r"^monthly_report$")
        )
        self.application.add_handler(
            CallbackQueryHandler(help_inline_callback, pattern=r"^help_inline$")
        )
        # Category and pagination
        self.application.add_handler(
            CallbackQueryHandler(category_callback, pattern=r"^category_")
        )
        self.application.add_handler(
            CallbackQueryHandler(pagination_callback, pattern=r"^page_")
        )
        # Main menu / back buttons
        self.application.add_handler(
            CallbackQueryHandler(self._main_menu_callback, pattern=r"^main_menu$")
        )
        self.application.add_error_handler(self._error_handler)

    async def _main_menu_callback(self, update, context):
        """Handle return to main menu."""
        query = update.callback_query
        await query.answer()
        from .keyboards import AssetKeyboardBuilder

        kb = AssetKeyboardBuilder(self.settings)
        await query.edit_message_text(
            "🎯 <b>OTC Signal Bot</b>\n\nSelect an option below:",
            parse_mode="HTML",
            reply_markup=kb.build_main_menu(),
        )

    async def _error_handler(self, update, context):
        logger.error("Bot error: %s", context.error)
        try:
            if update and update.callback_query:
                await update.callback_query.answer(
                    "⚠️ An error occurred. Please try again.",
                    show_alert=True,
                )
        except Exception as e:
            logger.error("Error handler failed: %s", e)

    def _signal_handler(self, signum, frame):
        logger.info("Received signal %s, shutting down...", signum)
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(self.shutdown())
        except Exception:
            self.is_running = False

    async def run(self) -> None:
        """Start the bot."""
        try:
            if self.application is None:
                await self.initialize()

            await self.application.initialize()
            await self.application.start()
            await self.application.updater.start_polling(drop_pending_updates=True)

            self.is_running = True
            mode = "DEMO" if getattr(self.settings, "DEMO_MODE", True) else "LIVE"
            logger.info("🚀 Bot is running in %s mode! Press Ctrl+C to stop.", mode)

            while self.is_running:
                await asyncio.sleep(1)

        except KeyboardInterrupt:
            logger.info("Keyboard interrupt received")
        except Exception as e:
            logger.error("Bot run failed: %s", e)
        finally:
            await self.shutdown()

    async def shutdown(self) -> None:
        if not self.is_running and self.application is None:
            return

        self.is_running = False
        logger.info("🔄 Shutting down gracefully...")

        try:
            if self.application:
                if self.application.updater and self.application.updater.running:
                    await self.application.updater.stop()
                await self.application.stop()
                await self.application.shutdown()

            if self.api_client:
                await self.api_client.close()

            logger.info("✅ Bot shutdown complete")
        except Exception as e:
            logger.error("Error during shutdown: %s", e)

        sys.exit(0)


def main() -> None:
    bot = OTCTradingBot()
    asyncio.run(bot.run())


if __name__ == "__main__":
    main()

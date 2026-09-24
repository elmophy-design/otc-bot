from pathlib import Path
import py_compile

ROOT = Path('.')
HANDLERS = ROOT / 'src' / 'bot' / 'handlers.py'
MAIN = ROOT / 'src' / 'bot' / 'main.py'
ADAPTER = ROOT / 'src' / 'api' / 'botv2_adapter.py'
STORAGE = ROOT / 'src' / 'data' / 'storage.py'

for path in (HANDLERS, MAIN, ADAPTER, STORAGE):
    if not path.exists():
        raise FileNotFoundError(f'Missing {path}. Run from the OTC bot project root.')

def backup(path):
    b = path.with_suffix(path.suffix + '.backup-before-runtime-fix-v3')
    if not b.exists():
        b.write_text(path.read_text(encoding='utf-8-sig'), encoding='utf-8')

for path in (HANDLERS, MAIN, ADAPTER, STORAGE):
    backup(path)

# 1. Analytics: respect PREMIUM_ONLY and make callback visibly fail/log if needed.
s = HANDLERS.read_text(encoding='utf-8-sig')

old = '''    # Premium gating: admins always have access; others need premium
    if not admin_service.is_admin(user.id) and not admin_service.is_premium(user.id):
        await update.message.reply_text(
            "🔒 <b>Premium Feature</b>\\n\\nAnalytics are available to premium members only.\\n"
            "Please contact an admin to upgrade your account.",
            parse_mode="HTML",
        )
        return
'''
new = '''    # Respect PREMIUM_ONLY. When false, analytics are available to all users.
    premium_only = bool(getattr(settings, "PREMIUM_ONLY", False))
    if (
        premium_only
        and not admin_service.is_admin(user.id)
        and not admin_service.is_premium(user.id)
    ):
        await _safe_reply(
            update,
            "🔒 <b>Premium Feature</b>\\n\\n"
            "Analytics are available to premium members only.\\n"
            "Please contact an admin to upgrade your account.",
            parse_mode="HTML",
        )
        return

    logger.info(
        "Analytics requested: user=%s callback=%s premium_only=%s",
        user.id,
        bool(getattr(update, "callback_query", None)),
        premium_only,
    )
'''
if old in s:
    s = s.replace(old, new, 1)

old = '''async def analytics_inline_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    # Callback wrapper for the My Analytics button.
    query = update.callback_query
    if query is not None:
        await query.answer()
    await analytics_command(update, context)
'''
new = '''async def analytics_inline_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    """Handle My Analytics safely from an inline callback."""
    query = update.callback_query
    if query is None:
        await analytics_command(update, context)
        return

    try:
        await query.answer()
        logger.info(
            "My Analytics callback received: user=%s data=%s",
            query.from_user.id if query.from_user else None,
            query.data,
        )
        await analytics_command(update, context)
    except Exception:
        logger.exception(
            "My Analytics callback failed: user=%s",
            query.from_user.id if query.from_user else None,
        )
        try:
            await query.edit_message_text(
                "⚠️ <b>Analytics could not be loaded.</b>\\n\\n"
                "The bot logged the error. Please try again.",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]]
                ),
            )
        except Exception:
            logger.exception("Could not display analytics error message")
'''
if old in s:
    s = s.replace(old, new, 1)

HANDLERS.write_text(s, encoding='utf-8')

# 2. Robust broker trade ID extraction.
s = ADAPTER.read_text(encoding='utf-8-sig')
old = '''        trade_id = None
        deal = res
        if isinstance(res, (tuple, list)) and len(res) >= 1:
            trade_id = res[0]
            deal = res[1] if len(res) > 1 else res[0]
        elif isinstance(res, dict):
            trade_id = res.get("id") or res.get("trade_id") or res.get("order_id")
'''
new = '''        trade_id = None
        deal = res

        # BinaryOptionsToolsV2 normally returns (trade_id, trade_data).
        if isinstance(res, (tuple, list)) and len(res) >= 1:
            trade_id = res[0]
            deal = res[1] if len(res) > 1 else res[0]
        elif isinstance(res, dict):
            trade_id = (
                res.get("id")
                or res.get("trade_id")
                or res.get("order_id")
                or res.get("deal_id")
                or res.get("request_id")
            )
        else:
            for attr in ("id", "trade_id", "order_id", "deal_id", "request_id"):
                value = getattr(res, attr, None)
                if value is not None:
                    trade_id = value
                    break

        # Some wrappers put the ID on the returned deal object.
        if trade_id is None and deal is not None:
            if isinstance(deal, dict):
                trade_id = (
                    deal.get("id")
                    or deal.get("trade_id")
                    or deal.get("order_id")
                    or deal.get("deal_id")
                    or deal.get("request_id")
                )
            else:
                for attr in ("id", "trade_id", "order_id", "deal_id", "request_id"):
                    value = getattr(deal, attr, None)
                    if value is not None:
                        trade_id = value
                        break

        if trade_id is not None:
            trade_id = str(trade_id)
'''
if old in s:
    s = s.replace(old, new, 1)
ADAPTER.write_text(s, encoding='utf-8')

# 3. Native asyncio settlement loop, independent of PTB JobQueue.
s = MAIN.read_text(encoding='utf-8-sig')
old = '''        self.signal_engine: Optional[SignalEngine] = None

        signal.signal(signal.SIGINT, self._signal_handler)
'''
new = '''        self.signal_engine: Optional[SignalEngine] = None
        self._settlement_task: Optional[asyncio.Task] = None

        signal.signal(signal.SIGINT, self._signal_handler)
'''
if old in s:
    s = s.replace(old, new, 1)

start_marker = '            # Periodic job: resolve PENDING executed trades into WIN/LOSS'
end_marker = '            logger.info("✅ Bot initialized successfully")'
start = s.find(start_marker)
end = s.find(end_marker, start)
if start == -1 or end == -1:
    raise RuntimeError('Could not locate settlement startup block in main.py.')

replacement = '''            # Always run a native asyncio settlement worker. This does not
            # depend on python-telegram-bot JobQueue being available.
            if self._settlement_task is None or self._settlement_task.done():
                self._settlement_task = asyncio.create_task(
                    self._settlement_loop(),
                    name="otc_settlement_loop",
                )
                logger.info("✅ Native settlement loop started (15s interval)")

            if self.application.job_queue is not None:
                self.application.job_queue.run_repeating(
                    self._resolve_trades_job,
                    interval=15,
                    first=15,
                    name="resolve_pending_trades",
                )
                logger.info("✅ PTB JobQueue settlement worker also enabled")
            else:
                logger.warning(
                    "PTB JobQueue unavailable; native asyncio settlement loop "
                    "will handle trade settlement."
                )

'''
s = s[:start] + replacement + s[end:]

marker = '    async def _resolve_trades_job(self, context) -> None:\n'
if '    async def _settlement_loop(self) -> None:\n' not in s:
    loop_code = '''    async def _settlement_loop(self) -> None:
        """Independent settlement worker; does not depend on PTB JobQueue."""
        while True:
            try:
                await asyncio.sleep(15)
                if not self.application:
                    continue

                storage = self.application.bot_data.get("storage")
                api_client = self.application.bot_data.get("api_client")
                data_fetcher = self.application.bot_data.get("data_fetcher")

                if storage is None or api_client is None:
                    logger.warning(
                        "Settlement loop skipped: storage=%s api_client=%s",
                        storage is not None,
                        api_client is not None,
                    )
                    continue

                closed = await storage.resolve_pending_trades(
                    api_client,
                    data_fetcher,
                )

                if closed:
                    logger.info("Settlement loop closed %d trade(s)", len(closed))

                for trade in closed:
                    chat_id = trade.get("chat_id")
                    if not chat_id:
                        logger.warning(
                            "Settled trade %s has no chat_id; cannot notify.",
                            trade.get("id"),
                        )
                        continue

                    result = str(trade.get("result") or "UNKNOWN").upper()
                    icon = {"WIN": "✅", "LOSS": "❌", "DRAW": "↔️"}.get(
                        result, "❔"
                    )
                    profit = trade.get("profit_loss")
                    message = (
                        f"{icon} <b>{result}</b>\\n\\n"
                        f"{trade.get('direction')} <b>{trade.get('asset')}</b> "
                        f"(${float(trade.get('amount') or 0):.2f})"
                    )
                    if profit is not None:
                        message += f"\\nP/L: <b>${float(profit):+.2f}</b>"

                    try:
                        await self.application.bot.send_message(
                            chat_id=int(chat_id),
                            text=message,
                            parse_mode="HTML",
                        )
                        logger.info(
                            "Settlement notification sent: trade=%s chat=%s result=%s",
                            trade.get("id"),
                            chat_id,
                            result,
                        )
                    except Exception:
                        logger.exception(
                            "Settlement notification failed: trade=%s chat=%s",
                            trade.get("id"),
                            chat_id,
                        )

            except asyncio.CancelledError:
                logger.info("Native settlement loop cancelled")
                raise
            except Exception:
                logger.exception("Native settlement loop failed; retrying")

'''
    if marker not in s:
        raise RuntimeError('Could not locate _resolve_trades_job in main.py.')
    s = s.replace(marker, loop_code + marker, 1)

old = '''        try:
            if self.application:
                if self.application.updater and self.application.updater.running:
'''
new = '''        try:
            if self._settlement_task is not None:
                self._settlement_task.cancel()
                try:
                    await self._settlement_task
                except asyncio.CancelledError:
                    pass
                self._settlement_task = None

            if self.application:
                if self.application.updater and self.application.updater.running:
'''
if old in s:
    s = s.replace(old, new, 1)
MAIN.write_text(s, encoding='utf-8')

# 4. Explicit settlement diagnostics.
s = STORAGE.read_text(encoding='utf-8-sig')
old = '''                    if not row.order_id:
                        row.result = "REQUIRES_RECONCILIATION"
                        row.broker_result = "MISSING_ORDER_ID"
                        row.settlement_source = "missing_order_id"
                        continue
'''
new = '''                    if not row.order_id:
                        row.result = "REQUIRES_RECONCILIATION"
                        row.broker_result = "MISSING_ORDER_ID"
                        row.settlement_source = "missing_order_id"
                        logger.error(
                            "Trade %s cannot settle: missing broker order_id",
                            row.id,
                        )
                        continue
'''
if old in s:
    s = s.replace(old, new, 1)

old = '''                    res = await api_client.check_win(
                        row.order_id,
                        timeout=20,
                    )
'''
new = '''                    logger.info(
                        "Checking broker settlement: trade=%s order=%s attempt=%s",
                        row.id,
                        row.order_id,
                        row.settlement_attempts,
                    )
                    res = await api_client.check_win(
                        row.order_id,
                        timeout=20,
                    )
                    logger.info(
                        "Broker settlement response: trade=%s order=%s response=%r",
                        row.id,
                        row.order_id,
                        res,
                    )
'''
if old in s:
    s = s.replace(old, new, 1)
STORAGE.write_text(s, encoding='utf-8')

for path in (HANDLERS, MAIN, ADAPTER, STORAGE):
    py_compile.compile(str(path), doraise=True)

print('SUCCESS - OTC bot runtime fix v3 created.')
print('Backups: *.backup-before-runtime-fix-v3')
print('Syntax checks passed.')

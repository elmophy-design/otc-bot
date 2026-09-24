
from pathlib import Path
import py_compile

ROOT = Path(".")
FILES = {
    "adapter": ROOT / "src" / "api" / "botv2_adapter.py",
    "handlers": ROOT / "src" / "bot" / "handlers.py",
    "main": ROOT / "src" / "bot" / "main.py",
}

for path in FILES.values():
    if not path.exists():
        raise FileNotFoundError(
            f"Missing {path}. Run this script from the OTC bot project root."
        )

# 1. Fix BotV2 settlement normalization.
p = FILES["adapter"]
s = p.read_text(encoding="utf-8")

old = """    async def check_win(self, trade_id: str, timeout: Optional[int] = None) -> dict:
        if not self.is_connected or self._client is None:
            raise RuntimeError("BotV2Client is not connected")
        client = self._client
        if not hasattr(client, "check_win"):
            raise AttributeError("Underlying client has no check_win")
        res = client.check_win(trade_id)
        if asyncio.iscoroutine(res):
            res = await asyncio.wait_for(res, timeout=(timeout or 120))
        if isinstance(res, dict):
            return res
        return {"result": res}
"""

new = """    async def check_win(self, trade_id: str, timeout: Optional[int] = None) -> dict:
        \"\"\"Check and normalize the broker settlement for a trade.\"\"\"
        if not self.is_connected or self._client is None:
            raise RuntimeError("BotV2Client is not connected")

        client = self._client
        if not hasattr(client, "check_win"):
            raise AttributeError("Underlying client has no check_win")

        res = client.check_win(trade_id)
        if asyncio.iscoroutine(res):
            res = await asyncio.wait_for(
                res,
                timeout=(timeout or 120),
            )

        normalized = self._normalize_settlement(res)

        logger.info(
            "Trade settlement: trade_id=%s result=%s profit=%s raw_result=%s",
            trade_id,
            normalized.get("result"),
            normalized.get("profit"),
            normalized.get("raw_result"),
        )

        return normalized
"""

if old not in s:
    raise RuntimeError("check_win() block was not found.")
s = s.replace(old, new, 1)

old = """        payload = (
            res
            if isinstance(res, dict)
            else {"result": res}
        )
"""

new = """        if isinstance(res, dict):
            payload = res
        elif isinstance(res, bool):
            payload = {"win": res}
        elif isinstance(res, (int, float)):
            # Some broker versions return settlement profit directly.
            payload = {"profit": float(res)}
        else:
            payload = {"result": res}
"""

if old not in s:
    raise RuntimeError("Settlement payload block was not found.")
s = s.replace(old, new, 1)
p.write_text(s, encoding="utf-8")

# 2. Fix analytics/report callbacks.
p = FILES["handlers"]
s = p.read_text(encoding="utf-8")

old = """    if getattr(update, "callback_query", None) is not None:
        await update.callback_query.edit_message_text("\\n".join(lines), parse_mode="HTML")
    else:
        await update.message.reply_text("\\n".join(lines), parse_mode="HTML")
"""

new = """    report_keyboard = InlineKeyboardMarkup([
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
            "\\n".join(lines),
            parse_mode="HTML",
            reply_markup=report_keyboard,
        )
    else:
        await update.message.reply_text(
            "\\n".join(lines),
            parse_mode="HTML",
            reply_markup=report_keyboard,
        )
"""

if old not in s:
    raise RuntimeError("Analytics response block was not found.")
s = s.replace(old, new, 1)

start_marker = "def _period_bounds(kind: str):"
end_marker = "\n\n\nasync def admin_dashboard_command"
start = s.find(start_marker)
end = s.find(end_marker, start)

if start == -1 or end == -1:
    raise RuntimeError("Report section could not be located.")

replacement = """def _period_bounds(kind: str):
    \"\"\"Return UTC-naive bounds for the requested Africa/Lagos period.\"\"\"
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
    \"\"\"Render a trade report for a Telegram command or callback.\"\"\"
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
                "\\n".join(lines),
                parse_mode="HTML",
                reply_markup=keyboard,
            )
        else:
            await update.message.reply_text(
                "\\n".join(lines),
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
"""

s = s[:start] + replacement + s[end:]
p.write_text(s, encoding="utf-8")

# 3. Register callbacks in main.py.
p = FILES["main"]
s = p.read_text(encoding="utf-8")

old = """    analytics_inline_callback,
    daily_report_command,
    weekly_report_command,
    monthly_report_command,
    broadcast_command,
"""

new = """    analytics_inline_callback,
    daily_report_command,
    weekly_report_command,
    monthly_report_command,
    daily_report_callback,
    weekly_report_callback,
    monthly_report_callback,
    broadcast_command,
"""

if old not in s:
    raise RuntimeError("Report imports were not found in main.py.")
s = s.replace(old, new, 1)

old = """        self.application.add_handler(
            CallbackQueryHandler(analytics_inline_callback, pattern=r"^analytics_inline$")
        )
        self.application.add_handler(
            CallbackQueryHandler(help_inline_callback, pattern=r"^help_inline$")
        )
"""

new = """        self.application.add_handler(
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
"""

if old not in s:
    raise RuntimeError("Analytics callback registration block was not found.")
s = s.replace(old, new, 1)
p.write_text(s, encoding="utf-8")

# 4. Syntax check the modified files.
for p in FILES.values():
    py_compile.compile(str(p), doraise=True)

print("OTC bot fix applied successfully.")
print("Backups created with: *.backup-before-report-settlement-fix")
print("Syntax checks passed.")

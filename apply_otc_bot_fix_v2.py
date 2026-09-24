from pathlib import Path
import py_compile

ROOT = Path(".")
HANDLERS = ROOT / "src" / "bot" / "handlers.py"
MAIN = ROOT / "src" / "bot" / "main.py"
ADAPTER = ROOT / "src" / "api" / "botv2_adapter.py"

for path in (HANDLERS, MAIN, ADAPTER):
    if not path.exists():
        raise FileNotFoundError(
            f"Missing {path}. Run this script from the OTC bot project root."
        )

def backup(path):
    b = path.with_suffix(path.suffix + ".backup-before-analytics-fix-v2")
    if not b.exists():
        b.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")

for path in (HANDLERS, MAIN, ADAPTER):
    backup(path)

# 1. Restore analytics_inline_callback.
s = HANDLERS.read_text(encoding="utf-8")

if "async def analytics_inline_callback(" not in s:
    marker = '\ndef _period_bounds(kind: str):'
    callback = '''
async def analytics_inline_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    # Callback wrapper for the My Analytics button.
    query = update.callback_query
    if query is not None:
        await query.answer()
    await analytics_command(update, context)

'''
    if marker not in s:
        raise RuntimeError("Could not find _period_bounds() in handlers.py.")
    s = s.replace(marker, callback + marker, 1)

# 2. Ensure report callbacks exist.
if "async def daily_report_callback(" not in s:
    marker = '\n\nasync def admin_dashboard_command'
    callback_block = '''
async def daily_report_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    query = update.callback_query
    if query is not None:
        await query.answer()
    await _period_report(update, context, "daily")


async def weekly_report_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    query = update.callback_query
    if query is not None:
        await query.answer()
    await _period_report(update, context, "weekly")


async def monthly_report_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    query = update.callback_query
    if query is not None:
        await query.answer()
    await _period_report(update, context, "monthly")
'''
    if marker not in s:
        raise RuntimeError("Could not find admin_dashboard_command in handlers.py.")
    s = s.replace(marker, callback_block + marker, 1)

HANDLERS.write_text(s, encoding="utf-8")

# 3. Ensure main.py imports the callbacks.
s = MAIN.read_text(encoding="utf-8")

if "    daily_report_callback," not in s:
    marker = "    analytics_inline_callback,\n"
    if marker not in s:
        raise RuntimeError("Could not find analytics_inline_callback import in main.py.")
    s = s.replace(
        marker,
        marker
        + "    daily_report_callback,\n"
        + "    weekly_report_callback,\n"
        + "    monthly_report_callback,\n",
        1,
    )

# 4. Ensure main.py registers the callbacks.
if 'pattern=r"^daily_report$"' not in s:
    marker = '''        self.application.add_handler(
            CallbackQueryHandler(analytics_inline_callback, pattern=r"^analytics_inline$")
        )
'''
    registrations = '''        self.application.add_handler(
            CallbackQueryHandler(daily_report_callback, pattern=r"^daily_report$")
        )
        self.application.add_handler(
            CallbackQueryHandler(weekly_report_callback, pattern=r"^weekly_report$")
        )
        self.application.add_handler(
            CallbackQueryHandler(monthly_report_callback, pattern=r"^monthly_report$")
        )
'''
    if marker not in s:
        raise RuntimeError("Could not find analytics callback registration in main.py.")
    s = s.replace(marker, marker + registrations, 1)

MAIN.write_text(s, encoding="utf-8")

# 5. Ensure check_win() normalizes broker settlement responses.
s = ADAPTER.read_text(encoding="utf-8")

if "normalized = self._normalize_settlement(res)" not in s:
    old = '''        if asyncio.iscoroutine(res):
            res = await asyncio.wait_for(res, timeout=(timeout or 120))
        if isinstance(res, dict):
            return res
        return {"result": res}
'''
    new = '''        if asyncio.iscoroutine(res):
            res = await asyncio.wait_for(res, timeout=(timeout or 120))

        normalized = self._normalize_settlement(res)

        logger.info(
            "Trade settlement: trade_id=%s result=%s profit=%s raw_result=%s",
            trade_id,
            normalized.get("result"),
            normalized.get("profit"),
            normalized.get("raw_result"),
        )

        return normalized
'''
    if old not in s:
        raise RuntimeError("check_win() has an unexpected structure.")
    s = s.replace(old, new, 1)

if 'payload = {"profit": float(res)}' not in s:
    old = '''        payload = (
            res
            if isinstance(res, dict)
            else {"result": res}
        )
'''
    new = '''        if isinstance(res, dict):
            payload = res
        elif isinstance(res, bool):
            payload = {"win": res}
        elif isinstance(res, (int, float)):
            payload = {"profit": float(res)}
        else:
            payload = {"result": res}
'''
    if old in s:
        s = s.replace(old, new, 1)

ADAPTER.write_text(s, encoding="utf-8")

# 6. Syntax-check everything.
for path in (HANDLERS, MAIN, ADAPTER):
    py_compile.compile(str(path), doraise=True)

print("SUCCESS - OTC bot fix v2 applied.")
print("Backups created with suffix: .backup-before-analytics-fix-v2")
print("Syntax checks passed.")

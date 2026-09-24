from pathlib import Path

path = Path("src/bot/handlers.py")
text = path.read_text(encoding="utf-8")

# ------------------------------------------------------------
# Add timezone imports
# ------------------------------------------------------------

if "from zoneinfo import ZoneInfo" not in text:
    marker = "from datetime import"
    pos = text.find(marker)

    if pos != -1:
        line_end = text.find("\n", pos)
        text = (
            text[:line_end + 1]
            + "from zoneinfo import ZoneInfo\n"
            + text[line_end + 1:]
        )
    else:
        text = "from zoneinfo import ZoneInfo\n" + text


# ------------------------------------------------------------
# Insert reporting helpers before first handler
# ------------------------------------------------------------

if "REPORT_TIMEZONE = ZoneInfo(" not in text:

    candidates = [
        "async def analytics",
        "async def daily",
        "def analytics",
        "def daily",
    ]

    insertion = -1

    for marker in candidates:
        insertion = text.find(marker)
        if insertion != -1:
            break

    if insertion == -1:
        raise SystemExit(
            "ERROR: Could not find reporting handler in handlers.py"
        )

    helpers = r'''
# ============================================================
# AUTHORITATIVE REPORTING PERIOD HELPERS
# ============================================================

REPORT_TIMEZONE = ZoneInfo("Africa/Lagos")


def _report_period(period: str):
    """Return local Africa/Lagos period boundaries as UTC-naive datetimes."""

    from datetime import datetime, timedelta, timezone

    now_local = datetime.now(REPORT_TIMEZONE)

    period = period.lower()

    if period == "daily":
        start_local = now_local.replace(
            hour=0,
            minute=0,
            second=0,
            microsecond=0,
        )

    elif period == "weekly":
        start_local = (
            now_local.replace(
                hour=0,
                minute=0,
                second=0,
                microsecond=0,
            )
            - timedelta(days=now_local.weekday())
        )

    elif period == "monthly":
        start_local = now_local.replace(
            day=1,
            hour=0,
            minute=0,
            second=0,
            microsecond=0,
        )

    elif period == "alltime":
        # Use the earliest representable application date.
        start_local = datetime(
            2000,
            1,
            1,
            tzinfo=REPORT_TIMEZONE,
        )

    else:
        raise ValueError(
            f"Unsupported report period: {period}"
        )

    if period == "daily":
        end_local = start_local + timedelta(days=1)

    elif period == "weekly":
        end_local = start_local + timedelta(days=7)

    elif period == "monthly":
        if start_local.month == 12:
            end_local = start_local.replace(
                year=start_local.year + 1,
                month=1,
                day=1,
            )
        else:
            end_local = start_local.replace(
                month=start_local.month + 1,
                day=1,
            )

    else:
        # All-time is open-ended.
        end_local = now_local + timedelta(seconds=1)

    start_utc = (
        start_local
        .astimezone(timezone.utc)
        .replace(tzinfo=None)
    )

    end_utc = (
        end_local
        .astimezone(timezone.utc)
        .replace(tzinfo=None)
    )

    return start_utc, end_utc


def _format_money(value):
    value = float(value or 0)
    return f"{value:,.2f}"


def _format_report(report, title):
    """Format authoritative report data for Telegram."""

    total = report["total"]
    settled = report["settled"]
    wins = report["wins"]
    losses = report["losses"]
    draws = report["draws"]
    pending = report["pending"]
    unresolved = report["unresolved"]

    win_rate = report["win_rate"]
    stake = report["stake"]
    settled_stake = report["settled_stake"]
    payout = report["payout"]
    net_pl = report["net_pl"]

    if net_pl > 0:
        pl_icon = "📈"
    elif net_pl < 0:
        pl_icon = "📉"
    else:
        pl_icon = "➖"

    lines = [
        f"📊 <b>{title}</b>",
        "",
        f"Trades: <b>{total}</b>",
        f"Settled: <b>{settled}</b>",
        f"Pending: <b>{pending}</b>",
        f"Unresolved: <b>{unresolved}</b>",
        "",
        f"✅ Wins: <b>{wins}</b>",
        f"❌ Losses: <b>{losses}</b>",
        f"➖ Draws: <b>{draws}</b>",
        f"🎯 Win rate: <b>{win_rate:.2f}%</b>",
        "",
        f"💰 Total stake: <b>{_format_money(stake)}</b>",
        f"💵 Settled stake: <b>{_format_money(settled_stake)}</b>",
        f"💳 Payout: <b>{_format_money(payout)}</b>",
        f"{pl_icon} Net P/L: <b>{_format_money(net_pl)}</b>",
        "",
        "📞 <b>CALL</b>",
        (
            f"  Trades: {report['call']['total']} | "
            f"W: {report['call']['wins']} | "
            f"L: {report['call']['losses']} | "
            f"D: {report['call']['draws']} | "
            f"WR: {report['call']['win_rate']:.2f}%"
        ),
        "",
        "📤 <b>PUT</b>",
        (
            f"  Trades: {report['put']['total']} | "
            f"W: {report['put']['wins']} | "
            f"L: {report['put']['losses']} | "
            f"D: {report['put']['draws']} | "
            f"WR: {report['put']['win_rate']:.2f}%"
        ),
    ]

    if report["by_asset"]:
        lines.extend([
            "",
            "📈 <b>BY ASSET</b>",
        ])

        for asset, stats in sorted(
            report["by_asset"].items()
        ):
            lines.append(
                f"• <b>{asset}</b>: "
                f"{stats['total']} trades | "
                f"W {stats['wins']} | "
                f"L {stats['losses']} | "
                f"D {stats['draws']} | "
                f"WR {stats['win_rate']:.2f}% | "
                f"P/L {_format_money(stats['net_pl'])}"
            )

    if unresolved:
        lines.extend([
            "",
            "⚠️ <b>UNRESOLVED TRADES</b>",
            (
                "These trades are excluded from the win-rate "
                "calculation and have NOT been classified as wins "
                "or losses."
            ),
        ])

    return "\n".join(lines)


async def _send_period_report(update, context, period, title):
    """Send one authoritative report."""

    storage = context.bot_data["storage"]

    start_at, end_at = _report_period(period)

    user = update.effective_user

    report = storage.get_trade_report(
        start_at=start_at,
        end_at=end_at,
        user_id=user.id if user else None,
    )

    message = _format_report(report, title)

    await update.effective_message.reply_text(
        message,
        parse_mode="HTML",
    )

'''

    text = text[:insertion] + helpers + text[insertion:]


# ------------------------------------------------------------
# Add handlers if not already present
# ------------------------------------------------------------

if "async def alltime_report" not in text:

    marker = "\n\n# ============================================================"
    insertion = text.find(marker)

    if insertion == -1:
        insertion = len(text)

    handlers = r'''

async def daily_report(update, context):
    await _send_period_report(
        update,
        context,
        "daily",
        "TODAY'S TRADING REPORT",
    )


async def weekly_report(update, context):
    await _send_period_report(
        update,
        context,
        "weekly",
        "THIS WEEK'S TRADING REPORT",
    )


async def monthly_report(update, context):
    await _send_period_report(
        update,
        context,
        "monthly",
        "THIS MONTH'S TRADING REPORT",
    )


async def alltime_report(update, context):
    await _send_period_report(
        update,
        context,
        "alltime",
        "ALL-TIME TRADING REPORT",
    )

'''

    text = text[:insertion] + handlers + text[insertion:]


path.write_text(text, encoding="utf-8")

print("SUCCESS: Phase 3C reporting helpers added.")
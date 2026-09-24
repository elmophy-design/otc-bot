from pathlib import Path
import py_compile
import shutil
import re

ROOT = Path(".")
ADAPTER = ROOT / "src" / "api" / "botv2_adapter.py"
STORAGE = ROOT / "src" / "data" / "storage.py"

for path in (ADAPTER, STORAGE):
    if not path.exists():
        raise FileNotFoundError(f"Missing {path}. Run this script from the OTC bot project root.")

def backup(path):
    b = path.with_suffix(path.suffix + ".backup-before-settlement-timeout-fix-v2")
    if not b.exists():
        shutil.copy2(path, b)
        print(f"Backup created: {b}")

for path in (ADAPTER, STORAGE):
    backup(path)

# Adapter: remove the outer timeout if it is still present.
s = ADAPTER.read_text(encoding="utf-8-sig")
old = (
    "        res = client.check_win(trade_id)\n"
    "        if asyncio.iscoroutine(res):\n"
    "            res = await asyncio.wait_for(\n"
    "                res,\n"
    "                timeout=(timeout or 120),\n"
    "            )\n\n"
    "        normalized = self._normalize_settlement(res)\n"
)
new = (
    "        # PocketOptionAsync.check_win() already manages its own broker-side\n"
    "        # timeout. Avoid a second asyncio.wait_for() around the same coroutine.\n"
    "        res = client.check_win(trade_id)\n"
    "        if asyncio.iscoroutine(res):\n"
    "            res = await res\n\n"
    "        normalized = self._normalize_settlement(res)\n"
)
if old in s:
    s = s.replace(old, new, 1)
    print("Adapter: removed nested check_win timeout.")
elif "res = client.check_win(trade_id)" in s and "res = await res" in s:
    print("Adapter: outer check_win timeout already removed.")
else:
    raise RuntimeError("Could not locate client.check_win(trade_id) in botv2_adapter.py.")
ADAPTER.write_text(s, encoding="utf-8")

# Storage: ensure imports/logger/lock exist.
s = STORAGE.read_text(encoding="utf-8-sig")

if not re.search(r"^import asyncio\s*$", s, re.MULTILINE):
    s = "import asyncio\n" + s
    print("Storage: added asyncio import.")

if not re.search(r"^import logging\s*$", s, re.MULTILINE):
    s = "import logging\n" + s
    print("Storage: added logging import.")

if not re.search(r"^logger\s*=", s, re.MULTILINE):
    # Put logger after the import section.
    lines = s.splitlines(True)
    pos = 0
    for i, line in enumerate(lines):
        if line.startswith("import ") or line.startswith("from "):
            pos = i + 1
    lines.insert(pos, "\nlogger = logging.getLogger(__name__)\n")
    s = "".join(lines)
    print("Storage: added module logger.")

if "_SETTLEMENT_LOCK = asyncio.Lock()" not in s:
    marker = "logger = logging.getLogger(__name__)\n"
    if marker not in s:
        raise RuntimeError("Could not establish the storage module logger.")
    s = s.replace(
        marker,
        marker + "\n# Prevent overlapping broker settlement sweeps.\n_SETTLEMENT_LOCK = asyncio.Lock()\n",
        1,
    )
    print("Storage: added settlement lock.")

start = s.find("    async def resolve_pending_trades(")
if start < 0:
    raise RuntimeError("resolve_pending_trades() was not found.")

m = re.search(r"\n    (?:async )?def ", s[start + 10:])
end = start + 10 + m.start() if m else len(s)
resolver = s[start:end]

if "async with _SETTLEMENT_LOCK:" not in resolver:
    line_end = resolver.find("\n")
    header = resolver[:line_end + 1]
    body = resolver[line_end + 1:]
    body = "".join(("    " + line if line.strip() else line) for line in body.splitlines(True))
    resolver = header + "        async with _SETTLEMENT_LOCK:\n" + body
    print("Storage: added settlement lock around resolver.")

old_call = (
    "                    res = await api_client.check_win(\n"
    "                        row.order_id,\n"
    "                        timeout=20,\n"
    "                    )\n"
)
new_call = (
    "                    logger.info(\n"
    "                        \"Checking broker settlement: trade=%s order=%s attempt=%s\",\n"
    "                        row.id,\n"
    "                        row.order_id,\n"
    "                        row.settlement_attempts,\n"
    "                    )\n\n"
    "                    try:\n"
    "                        res = await api_client.check_win(\n"
    "                            row.order_id,\n"
    "                            timeout=None,\n"
    "                        )\n"
    "                    except (asyncio.TimeoutError, TimeoutError) as exc:\n"
    "                        row.result = \"PENDING\"\n"
    "                        row.broker_result = \"BROKER_TIMEOUT\"\n"
    "                        row.settlement_source = \"broker_timeout\"\n"
    "                        row.last_settlement_at = datetime.utcnow()\n"
    "                        logger.warning(\n"
    "                            \"Broker settlement timed out: trade=%s order=%s attempt=%s error=%s\",\n"
    "                            row.id,\n"
    "                            row.order_id,\n"
    "                            row.settlement_attempts,\n"
    "                            exc,\n"
    "                        )\n"
    "                        continue\n"
    "                    except asyncio.CancelledError:\n"
    "                        raise\n"
    "                    except Exception as exc:\n"
    "                        row.result = \"PENDING\"\n"
    "                        row.broker_result = f\"SETTLEMENT_ERROR:{type(exc).__name__}\"\n"
    "                        row.settlement_source = \"broker_error\"\n"
    "                        row.last_settlement_at = datetime.utcnow()\n"
    "                        logger.exception(\n"
    "                            \"Broker settlement request failed: trade=%s order=%s attempt=%s\",\n"
    "                            row.id,\n"
    "                            row.order_id,\n"
    "                            row.settlement_attempts,\n"
    "                        )\n"
    "                        continue\n\n"
    "                    logger.info(\n"
    "                        \"Broker settlement response: trade=%s order=%s response=%r\",\n"
    "                        row.id,\n"
    "                        row.order_id,\n"
    "                        res,\n"
    "                    )\n"
)

if old_call in resolver:
    resolver = resolver.replace(old_call, new_call, 1)
    print("Storage: patched settlement broker call.")
elif "timeout=None" in resolver and "Broker settlement response:" in resolver:
    print("Storage: settlement broker call already patched.")
else:
    raise RuntimeError("Could not find the current api_client.check_win() call.")

s = s[:start] + resolver + s[end:]
STORAGE.write_text(s, encoding="utf-8")

for path in (ADAPTER, STORAGE):
    py_compile.compile(str(path), doraise=True)

print()
print("SUCCESS - settlement timeout/concurrency fix v2 applied.")
print("Changed: src/api/botv2_adapter.py and src/data/storage.py")
print("No main.py change is required.")
print("Restart the bot and place one short DEMO trade.")

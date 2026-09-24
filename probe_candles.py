import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(".").resolve()))

from config.settings import Settings
from src.api.factory import create_broker_client

ASSET = "EURUSD_otc"
PERIOD = 60

async def main():
    s = Settings(require_token=False)
    c = create_broker_client(s)
    await c.connect()
    lib = c._client  # PocketOptionAsync

    print("Client:", type(c).__name__)
    print("Lib   :", type(lib).__name__)
    print("Connected, balance should already be loaded")

    # Give the library a moment after connect (assets list)
    if hasattr(lib, "wait_for_assets"):
        try:
            await asyncio.wait_for(lib.wait_for_assets(), timeout=10)
            print("wait_for_assets: OK")
        except Exception as e:
            print("wait_for_assets failed:", type(e).__name__, e)
    else:
        print("No wait_for_assets – sleeping 4s")
        await asyncio.sleep(4)

    # ---------- 1. get_candles_live (recommended) ----------
    print("\n=== get_candles_live ===")
    try:
        gen = lib.get_candles_live(ASSET, PERIOD, hours=1.0, max_rows=50)
        closed, forming = await asyncio.wait_for(anext(gen), timeout=25)
        print(f"closed candles : {len(closed) if closed else 0}")
        if closed:
            print("  first:", closed[0])
            print("  last :", closed[-1])
        print("forming       :", forming)
    except Exception as e:
        print("get_candles_live ERROR:", type(e).__name__, e)

    # ---------- 2. history ----------
    print("\n=== history ===")
    try:
        res = await asyncio.wait_for(lib.history(ASSET, PERIOD), timeout=20)
        print("type:", type(res), "len:", len(res) if res is not None else None)
        if res:
            print("  sample:", res[0])
    except Exception as e:
        print("history ERROR:", type(e).__name__, e)

    # ---------- 3. get_candles_advanced ----------
    print("\n=== get_candles_advanced ===")
    try:
        now = int(time.time())
        res = await asyncio.wait_for(
            lib.get_candles_advanced(ASSET, PERIOD, now, 50),
            timeout=20,
        )
        print("type:", type(res), "len:", len(res) if res is not None else None)
        if res:
            print("  sample:", res[0])
    except Exception as e:
        print("get_candles_advanced ERROR:", type(e).__name__, e)

    # ---------- 4. get_ticks (raw ticks – useful fallback) ----------
    if hasattr(lib, "get_ticks"):
        print("\n=== get_ticks (last 5 min) ===")
        try:
            ticks = await asyncio.wait_for(lib.get_ticks(ASSET, 300), timeout=20)
            print("ticks:", len(ticks) if ticks else 0)
            if ticks:
                print("  sample:", ticks[0])
        except Exception as e:
            print("get_ticks ERROR:", type(e).__name__, e)

    # ---------- 5. live subscription (proof the stream works) ----------
    print("\n=== subscribe_symbol / live ticks (5s) ===")
    try:
        if hasattr(lib, "subscribe_symbol"):
            sub = await lib.subscribe_symbol(ASSET)  # or (ASSET, PERIOD)
            count = 0
            async for item in sub:
                print("  live:", item)
                count += 1
                if count >= 3:
                    break
        else:
            print("no subscribe_symbol")
    except Exception as e:
        print("subscribe ERROR:", type(e).__name__, e)

    await c.disconnect()
    print("\nDone.")

if __name__ == "__main__":
    # Python < 3.10 polyfill for anext
    if sys.version_info < (3, 10):
        async def anext(ait):
            return await ait.__anext__()
    asyncio.run(main())
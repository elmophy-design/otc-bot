from pathlib import Path
p=Path(r".\frontend\src\web\market_scanner.py")
s=p.read_text(encoding="utf-8")
needle="    async def _scan_asset(self, asset: str, timeframe: str) -> dict[str, Any]:\n        if self.fetcher is None:"
insert="    async def _scan_asset(self, asset: str, timeframe: str) -> dict[str, Any]:\n        cache_key=(asset, timeframe)\n        cached=self._scan_cache.get(cache_key)\n        if cached is not None:\n            cached_at,cached_result=cached\n            if asyncio.get_running_loop().time()-cached_at < _CACHE_SECONDS:\n                return cached_result\n        if self.fetcher is None:"
if needle not in s: raise SystemExit("STOP: exact scanner location not found")
s=s.replace(needle,insert,1)
p.write_text(s,encoding="utf-8")
print("OK: scanner cache lookup inserted")

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FILES = {
    'api.py': ROOT / 'frontend' / 'src' / 'web' / 'api.py',
    'frontend_api.ts': ROOT / 'frontend' / 'frontend_api.ts',
    'dashboard.tsx': ROOT / 'frontend' / 'components' / 'dashboard.tsx',
}

for source_name, target in FILES.items():
    if not target.exists():
        raise SystemExit(f'Missing target: {target}')
    target.write_text((Path(__file__).parent / source_name).read_text(encoding='utf-8'), encoding='utf-8')

print('Applied Phase 3: selected asset/timeframe now calls the production SignalEngine in read-only mode.')

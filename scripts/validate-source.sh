#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT/apps/backend"
python -m compileall -q api core database routers services integrations utils workers scripts main.py
PYTHONPATH=. pytest -q
DATABASE_URL=sqlite+pysqlite:////tmp/ithute_pay_bridge_validate.db ENVIRONMENT=test python - <<'PY'
from main import app
ops=[]
for route in app.routes:
    path=getattr(route,'path','')
    methods=sorted(getattr(route,'methods',[]) or [])
    if methods:
        for method in methods:
            if method not in {'HEAD','OPTIONS'}:
                ops.append((method,path))
    elif path:
        ops.append(('WS',path))
print(f'FastAPI operations: {len(ops)}')
PY
printf '\nBackend validation passed.\n'
printf 'Frontend validation: run `pnpm typecheck && pnpm build` in apps/frontend after dependencies are installed.\n'

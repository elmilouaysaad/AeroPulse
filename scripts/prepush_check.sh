#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

echo "==> 1. Ruff lint check"
ruff check .

echo "==> 2. Unit tests (excluding integration)"
pytest tests/ -v -m "not integration" --cov=src --cov-report=term

echo "==> 3. Optional Postgres integration check (if reachable)"
export POSTGRES_DSN="${POSTGRES_DSN:-postgresql://aeropulse:aeropulse@localhost:5432/aeropulse}"

if python - <<'PY'
import os, socket, urllib.parse
dsn = os.environ["POSTGRES_DSN"]
parsed = urllib.parse.urlparse(dsn)
host = parsed.hostname or "localhost"
port = parsed.port or 5432
sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.settimeout(1.5)
try:
    sock.connect((host, port))
    raise SystemExit(0)
except OSError:
    raise SystemExit(1)
finally:
    sock.close()
PY
then
    pytest tests/integration/test_db_idempotency.py -v -m integration
else
    echo "Skipping DB integration test (Postgres not reachable at $POSTGRES_DSN)."
fi

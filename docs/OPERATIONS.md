# AeroPulse Operations & Verification Runbook

## 1. Starting & Validating the Stack

From the repository root:

```bash
docker compose config -q
docker compose up -d
docker compose ps
```

Verify API health, readiness, and Prometheus metrics:

```bash
curl -sf http://localhost:${API_PORT:-8001}/health | python3 -m json.tool
curl -sf http://localhost:${API_PORT:-8001}/ready | python3 -m json.tool
curl -sf http://localhost:${API_PORT:-8001}/metrics | head -n 25
```

## 2. Secret Rotation (`scripts/rotate-secrets.sh`)

Secrets live in `.env` (`chmod 600`) and are interpolated by `docker-compose.yml` (including `redis-server --requirepass "${REDIS_PASSWORD}"` and `QDRANT__SERVICE__API_KEY: ${QDRANT_API_KEY}`).

### Pre-Flight & Credential Verification

Unset any exported secret variables in your shell so they do not override `.env`, then verify live credentials:

```bash
unset POSTGRES_PASSWORD REDIS_PASSWORD QDRANT_API_KEY \
      AIRFLOW_PASSWORD AIRFLOW_FERNET_KEY AIRFLOW_SECRET_KEY \
      GRAFANA_PASSWORD KAFKA_CLUSTER_ID

./scripts/rotate-secrets.sh --verify
```

### Rotating a Secret (Single or All Non-Destructive)

Every rotation command writes a timestamped snapshot to `./.env-backups/.env.<YYYYMMDD-HHMMSS>.bak` before modifying `.env`:

```bash
# Single-service rotations
./scripts/rotate-secrets.sh --rotate-redis
./scripts/rotate-secrets.sh --rotate-qdrant
./scripts/rotate-secrets.sh --rotate-postgres
./scripts/rotate-secrets.sh --rotate-airflow
./scripts/rotate-secrets.sh --rotate-grafana

# Rotate all non-destructive secrets (skips Kafka volume wipe)
./scripts/rotate-secrets.sh --rotate-all
```

If any container still holds a stale value after rotation, force-recreate the target service and dependent clients with `--no-deps`:

```bash
docker compose up -d --force-recreate --no-deps qdrant airflow api spark
sleep 4
./scripts/rotate-secrets.sh --verify
curl -sf http://localhost:${API_PORT:-8001}/ready | python3 -m json.tool
```

### Restoring from Backup

```bash
ls -lt .env-backups/
cp .env-backups/<latest-backup>.bak .env
docker compose up -d --force-recreate --no-deps postgres redis qdrant airflow api spark
sleep 4
./scripts/rotate-secrets.sh --verify
```

> **Warning:** `--rotate-kafka` is destructive (`WIPE` confirmation required): it wipes `kafka-1-data`, `kafka-2-data`, and `kafka-3-data` volumes and assigns a new `KAFKA_CLUSTER_ID`.

## 3. Running Tests

Integration tests connect to host-exposed services (`localhost` / `127.0.0.1`) using credentials from `.env`:

```bash
set -a && source .env && set +a
export POSTGRES_HOST=127.0.0.1
export POSTGRES_DSN="postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@127.0.0.1:${POSTGRES_PORT:-5432}/${POSTGRES_DB}"

make test
```

You can also run unit tests alone without Docker services:

```bash
pytest tests/ -v -m "not integration"
```

## 4. Troubleshooting Common Issues

- **Script fails with `env: $'bash\r': No such file or directory`:** Convert CRLF to LF and ensure executable permissions:
  ```bash
  sed -i 's/\r$//' scripts/rotate-secrets.sh
  chmod +x scripts/rotate-secrets.sh
  ```
- **Integration tests fail with password authentication error:** Export `.env` variables and set `POSTGRES_HOST=127.0.0.1` / `POSTGRES_DSN` before running `make test` so host-side `pytest` uses `.env` credentials instead of default fallbacks.
- **Prometheus alerts stay `inactive`:** Confirm targets are `up` in Prometheus (`/api/v1/targets`), test the rule's `expr` via `/api/v1/query`, verify the `for:` duration has elapsed, and reload rules with `curl -sf -X POST http://localhost:${PROMETHEUS_PORT:-9090}/-/reload`.
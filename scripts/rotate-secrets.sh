#!/usr/bin/env bash
# =============================================================================
# AeroPulse secret rotation helper — MANUAL, interactive.
#
# Every destructive action asks for explicit confirmation. You drive the
# sequence; the script performs the mechanical steps and verifies them.
#
# Usage:
#   ./scripts/rotate-secrets.sh                      # interactive menu
#   ./scripts/rotate-secrets.sh --generate-env       # bootstrap .env from .env.example
#   ./scripts/rotate-secrets.sh --rotate-postgres
#   ./scripts/rotate-secrets.sh --rotate-redis
#   ./scripts/rotate-secrets.sh --rotate-airflow
#   ./scripts/rotate-secrets.sh --rotate-grafana
#   ./scripts/rotate-secrets.sh --rotate-qdrant
#   ./scripts/rotate-secrets.sh --rotate-kafka       # DESTRUCTIVE
#   ./scripts/rotate-secrets.sh --rotate-all         # non-destructive set
#   ./scripts/rotate-secrets.sh --verify
# =============================================================================
set -euo pipefail

ENV_FILE="${ENV_FILE:-.env}"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.yml}"
ENV_EXAMPLE="${ENV_EXAMPLE:-.env.example}"
BACKUP_DIR="${BACKUP_DIR:-./.env-backups}"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
log_info()  { echo -e "${GREEN}[INFO]${NC}  $*"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
log_error() { echo -e "${RED}[ERROR]${NC} $*"; }
log_step()  { echo -e "${BLUE}[STEP]${NC}  $*"; }

require_tools() {
  local missing=()
  for t in docker awk openssl; do
    command -v "$t" >/dev/null 2>&1 || missing+=("$t")
  done
  if ((${#missing[@]})); then
    log_error "Missing required tools: ${missing[*]}"
    exit 1
  fi
}

require_env_file() {
  [[ -f "$ENV_FILE" ]] || { log_error "$ENV_FILE not found. Run: ./scripts/rotate-secrets.sh --generate-env"; exit 1; }
}

compose() { docker compose -f "$COMPOSE_FILE" "$@"; }

# -------- env helpers --------------------------------------------------------
get_env_var() {
  local key="$1"
  local line
  line="$(grep -E "^${key}=" "$ENV_FILE" | head -n 1 || true)"
  [[ -n "$line" ]] || return 0
  local val="${line#*=}"
  val="${val%$'\r'}"
  if [[ "$val" =~ ^\"(.*)\"$ ]]; then
    val="${BASH_REMATCH[1]}"
  elif [[ "$val" =~ ^\'(.*)\'$ ]]; then
    val="${BASH_REMATCH[1]}"
  fi
  printf '%s' "$val"
}

set_env_var() {
  local key="$1" value="$2" tmp
  tmp="$(mktemp)"
  if grep -qE "^${key}=" "$ENV_FILE"; then
    awk -v k="$key" -v v="$value" '
      index($0, k "=") == 1 { print k "=" v; next }
      { print }
    ' "$ENV_FILE" > "$tmp"
  else
    cp "$ENV_FILE" "$tmp"
    printf '%s=%s\n' "$key" "$value" >> "$tmp"
  fi
  mv "$tmp" "$ENV_FILE"
  chmod 600 "$ENV_FILE"
}

gen_password() {
  local len="${1:-40}"
  openssl rand -base64 $((len * 2)) | tr -dc 'A-Za-z0-9' | head -c "$len"
}

gen_fernet() {
  if command -v python3 >/dev/null 2>&1; then
    python3 - <<'PY' 2>/dev/null && return 0
from cryptography.fernet import Fernet
print(Fernet.generate_key().decode())
PY
  fi
  openssl rand -base64 32 | tr '+/' '-_'
}

backup_env() {
  mkdir -p "$BACKUP_DIR"
  local ts
  ts="$(date +%Y%m%d-%H%M%S)"
  cp "$ENV_FILE" "$BACKUP_DIR/.env.$ts.bak"
  chmod 600 "$BACKUP_DIR/.env.$ts.bak"
  log_info "Backed up $ENV_FILE -> $BACKUP_DIR/.env.$ts.bak"
}

confirm() {
  local prompt="${1:-Proceed?}" ans
  read -rp "$prompt [y/N] " ans
  [[ "$ans" =~ ^[Yy]$ ]]
}

# -------- bootstrap ----------------------------------------------------------
generate_env_from_example() {
  [[ -f "$ENV_EXAMPLE" ]] || { log_error "$ENV_EXAMPLE not found."; exit 1; }
  if [[ -f "$ENV_FILE" ]]; then
    log_error "$ENV_FILE already exists; refusing to overwrite."
    exit 1
  fi

  log_step "Creating $ENV_FILE from $ENV_EXAMPLE with fresh random secrets..."
  tr -d '\r' < "$ENV_EXAMPLE" > "$ENV_FILE"
  chmod 600 "$ENV_FILE"

  set_env_var POSTGRES_PASSWORD   "$(gen_password 40)"
  set_env_var REDIS_PASSWORD      "$(gen_password 40)"
  set_env_var QDRANT_API_KEY      "$(gen_password 48)"
  set_env_var AIRFLOW_PASSWORD    "$(gen_password 24)"
  set_env_var AIRFLOW_FERNET_KEY  "$(gen_fernet)"
  set_env_var AIRFLOW_SECRET_KEY  "$(gen_password 48)"
  set_env_var GRAFANA_PASSWORD    "$(gen_password 24)"

  log_info "$ENV_FILE created (chmod 600)."
  log_warn "Back up $ENV_FILE to a secure secret store. It is NOT safe to commit."
  log_warn "First 'docker compose up' will initialize services with these passwords."
}

# -------- rotation: PostgreSQL ----------------------------------------------
rotate_postgres() {
  echo; log_step "=== PostgreSQL password rotation ==="
  local cur new user db
  cur="$(get_env_var POSTGRES_PASSWORD)"
  user="$(get_env_var POSTGRES_USER)"
  db="$(get_env_var POSTGRES_DB)"
  new="$(gen_password 40)"

  log_warn "This uses the CURRENT password once to change it in the live DB,"
  log_warn "then updates $ENV_FILE and recreates dependent services."
  confirm "Proceed?" || { log_warn "Skipped"; return 0; }

  log_step "Altering password in live PostgreSQL..."
  if ! compose exec -T -e PGPASSWORD="$cur" postgres \
       psql -U "$user" -d "$db" -v ON_ERROR_STOP=1 \
       -c "ALTER USER \"$user\" WITH PASSWORD '$new';" >/dev/null; then
    log_error "Failed to update PostgreSQL password. Is the service running and the current password correct?"
    return 1
  fi

  set_env_var POSTGRES_PASSWORD "$new"
  log_info "Updated POSTGRES_PASSWORD in $ENV_FILE."

  log_step "Recreating postgres + dependents (poller, spark, airflow, api)..."
  compose up -d --force-recreate postgres poller spark airflow api

  log_info "PostgreSQL rotation complete."
}

# -------- rotation: Redis ----------------------------------------------------
rotate_redis() {
  echo; log_step "=== Redis password rotation ==="
  local cur new
  cur="$(get_env_var REDIS_PASSWORD)"
  new="$(gen_password 40)"

  log_warn "Redis is used as a cache/queue here. Data is not persisted across"
  log_warn "container recreation in this configuration."
  confirm "Proceed?" || { log_warn "Skipped"; return 0; }

  log_step "Applying new password at runtime via CONFIG SET..."
  if ! compose exec -T redis sh -c 'redis-cli -a "$1" --no-auth-warning CONFIG SET requirepass "$2"' _ "$cur" "$new" >/dev/null 2>&1; then
    log_error "Redis CONFIG SET failed. Verify REDIS_PASSWORD in $ENV_FILE matches the live password."
    return 1
  fi

  set_env_var REDIS_PASSWORD "$new"
  log_info "Updated REDIS_PASSWORD in $ENV_FILE."

  log_step "Recreating redis + dependents (airflow, api)..."
  compose up -d --force-recreate redis airflow api

  log_info "Redis rotation complete."
}

# -------- rotation: Airflow --------------------------------------------------
rotate_airflow() {
  echo; log_step "=== Airflow admin password rotation ==="
  local user new
  user="$(get_env_var AIRFLOW_USERNAME)"
  new="$(gen_password 24)"

  confirm "Reset Airflow admin password for '$user'?" || { log_warn "Skipped"; return 0; }

  if ! compose exec -T airflow airflow users reset-password \
       --username "$user" --password "$new" >/dev/null; then
    log_error "Airflow password reset failed."
    return 1
  fi

  set_env_var AIRFLOW_PASSWORD "$new"
  log_info "Airflow rotation complete. New value stored in AIRFLOW_PASSWORD."
}

# -------- rotation: Grafana --------------------------------------------------
rotate_grafana() {
  echo; log_step "=== Grafana admin password rotation ==="
  local new
  new="$(gen_password 24)"

  confirm "Reset Grafana admin password?" || { log_warn "Skipped"; return 0; }

  if ! compose exec -T grafana grafana cli admin reset-admin-password "$new" >/dev/null; then
    log_error "Grafana password reset failed."
    return 1
  fi

  set_env_var GRAFANA_PASSWORD "$new"
  log_info "Grafana rotation complete."
}

# -------- rotation: Qdrant ---------------------------------------------------
rotate_qdrant() {
  echo; log_step "=== Qdrant API key rotation ==="
  local new
  new="$(gen_password 48)"

  log_warn "Qdrant and its clients (airflow, api, spark) will be recreated to pick up the new key."
  confirm "Proceed?" || { log_warn "Skipped"; return 0; }

  set_env_var QDRANT_API_KEY "$new"
  log_step "Recreating qdrant + clients..."
  compose up -d --force-recreate qdrant airflow api spark

  log_info "Qdrant rotation complete."
}

# -------- rotation: Kafka (DESTRUCTIVE) -------------------------------------
rotate_kafka() {
  echo; log_step "=== Kafka CLUSTER_ID rotation (DESTRUCTIVE) ==="
  log_warn "Rotating KAFKA_CLUSTER_ID requires wiping ALL Kafka data volumes."
  log_warn "Every topic and message will be permanently destroyed."
  read -rp "Type WIPE to confirm: " ans
  [[ "$ans" == "WIPE" ]] || { log_warn "Aborted"; return 0; }

  local new_id project_name
  new_id="aeropulse-$(gen_password 16 | tr '[:upper:]' '[:lower:]')"
  project_name="$(basename "$PWD" | tr '[:upper:]' '[:lower:]')"
  set_env_var KAFKA_CLUSTER_ID "$new_id"

  log_step "Stopping Kafka and removing volumes..."
  compose rm -sf kafka-1 kafka-2 kafka-3 kafka-init || true
  docker volume rm \
    "${project_name}_kafka-1-data" \
    "${project_name}_kafka-2-data" \
    "${project_name}_kafka-3-data" 2>/dev/null || true

  log_step "Recreating Kafka with new cluster ID..."
  compose up -d kafka-1 kafka-2 kafka-3 kafka-init

  log_info "Kafka rotation complete (all data wiped)."
}

# -------- rotation: all non-destructive -------------------------------------
rotate_all() {
  echo; log_step "=== Rotate ALL non-destructive secrets ==="
  log_warn "Will rotate: PostgreSQL, Redis, Airflow, Grafana, Qdrant."
  log_warn "Kafka is skipped (run --rotate-kafka separately if needed)."
  confirm "Proceed?" || return 0

  backup_env
  rotate_postgres || log_error "Postgres rotation failed; continuing."
  rotate_redis    || log_error "Redis rotation failed; continuing."
  rotate_airflow  || log_error "Airflow rotation failed; continuing."
  rotate_grafana  || log_error "Grafana rotation failed; continuing."
  rotate_qdrant   || log_error "Qdrant rotation failed; continuing."

  log_info "Rotation pass finished. Backup stored in $BACKUP_DIR."
}

# -------- verify -------------------------------------------------------------
verify() {
  echo; log_step "=== Verifying credentials against running services ==="
  local pg_user pg_pass redis_pass qdrant_key
  pg_user="$(get_env_var POSTGRES_USER)"
  pg_pass="$(get_env_var POSTGRES_PASSWORD)"
  redis_pass="$(get_env_var REDIS_PASSWORD)"
  qdrant_key="$(get_env_var QDRANT_API_KEY)"

  printf 'PostgreSQL : '
  if compose exec -T -e PGPASSWORD="$pg_pass" postgres \
       psql -U "$pg_user" -c 'SELECT 1' >/dev/null 2>&1; then
    echo "OK"
  else
    echo "FAIL"
  fi

  printf 'Redis      : '
  if compose exec -T redis sh -c 'redis-cli -a "$1" --no-auth-warning PING' _ "$redis_pass" 2>/dev/null | grep -q PONG; then
    echo "OK"
  else
    echo "FAIL"
  fi

  printf 'Qdrant     : '
  local qdrant_port
  qdrant_port="$(get_env_var QDRANT_PORT_6333)"
  qdrant_port="${qdrant_port:-6333}"
  if { command -v curl >/dev/null 2>&1 && curl -sf -H "api-key: $qdrant_key" "http://localhost:${qdrant_port}/collections" >/dev/null; } \
     || { command -v python3 >/dev/null 2>&1 && python3 -c '
import sys, urllib.request
url, key = sys.argv[1], sys.argv[2]
req = urllib.request.Request(url, headers={"api-key": key})
with urllib.request.urlopen(req, timeout=5) as resp:
    if resp.status != 200:
        sys.exit(1)
' "http://localhost:${qdrant_port}/collections" "$qdrant_key" 2>/dev/null; }; then
    echo "OK"
  else
    echo "FAIL"
  fi
}

# -------- menu ---------------------------------------------------------------
menu() {
  cat <<'EOF'
===============================
 AeroPulse Secret Manager (manual)
===============================
 1) Generate .env from .env.example (fresh secrets)
 2) Rotate PostgreSQL password
 3) Rotate Redis password
 4) Rotate Airflow admin password
 5) Rotate Grafana admin password
 6) Rotate Qdrant API key
 7) Rotate Kafka CLUSTER_ID  (DESTRUCTIVE - wipes data)
 8) Rotate all (non-destructive)
 9) Verify current credentials
 0) Exit
===============================
EOF
}

main() {
  require_tools

  case "${1:-}" in
    --generate-env) generate_env_from_example; exit 0 ;;
    --help|-h)      menu; exit 0 ;;
  esac

  require_env_file

  case "${1:-}" in
    --rotate-postgres) backup_env; rotate_postgres; exit $? ;;
    --rotate-redis)    backup_env; rotate_redis;    exit $? ;;
    --rotate-airflow)  backup_env; rotate_airflow;  exit $? ;;
    --rotate-grafana)  backup_env; rotate_grafana;  exit $? ;;
    --rotate-qdrant)   backup_env; rotate_qdrant;   exit $? ;;
    --rotate-kafka)    backup_env; rotate_kafka;    exit $? ;;
    --rotate-all)      rotate_all;  exit $? ;;
    --verify)          verify;      exit $? ;;
  esac

  while true; do
    echo; menu
    read -rp "Choose: " choice
    case "$choice" in
      1) if [[ -f "$ENV_FILE" ]]; then log_error "$ENV_FILE exists; move it aside first."; else generate_env_from_example; fi ;;
      2) backup_env; rotate_postgres ;;
      3) backup_env; rotate_redis ;;
      4) backup_env; rotate_airflow ;;
      5) backup_env; rotate_grafana ;;
      6) backup_env; rotate_qdrant ;;
      7) backup_env; rotate_kafka ;;
      8) rotate_all ;;
      9) verify ;;
      0) exit 0 ;;
      *) log_error "Invalid choice." ;;
    esac
    echo; read -rp "Press Enter to return to menu..." _
  done
}

main "$@"
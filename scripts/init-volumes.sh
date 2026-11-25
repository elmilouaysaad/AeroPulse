#!/usr/bin/env bash
# =============================================================================
# Pre-create the external volumes that docker-compose.yml declares but does
# not own. Safe to run repeatedly (idempotent). Required before the first
# `docker compose up` in ANY environment.
#
# Usage:  ./scripts/init-volumes.sh [--project-name NAME]
# =============================================================================
set -euo pipefail

PROJECT="${1:-aeropulse}"

# Strip leading "--project-name" if passed as positional
[[ "$PROJECT" == "--project-name" ]] && PROJECT="${2:-aeropulse}"

create_volume() {
  local name="$1"
  if docker volume inspect "$name" >/dev/null 2>&1; then
    echo "[OK]   $name already exists"
  else
    docker volume create "$name" >/dev/null
    echo "[NEW]  $name created"
  fi
}

echo "Ensuring external volumes for project '$PROJECT' exist..."
create_volume "${PROJECT}_model-cache-api"
create_volume "${PROJECT}_model-cache-airflow"
echo "Done. Safe to run 'docker compose up -d'."
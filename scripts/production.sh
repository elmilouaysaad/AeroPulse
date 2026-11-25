cp .env.prod.example .env.prod && chmod 600 .env.prod
# pre-create Docker secrets (one-time, on Swarm)
printf '%s' "STRONG_PG_PW"     | docker secret create postgres_password -
printf '%s' "STRONG_REDIS_PW"  | docker secret create redis_password -
printf '%s' "STRONG_QDRANT_KEY"| docker secret create qdrant_api_key -
printf '%s' "STRONG_AIRFLOW_PW"| docker secret create airflow_password -
printf '%s' "$(python -c 'from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())')" \
                               | docker secret create airflow_fernet_key -
printf '%s' "$(openssl rand -base64 48)" \
                               | docker secret create airflow_secret_key -
printf '%s' "STRONG_GRAFANA_PW"| docker secret create grafana_password -

# Always inspect the merged output before deploying:
docker compose --env-file .env.prod -f compose.yaml -f compose.prod.yaml config

# Deploy:
docker compose --env-file .env.prod -f compose.yaml -f compose.prod.yaml up -d
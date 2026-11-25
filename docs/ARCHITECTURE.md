# AeroPulse System Architecture

## 1. End-to-End Data Flow

AeroPulse separates real-time kinematic stream processing from asynchronous narrative generation and similarity search:

1. **Ingestion (`src/ingestion/`):** `poller.py` queries `adsb.lol` v2 within a ~100 NM radius around JFK on a 15-second interval, falling back to `adsb.fi` when needed. `parser.py` normalizes raw feeds into `StateVector` records (`on_ground`, stripped callsigns, filtered stale/incomplete points) and `producer.py` publishes them to Kafka (`aircraft_state`) keyed by ICAO24 `hex`.
2. **Stateful Stream Detection (`src/streaming/`):** `detector.py` runs in Spark Structured Streaming (`local[2]`) with a 2-minute watermark and stateful tracking (`state.py`, `detection.py`, `schema.py`):
   - **Emergency squawks (`7700`, `7600`, `7500`):** Emits on state transition so persistent squawks do not flood downstream sinks every poll.
   - **Rapid descent (`rapid_descent`):** Detects sustained descent $\ge 3,000\text{ ft/min}$ over $\ge 3\text{s}$ (clamped at $15,000\text{ ft/min}$) with a 60-second suppression window.
   - **Holding pattern (`holding_pattern`):** Detects $>270^\circ$ cumulative heading rotation at $\ge 2,000\text{ ft}$ within a $\pm 1,000\text{ ft}$ altitude band with a 300-second suppression window.
3. **Idempotent Sink (`docker/postgres-init.sql` & `src/streaming/detector.py`):** Micro-batches stage rows and merge into `anomalies` using `INSERT ... SELECT ... ON CONFLICT (hex, anomaly_type, detected_at_ms) DO NOTHING`, ensuring replays from Spark checkpoints or Kafka offsets remain idempotent.
4. **AI Enrichment & Vector Search (`src/ai/` & `airflow/dags/`):** Airflow DAGs (`dag_ai_brief`, `dag_explain_anomalies`) coordinate scheduled briefs, anomaly explanations, kinematic vector embeddings (`kinematic_vectors.py`, `embed.py`), Qdrant indexing (`similarity.py`), and Redis/Postgres persistence (`cache.py`, `db.py`). LLM calls Pollinations (`client.py`, `prompts.py`) with 429/quota vs. 5xx error handling.
5. **Read API & Dashboard (`src/api/` & `src/dashboard/`):** FastAPI exposes `/health`, `/ready`, `/metrics`, `/airspace/brief`, `/anomalies`, `/aircraft/{hex}/track`, `/stats`, and `/similar`. Streamlit renders the map and anomaly views while applying client-side filters.
6. **Observability (`docker/`, `grafana/`, `loki/`, `promtail/`, `prometheus/`):** Prometheus scrapes service metrics and evaluates rules in `./docker/prometheus/rules/aeropulse-alerts.yml`; Promtail ships container logs to Loki; Grafana provisions Prometheus and Loki datasources alongside `./grafana/dashboards/json/aeropulse-observability.json`.

## 2. Failure Isolation & Resilience

- **LLM decoupled from detection:** If external LLM APIs fail or hit rate limits, anomaly detection and `/anomalies` ingestion continue unaffected; narrative fields degrade explicitly (`provider` and `stale` indicators).
- **Cache vs. durable fallback:** Brief reads check Redis first and fall back to Postgres when cache entries expire or are cold.
- **Readiness vs. liveness:** `/health` verifies process liveness, while `/ready` probes Postgres, Redis, and Qdrant so operators can distinguish a running API process from an unhealthy dependency.

## 3. Repository Map

| Path | Responsibility |
|---|---|
| `docker-compose.yml` | Primary local stack orchestration and environment interpolation |
| `src/ingestion/` | ADS-B client, state normalization, and Kafka producer |
| `src/streaming/` | Spark Structured Streaming job, state machine, and deterministic detectors |
| `src/api/` | FastAPI service, DB/cache queries, readiness checks, and Pydantic schemas |
| `src/ai/` | Brief generation, anomaly explanations, embeddings, similarity search, and LLM fallback |
| `src/dashboard/` | Streamlit operator UI |
| `airflow/dags/` | Scheduled Airflow DAGs for briefs and anomaly explanations |
| `scripts/` | Secret rotation (`rotate-secrets.sh`), diagnostics, migrations, and drills |
| `tests/` | Unit tests (`tests/test_*.py`) and integration tests (`tests/integration/`) |
-- =============================================================================
-- AeroPulse PostgreSQL bootstrap schema — Phase 1
--
-- Use this file for FRESH installs (empty postgres-data volume).
-- For EXISTING databases, apply migrate_phase1.sql instead.
--
-- Both paths produce the same final schema. Do not diverge them: if you add a
-- column/index/constraint here, mirror it in a numbered migration and vice versa.
-- =============================================================================

-- -----------------------------------------------------------------------------
-- Airflow side-car database
-- Runs before anything else so a failure doesn't leave app tables half-built.
-- CREATE DATABASE cannot run inside a transaction block, so use psql's \gexec
-- to make the statement idempotent on re-run.
-- -----------------------------------------------------------------------------
SELECT 'CREATE DATABASE aeropulse_airflow OWNER aeropulse'
WHERE NOT EXISTS (
    SELECT 1 FROM pg_database WHERE datname = 'aeropulse_airflow'
)\gexec

-- -----------------------------------------------------------------------------
-- anomalies: canonical detected-anomaly records
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS anomalies (
    batch_id        BIGINT           NOT NULL,
    hex             TEXT             NOT NULL,
    flight          TEXT,
    anomaly_type    TEXT             NOT NULL,
    detected_at_ms  BIGINT           NOT NULL,
    lat             DOUBLE PRECISION,
    lon             DOUBLE PRECISION,
    alt_baro_ft     DOUBLE PRECISION,
    details         TEXT,
    severity        TEXT             NOT NULL DEFAULT 'INFO',
    phase           TEXT,
    rate_fpm        DOUBLE PRECISION,
    turn_rate_dps   DOUBLE PRECISION,
    inserted_at     TIMESTAMPTZ      NOT NULL DEFAULT NOW(),
    PRIMARY KEY (hex, anomaly_type, detected_at_ms)
);

CREATE INDEX IF NOT EXISTS idx_anomalies_detected_at
    ON anomalies (detected_at_ms DESC);

CREATE INDEX IF NOT EXISTS idx_anomalies_severity_type
    ON anomalies (severity, anomaly_type, detected_at_ms DESC);

-- -----------------------------------------------------------------------------
-- anomalies_staging: append-then-merge buffer used by Spark streaming
-- Nullable severity/phase/etc. here so the merge step can fill defaults.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS anomalies_staging (
    batch_id        BIGINT           NOT NULL,
    hex             TEXT             NOT NULL,
    flight          TEXT,
    anomaly_type    TEXT             NOT NULL,
    detected_at_ms  BIGINT           NOT NULL,
    lat             DOUBLE PRECISION,
    lon             DOUBLE PRECISION,
    alt_baro_ft     DOUBLE PRECISION,
    details         TEXT,
    severity        TEXT,
    phase           TEXT,
    rate_fpm        DOUBLE PRECISION,
    turn_rate_dps   DOUBLE PRECISION
);

-- -----------------------------------------------------------------------------
-- anomaly_notes: LLM-written explanations, now FK-bound to anomalies
--
-- The composite PK doubles as the supporting index for the FK, so no extra
-- index on (anomaly_hex, anomaly_type, anomaly_at_ms) is required.
-- ON DELETE CASCADE keeps notes from outliving their parent anomaly.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS anomaly_notes (
    anomaly_hex     TEXT        NOT NULL,
    anomaly_type    TEXT        NOT NULL,
    anomaly_at_ms   BIGINT      NOT NULL,
    explanation     TEXT        NOT NULL,
    provider        TEXT        NOT NULL,
    generated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (anomaly_hex, anomaly_type, anomaly_at_ms),
    CONSTRAINT fk_anomaly_notes_to_anomalies
        FOREIGN KEY (anomaly_hex, anomaly_type, anomaly_at_ms)
        REFERENCES anomalies (hex, anomaly_type, detected_at_ms)
        ON DELETE CASCADE
);

-- -----------------------------------------------------------------------------
-- briefs: scheduled LLM briefings over anomaly windows
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS briefs (
    id              BIGSERIAL   PRIMARY KEY,
    window_start_ms BIGINT      NOT NULL,
    window_end_ms   BIGINT      NOT NULL,
    text            TEXT        NOT NULL,
    provider        TEXT        NOT NULL,
    generated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
-- Phase 1: new columns + FK constraint against orphans
BEGIN;

ALTER TABLE anomalies
  ADD COLUMN IF NOT EXISTS severity      TEXT NOT NULL DEFAULT 'INFO',
  ADD COLUMN IF NOT EXISTS phase         TEXT,
  ADD COLUMN IF NOT EXISTS rate_fpm      DOUBLE PRECISION,
  ADD COLUMN IF NOT EXISTS turn_rate_dps DOUBLE PRECISION;

ALTER TABLE anomalies_staging
  ADD COLUMN IF NOT EXISTS severity      TEXT,
  ADD COLUMN IF NOT EXISTS phase         TEXT,
  ADD COLUMN IF NOT EXISTS rate_fpm      DOUBLE PRECISION,
  ADD COLUMN IF NOT EXISTS turn_rate_dps DOUBLE PRECISION;

CREATE INDEX IF NOT EXISTS idx_anomalies_severity_type
  ON anomalies (severity, anomaly_type, detected_at_ms DESC);

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'fk_anomaly_notes_to_anomalies'
  ) THEN
    ALTER TABLE anomaly_notes
      ADD CONSTRAINT fk_anomaly_notes_to_anomalies
      FOREIGN KEY (anomaly_hex, anomaly_type, anomaly_at_ms)
      REFERENCES anomalies (hex, anomaly_type, detected_at_ms)
      ON DELETE CASCADE;
  END IF;
END $$;

COMMIT;
-- scripts/purge_orphan_notes.sql
-- Deletes anomaly_notes whose source anomaly no longer exists.
-- Background: a prior anomalies purge left 900+ notes orphaned,
-- which polluted the Qdrant index used by /similar.
BEGIN;

-- 1. Count before
SELECT COUNT(*) AS orphan_notes_before FROM anomaly_notes n
LEFT JOIN anomalies a
  ON a.hex = n.anomaly_hex
 AND a.anomaly_type = n.anomaly_type
 AND a.detected_at_ms = n.anomaly_at_ms
WHERE a.hex IS NULL;

-- 2. Delete orphans
DELETE FROM anomaly_notes n
WHERE NOT EXISTS (
    SELECT 1 FROM anomalies a
    WHERE a.hex = n.anomaly_hex
      AND a.anomaly_type = n.anomaly_type
      AND a.detected_at_ms = n.anomaly_at_ms
);

-- 3. Count after (should be 0)
SELECT COUNT(*) AS orphan_notes_after FROM anomaly_notes n
LEFT JOIN anomalies a
  ON a.hex = n.anomaly_hex
 AND a.anomaly_type = n.anomaly_type
 AND a.detected_at_ms = n.anomaly_at_ms
WHERE a.hex IS NULL;

COMMIT;
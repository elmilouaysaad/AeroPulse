"""Integration tests for idempotent writes in src.ai.db."""
from __future__ import annotations

import pytest

from src.ai import db
from src.api import db as api_db


@pytest.mark.integration
def test_write_explanation_is_idempotent():
    hex_, anomaly_type, detected_at_ms = ("idem-test", "squawk_7700", 1794240000000)
    batch_id = 999_999

    try:
        with api_db.connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO anomalies
                    (batch_id, hex, flight, anomaly_type, detected_at_ms, lat, lon, alt_baro_ft, details)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (hex, anomaly_type, detected_at_ms) DO NOTHING
                """,
                (batch_id, hex_, "TEST1", anomaly_type, detected_at_ms, 40.0, -74.0, 28000.0, "general_emergency"),
            )

        db.write_explanation(hex_, anomaly_type, detected_at_ms, "first", "pollinations")

        with api_db.connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT explanation, provider
                FROM anomaly_notes
                WHERE anomaly_hex = %s AND anomaly_type = %s AND anomaly_at_ms = %s
                """,
                (hex_, anomaly_type, detected_at_ms),
            )
            rows = cur.fetchall()

        assert len(rows) == 1
    finally:
        with api_db.connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                DELETE FROM anomaly_notes
                WHERE anomaly_hex = %s AND anomaly_type = %s AND anomaly_at_ms = %s
                """,
                (hex_, anomaly_type, detected_at_ms),
            )
            cur.execute(
                """
                DELETE FROM anomalies
                WHERE hex = %s AND anomaly_type = %s AND detected_at_ms = %s
                """,
                (hex_, anomaly_type, detected_at_ms),
            )
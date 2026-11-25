import os
import psycopg
import pytest

pytestmark = pytest.mark.integration


def _dsn() -> str:
    if os.getenv("POSTGRES_DSN"):
        return os.environ["POSTGRES_DSN"]
    user = os.getenv("POSTGRES_USER", "aeropulse")
    password = os.getenv("POSTGRES_PASSWORD", "aeropulse")
    host = os.getenv("POSTGRES_HOST", "127.0.0.1")
    port = os.getenv("POSTGRES_PORT", "5432")
    dbname = os.getenv("POSTGRES_DB", "aeropulse")
    return f"postgresql://{user}:{password}@{host}:{port}/{dbname}"


def test_anomaly_primary_key_deduplicates():
    """Simulates a Spark batch replay: same anomaly written twice."""
    row = ("replay-test", "rapid_descent", 1794240000000,
           40.0, -74.0, 28000.0, "3000 ft/min")
    sql = """
        INSERT INTO anomalies
            (batch_id, hex, anomaly_type, detected_at_ms,
             lat, lon, alt_baro_ft, details)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (hex, anomaly_type, detected_at_ms) DO NOTHING
    """
    with psycopg.connect(_dsn()) as conn, conn.cursor() as cur:
        cur.execute(sql, (1, *row))
        cur.execute(sql, (2, *row))   # different batch_id, same anomaly
        conn.commit()
        cur.execute(
            "SELECT COUNT(*) FROM anomalies WHERE hex=%s", ("replay-test",)
        )
        assert cur.fetchone()[0] == 1
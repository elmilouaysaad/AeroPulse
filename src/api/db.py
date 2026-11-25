"""Postgres read queries for the API. All queries are parameterized."""
from __future__ import annotations

import os
from contextlib import contextmanager

import psycopg


def _dsn() -> str:
    return os.getenv(
        "POSTGRES_DSN",
        "postgresql://aeropulse:aeropulse@postgres:5432/aeropulse",
    )


@contextmanager
def connect():
    with psycopg.connect(_dsn()) as conn:
        yield conn


def recent_anomalies(since_ms: int, limit: int = 100) -> list[dict]:
    sql = """
        SELECT a.hex, a.flight, a.anomaly_type, a.detected_at_ms,
               a.lat, a.lon, a.alt_baro_ft, a.details,
               n.explanation, n.provider AS explanation_provider
        FROM anomalies a
        LEFT JOIN anomaly_notes n
          ON n.anomaly_hex = a.hex
         AND n.anomaly_type = a.anomaly_type
         AND n.anomaly_at_ms = a.detected_at_ms
        WHERE a.detected_at_ms >= %s
        ORDER BY a.detected_at_ms DESC
        LIMIT %s
    """
    with connect() as conn, conn.cursor() as cur:
        cur.execute(sql, (since_ms, limit))
        cols = [d.name for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


def aircraft_track(hex_: str, limit: int = 200) -> list[dict]:
    sql = """
        SELECT detected_at_ms, lat, lon, alt_baro_ft, anomaly_type
        FROM anomalies
        WHERE hex = %s
        ORDER BY detected_at_ms ASC
        LIMIT %s
    """
    with connect() as conn, conn.cursor() as cur:
        cur.execute(sql, (hex_, limit))
        cols = [d.name for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


def latest_brief() -> dict | None:
    sql = """
        SELECT text, provider, generated_at
        FROM briefs
        ORDER BY id DESC
        LIMIT 1
    """
    with connect() as conn, conn.cursor() as cur:
        cur.execute(sql)
        row = cur.fetchone()
    if not row:
        return None
    return {
        "text": row[0],
        "provider": row[1],
        "generated_at": row[2].isoformat(),
    }


def stats(since_ms: int) -> dict:
    sql = """
        SELECT anomaly_type, COUNT(*) AS n
        FROM anomalies
        WHERE detected_at_ms >= %s
        GROUP BY anomaly_type
    """
    with connect() as conn, conn.cursor() as cur:
        cur.execute(sql, (since_ms,))
        rows = cur.fetchall()
    by_type = {row[0]: int(row[1]) for row in rows}
    return {"total": sum(by_type.values()), "by_type": by_type}

"""Postgres access for the AI layer. Every write is idempotent."""
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


def fetch_recent_anomalies(window_minutes: int = 15) -> list[dict]:
    sql = """
        SELECT hex, flight, anomaly_type, detected_at_ms,
               lat, lon, alt_baro_ft, details
        FROM anomalies
        WHERE detected_at_ms >= (
            (EXTRACT(EPOCH FROM NOW()) * 1000)::BIGINT - %s * 60 * 1000
        )
        ORDER BY detected_at_ms DESC
        LIMIT 50
    """
    with connect() as conn, conn.cursor() as cur:
        cur.execute(sql, (window_minutes,))
        cols = [d.name for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


def fetch_unexplained_anomalies(limit: int = 5, max_age_minutes: int = 180) -> list[dict]:
    """Newest-first, one row per (aircraft, anomaly type).

    The dashboard shows the latest detection per aircraft, so that is the
    one that must be explained first. Old backlog is ignored after
    `max_age_minutes` so the LLM quota is never spent on stale rows.
    """
    sql = """
        SELECT * FROM (
            SELECT DISTINCT ON (a.hex, a.anomaly_type)
                   a.hex, a.flight, a.anomaly_type, a.detected_at_ms,
                   a.lat, a.lon, a.alt_baro_ft, a.details
            FROM anomalies a
            WHERE a.detected_at_ms >= (
                (EXTRACT(EPOCH FROM NOW()) * 1000)::BIGINT - %s * 60 * 1000
            )
            ORDER BY a.hex, a.anomaly_type, a.detected_at_ms DESC
        ) latest
        WHERE NOT EXISTS (
            SELECT 1 FROM anomaly_notes n
            WHERE n.anomaly_hex   = latest.hex
              AND n.anomaly_type  = latest.anomaly_type
              AND n.anomaly_at_ms = latest.detected_at_ms
        )
        ORDER BY latest.detected_at_ms DESC
        LIMIT %s
    """
    with connect() as conn, conn.cursor() as cur:
        cur.execute(sql, (max_age_minutes, limit))
        cols = [d.name for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


def write_brief(window_start_ms: int, window_end_ms: int,
                text: str, provider: str) -> None:
    sql = """
        INSERT INTO briefs (window_start_ms, window_end_ms, text, provider)
        VALUES (%s, %s, %s, %s)
    """
    with connect() as conn, conn.cursor() as cur:
        cur.execute(sql, (window_start_ms, window_end_ms, text, provider))
        conn.commit()


def write_explanation(hex_: str, anomaly_type: str, anomaly_at_ms: int,
                      explanation: str, provider: str) -> None:
    sql = """
        INSERT INTO anomaly_notes
            (anomaly_hex, anomaly_type, anomaly_at_ms, explanation, provider)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (anomaly_hex, anomaly_type, anomaly_at_ms) DO NOTHING
    """
    with connect() as conn, conn.cursor() as cur:
        cur.execute(sql, (hex_, anomaly_type, anomaly_at_ms, explanation, provider))
        conn.commit()

def fetch_latest_anomaly_ms() -> int | None:
    with connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT MAX(detected_at_ms) FROM anomalies;")
        row = cur.fetchone()
    return row[0] if row and row[0] is not None else None

def fetch_unembedded_notes(limit: int = 500) -> list[dict]:
    """Notes whose (hex, type, timestamp) has no vector yet.

    Used by the embed DAG to backfill incrementally. The idempotent
    point_id means re-processing already-indexed notes is harmless —
    Qdrant overwrites rather than duplicating.
    """
    sql = """
        SELECT anomaly_hex AS hex, anomaly_type,
               anomaly_at_ms AS detected_at_ms, explanation
        FROM anomaly_notes
        ORDER BY generated_at DESC
        LIMIT %s
    """
    with connect() as conn, conn.cursor() as cur:
        cur.execute(sql, (limit,))
        cols = [d.name for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


def fetch_note_for_hex(hex_: str) -> dict | None:
    """The most recent explanation for an aircraft.

    Used by /similar as the query text — the reader wants "aircraft
    that behaved like this one", so the most recent behaviour is the
    right proxy.
    """
    sql = """
        SELECT anomaly_hex AS hex, anomaly_type,
               anomaly_at_ms AS detected_at_ms, explanation
        FROM anomaly_notes
        WHERE anomaly_hex = %s
        ORDER BY anomaly_at_ms DESC
        LIMIT 1
    """
    with connect() as conn, conn.cursor() as cur:
        cur.execute(sql, (hex_,))
        row = cur.fetchone()
        if not row:
            return None
        cols = [d.name for d in cur.description]
        return dict(zip(cols, row))
def fetch_latest_anomaly_for_hex(hex_: str) -> dict | None:
    sql = """
        SELECT hex, flight, anomaly_type, detected_at_ms,
               lat, lon, alt_baro_ft, details,
               severity, phase, rate_fpm, turn_rate_dps
        FROM anomalies
        WHERE hex = %s
        ORDER BY detected_at_ms DESC
        LIMIT 1
    """
    with connect() as conn, conn.cursor() as cur:
        cur.execute(sql, (hex_,))
        row = cur.fetchone()
        if not row:
            return None
        cols = [d.name for d in cur.description]
        return dict(zip(cols, row))


def fetch_similar_candidates(
    exclude_hex: str,
    anomaly_type: str,
    lookback_days: int = 7,
    limit: int = 200,
) -> list[dict]:
    sql = """
        SELECT hex, flight, anomaly_type, detected_at_ms,
               lat, lon, alt_baro_ft, details,
               severity, phase, rate_fpm, turn_rate_dps
        FROM anomalies
        WHERE hex <> %s
          AND anomaly_type = %s
          AND detected_at_ms >= (
              (EXTRACT(EPOCH FROM NOW()) * 1000)::BIGINT - (%s::BIGINT * 86400 * 1000)
          )
        ORDER BY detected_at_ms DESC
        LIMIT %s
    """
    with connect() as conn, conn.cursor() as cur:
        cur.execute(sql, (exclude_hex, anomaly_type, lookback_days, limit))
        cols = [d.name for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


def fetch_prior_hex_anomalies(
    hex_: str,
    before_ms: int,
    anomaly_type: str,
    limit: int = 10,
) -> list[dict]:
    sql = """
        SELECT hex, flight, anomaly_type, detected_at_ms,
               lat, lon, alt_baro_ft, details,
               severity, phase, rate_fpm, turn_rate_dps
        FROM anomalies
        WHERE hex = %s
          AND anomaly_type = %s
          AND detected_at_ms < %s
        ORDER BY detected_at_ms DESC
        LIMIT %s
    """
    with connect() as conn, conn.cursor() as cur:
        cur.execute(sql, (hex_, anomaly_type, before_ms, limit))
        cols = [d.name for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


def count_regime_recurrence(
    anomaly_type: str,
    phase: str | None,
    window_hours: int = 24,
) -> int:
    sql = """
        SELECT COUNT(*)
        FROM anomalies
        WHERE anomaly_type = %s
          AND (%s::TEXT IS NULL OR phase = %s)
          AND detected_at_ms >= (
              (EXTRACT(EPOCH FROM NOW()) * 1000)::BIGINT - (%s::BIGINT * 3600 * 1000)
          )
    """
    with connect() as conn, conn.cursor() as cur:
        cur.execute(sql, (anomaly_type, phase, phase, window_hours))
        row = cur.fetchone()
    return int(row[0]) if row and row[0] is not None else 0
def fetch_anomalies_for_vectors(hours: int = 2, limit: int = 2000) -> list[dict]:
    sql = """
        SELECT hex, flight, anomaly_type, phase, detected_at_ms,
               alt_baro_ft, rate_fpm, turn_rate_dps
        FROM anomalies
        WHERE detected_at_ms >= (
            (EXTRACT(EPOCH FROM NOW()) * 1000)::BIGINT - (%s::BIGINT * 3600 * 1000)
        )
        ORDER BY detected_at_ms DESC
        LIMIT %s
    """
    with connect() as conn, conn.cursor() as cur:
        cur.execute(sql, (hours, limit))
        cols = [d.name for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]
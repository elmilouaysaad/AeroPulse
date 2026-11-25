"""Backfill severity/rate_fpm/turn_rate_dps for pre-Phase-1 anomalies.
Idempotent — safe to re-run. Matches the Phase 1 logic in detection.py.
"""
from __future__ import annotations

import os
import re
import sys

import psycopg


RATE_RE = re.compile(r"(-?\d+(?:\.\d+)?) ft/min")
ROT_RE = re.compile(r"rotated (-?\d+(?:\.\d+)?)°")


def _severity(atype: str, alt: float | None, rate: float | None) -> str:
    if atype in ("squawk_7500", "squawk_7700"):
        return "EMERGENCY"
    if atype == "squawk_7600":
        return "ADVISORY"
    if atype == "rapid_descent" and rate is not None:
        return "EMERGENCY" if rate >= 7000 else "ADVISORY"
    if atype == "holding_pattern" and alt is not None and alt >= 15_000:
        return "ADVISORY"
    return "INFO"


def main() -> int:
    dsn = os.getenv(
        "POSTGRES_DSN",
        "postgresql://aeropulse:aeropulse@postgres:5432/aeropulse",
    )
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT hex, anomaly_type, detected_at_ms, alt_baro_ft, details
            FROM anomalies
            WHERE rate_fpm IS NULL AND turn_rate_dps IS NULL
        """)
        rows = cur.fetchall()
        print(f"backfilling {len(rows)} rows")
        for hex_, atype, ts, alt, details in rows:
            rate = turn = None
            if details:
                m = RATE_RE.search(details)
                if m:
                    rate = float(m.group(1))
                m = ROT_RE.search(details)
                if m:
                    turn = abs(float(m.group(1)))
            sev = _severity(atype, alt, rate)
            cur.execute("""
                UPDATE anomalies
                SET severity = %s,
                    rate_fpm = COALESCE(%s, rate_fpm),
                    turn_rate_dps = COALESCE(%s, turn_rate_dps)
                WHERE hex = %s AND anomaly_type = %s AND detected_at_ms = %s
            """, (sev, rate, turn, hex_, atype, ts))
        conn.commit()
        print("done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
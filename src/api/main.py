"""FastAPI serving layer. Read-only: never writes, never calls the LLM."""
from __future__ import annotations

import time
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException
from prometheus_fastapi_instrumentator import Instrumentator

from src.ai import db as ai_db
from src.ai import kinematic_vectors as kin_vec
from src.api import cache, db
from src.api.schemas import AircraftPoint, Anomaly, Brief, Stats
import os
import urllib.request
from fastapi import status
import psycopg
import redis as redis_lib

app = FastAPI(title="AeroPulse API", version="0.6.0")



def _check_postgres() -> dict:
    dsn = os.getenv("POSTGRES_DSN") or (
        f"postgresql://{os.getenv('POSTGRES_USER', 'aeropulse')}:{os.getenv('POSTGRES_PASSWORD', 'aeropulse')}"
        f"@{os.getenv('POSTGRES_HOST', 'postgres')}:{os.getenv('POSTGRES_PORT', '5432')}/{os.getenv('POSTGRES_DB', 'aeropulse')}"
    )
    with psycopg.connect(dsn, connect_timeout=2) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
            cur.fetchone()
    return {"ok": True, "detail": "ok"}


def _check_redis() -> dict:
    redis_url = os.getenv("REDIS_URL")
    if redis_url:
        client = redis_lib.Redis.from_url(
            redis_url,
            socket_connect_timeout=2,
            socket_timeout=2,
        )
    else:
        client = redis_lib.Redis(
            host=os.getenv("REDIS_HOST", "redis"),
            port=int(os.getenv("REDIS_PORT", "6379")),
            username=os.getenv("REDIS_USERNAME") or None,
            password=os.getenv("REDIS_PASSWORD") or None,
            socket_connect_timeout=2,
            socket_timeout=2,
        )
    if not client.ping():
        raise RuntimeError("redis ping failed")
    return {"ok": True, "detail": "ok"}


def _check_qdrant() -> dict:
    url = os.getenv("QDRANT_URL", "http://qdrant:6333").rstrip("/") + "/readyz"
    with urllib.request.urlopen(url, timeout=2) as resp:
        if resp.status >= 400:
            raise RuntimeError(f"qdrant status {resp.status}")
    return {"ok": True, "detail": "ok"}


@app.get("/ready")
def ready() -> dict:
    checks: dict[str, dict] = {}
    all_ok = True
    for name, fn in (
        ("postgres", _check_postgres),
        ("redis", _check_redis),
        ("qdrant", _check_qdrant),
    ):
        try:
            checks[name] = fn()
        except Exception as exc:
            all_ok = False
            checks[name] = {"ok": False, "detail": str(exc)}

    payload = {
        "status": "ready" if all_ok else "not_ready",
        "ts": datetime.now(timezone.utc).isoformat(),
        "checks": checks,
    }
    if not all_ok:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=payload)
    return payload
@app.get("/similar")
def similar(hex_: str, limit: int = 5) -> dict:
    target = ai_db.fetch_latest_anomaly_for_hex(hex_)
    if not target:
        raise HTTPException(
            status_code=404,
            detail=f"No anomaly found for hex={hex_}",
        )

    matches = kin_vec.search_similar_kinematics(
        target=target,
        exclude_hex=hex_,
        limit=limit,
    )

    prior_occurrences = ai_db.fetch_prior_hex_anomalies(
        hex_=hex_,
        before_ms=target["detected_at_ms"],
        anomaly_type=target["anomaly_type"],
        limit=limit,
    )
    regime_24h = ai_db.count_regime_recurrence(
        anomaly_type=target["anomaly_type"],
        phase=target.get("phase"),
        window_hours=24,
    )

    return {
        "query_hex": hex_,
        "reference_anomaly": target,
        "similar_aircraft": matches,
        "prior_occurrences": prior_occurrences,
        "recurrence_summary": {
            "hex_prior_count": len(prior_occurrences),
            "regime_count_24h": regime_24h,
            "anomaly_type": target["anomaly_type"],
            "phase": target.get("phase"),
        },
    }


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "ts": datetime.now(timezone.utc).isoformat()}


@app.get("/airspace/brief", response_model=Brief)
def airspace_brief() -> Brief:
    # Prefer the Redis cache — the DAG refreshes it every 15 minutes
    cached = cache.cached_brief()
    if cached:
        return Brief(**cached, stale=False)

    # Fallback: last persisted brief, marked stale so the UI can warn
    row = db.latest_brief()
    if row:
        return Brief(**row, stale=True)

    raise HTTPException(status_code=503, detail="No brief available yet")


@app.get("/anomalies", response_model=list[Anomaly])
def anomalies(since_minutes: int = 60, limit: int = 100) -> list[Anomaly]:
    since_ms = int(time.time() * 1000) - since_minutes * 60 * 1000
    rows = db.recent_anomalies(since_ms, limit)
    return [Anomaly(**r) for r in rows]


@app.get("/aircraft/{hex_}/track", response_model=list[AircraftPoint])
def aircraft_track(hex_: str, limit: int = 200) -> list[AircraftPoint]:
    rows = db.aircraft_track(hex_, limit)
    if not rows:
        raise HTTPException(status_code=404, detail=f"No track for hex={hex_}")
    return [AircraftPoint(**r) for r in rows]


@app.get("/stats", response_model=Stats)
def stats(window_minutes: int = 60) -> Stats:
    since_ms = int(time.time() * 1000) - window_minutes * 60 * 1000
    s = db.stats(since_ms)
    return Stats(
        total_anomalies=s["total"],
        window_minutes=window_minutes,
        by_type=s["by_type"],
    )


Instrumentator().instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)
"""FastAPI serving layer. Read-only: never writes, never calls the LLM."""
from __future__ import annotations

import time
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException

from src.ai import db as ai_db, similarity as sim_mod
from src.api import cache, db
from src.api.schemas import AircraftPoint, Anomaly, Brief, Stats

app = FastAPI(title="AeroPulse API", version="0.6.0")


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "ts": datetime.now(timezone.utc).isoformat()}


@app.get("/airspace/brief", response_model=Brief)
def airspace_brief() -> Brief:
    cached = cache.cached_brief()
    if cached:
        return Brief(**cached, stale=False)
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




@app.get("/similar")
@app.get("/similar")
def similar(hex_: str, limit: int = 5) -> dict:
    """Blended kinematic + text similarity across aircraft, plus recurrence info."""
    target = ai_db.fetch_latest_anomaly_for_hex(hex_)
    if not target:
        raise HTTPException(
            status_code=404,
            detail=f"No anomaly found for hex={hex_}",
        )

    candidates = ai_db.fetch_similar_candidates(
        exclude_hex=hex_,
        anomaly_type=target["anomaly_type"],
    )

    note = ai_db.fetch_note_for_hex(hex_)
    qdrant_matches: list[dict] = []

    similar_aircraft = sim_mod.rank_blended_anomalies(
        target=target,
        candidates=candidates,
        qdrant_matches=qdrant_matches,
        kinematic_weight=0.75,
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
        "query_explanation": note["explanation"] if note else None,
        "reference_anomaly": target,
        "similar_aircraft": similar_aircraft,
        "prior_occurrences": prior_occurrences,
        "recurrence_summary": {
            "hex_prior_count": len(prior_occurrences),
            "regime_count_24h": regime_24h,
            "anomaly_type": target["anomaly_type"],
            "phase": target.get("phase"),
        },
    }
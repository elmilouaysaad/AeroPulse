from __future__ import annotations

import math
import os
import uuid
from typing import Any, Optional

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchValue,
    PointStruct,
    VectorParams,
)

from src.ai.similarity import MAX_ALT_FT, MAX_RATE_FPM, MAX_TURN_DPS, _norm_or_none

COLLECTION = "kinematic_anomalies"
VECTOR_SIZE = 4
POINT_NAMESPACE = uuid.UUID("9b1c4e2a-6f3d-4a8e-b2c1-5d7e8f9a0b1c")

PHASE_MAP = {
    "climb": 0.25,
    "cruise": 0.50,
    "descent": 0.75,
    "approach": 1.0,
}

def sync_recent_anomalies(hours: int = 2, limit: int = 2000) -> dict:
    from src.ai import db

    rows = db.fetch_anomalies_for_vectors(hours=hours, limit=limit)
    upserted = upsert_anomalies(rows)
    return {"fetched": len(rows), "upserted": upserted}

def _client() -> QdrantClient:
    return QdrantClient(
        url=os.getenv("QDRANT_URL", "http://qdrant:6333"),
        api_key=os.getenv("QDRANT_API_KEY"),
        timeout=10,
    )


def build_kinematic_vector(row: dict[str, Any]) -> list[float]:
    alt = _norm_or_none(row.get("alt_baro_ft"), MAX_ALT_FT, MAX_ALT_FT) or 0.0
    rate = _norm_or_none(row.get("rate_fpm"), MAX_RATE_FPM, MAX_RATE_FPM) or 0.0
    turn = _norm_or_none(row.get("turn_rate_dps"), MAX_TURN_DPS, MAX_TURN_DPS) or 0.0
    phase = PHASE_MAP.get((row.get("phase") or "").lower(), 0.0)
    return [alt, rate, turn, phase]


def point_id(hex_: str, anomaly_type: str, detected_at_ms: int) -> str:
    return str(uuid.uuid5(POINT_NAMESPACE, f"{hex_}:{anomaly_type}:{detected_at_ms}"))


def ensure_collection() -> None:
    c = _client()
    if not c.collection_exists(collection_name=COLLECTION):
        c.create_collection(
            collection_name=COLLECTION,
            vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.EUCLID),
        )


def upsert_anomalies(rows: list[dict[str, Any]]) -> int:
    if not rows:
        return 0
    ensure_collection()
    points = [
        PointStruct(
            id=point_id(r["hex"], r["anomaly_type"], int(r["detected_at_ms"])),
            vector=build_kinematic_vector(r),
            payload={
                "hex": r["hex"],
                "flight": r.get("flight"),
                "anomaly_type": r["anomaly_type"],
                "phase": r.get("phase"),
                "detected_at_ms": int(r["detected_at_ms"]),
                "alt_baro_ft": r.get("alt_baro_ft"),
                "rate_fpm": r.get("rate_fpm"),
                "turn_rate_dps": r.get("turn_rate_dps"),
            },
        )
        for r in rows
    ]
    _client().upsert(collection_name=COLLECTION, points=points)
    return len(points)


def search_similar_kinematics(
    target: dict[str, Any],
    exclude_hex: Optional[str] = None,
    limit: int = 5,
) -> list[dict[str, Any]]:
    ensure_collection()
    query_vec = build_kinematic_vector(target)
    atype = target.get("anomaly_type")

    query_filter = (
        Filter(must=[FieldCondition(key="anomaly_type", match=MatchValue(value=atype))])
        if atype
        else None
    )

    resp = _client().query_points(
        collection_name=COLLECTION,
        query=query_vec,
        query_filter=query_filter,
        limit=limit + 10 if exclude_hex else limit,
        with_payload=True,
    )

    # Convert Euclidean distance in 4D unit cube (max dist = sqrt(4) = 2.0) to [0, 1] similarity
    max_dist = math.sqrt(VECTOR_SIZE)
    out: list[dict[str, Any]] = []
    for pt in resp.points:
        p = pt.payload or {}
        if exclude_hex and p.get("hex") == exclude_hex:
            continue
        dist = float(pt.score)
        sim = round(max(0.0, 1.0 - min(1.0, dist / max_dist)), 4)
        out.append({
            **p,
            "vector_distance": round(dist, 4),
            "similarity_score": sim,
        })
        if len(out) >= limit:
            break
    return out
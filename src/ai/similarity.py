"""Kinematic similarity, text-score alignment, and ranking helpers."""
from __future__ import annotations

import math
from typing import Any, Optional

MAX_ALT_FT = 25_000.0
MAX_RATE_FPM = 4_500.0
MAX_TURN_DPS = 8.0
PHASE_MATCH_WEIGHT = 0.05
BASE_KINEMATIC_WEIGHT = 1.0 - PHASE_MATCH_WEIGHT


def _norm_or_none(
    val: Optional[float],
    scale: float,
    cap: Optional[float] = None,
) -> Optional[float]:
    if val is None:
        return None
    try:
        x = float(val)
    except (TypeError, ValueError):
        return None
    if math.isnan(x) or math.isinf(x) or scale <= 0:
        return None
    x = max(0.0, x)
    if cap is not None:
        x = min(x, cap)
    return min(1.0, x / scale)


def _feature_vector(row: dict[str, Any]) -> list[float]:
    """Build a bounded physical feature vector based on anomaly_type."""
    atype = row.get("anomaly_type") or ""
    alt = _norm_or_none(row.get("alt_baro_ft"), MAX_ALT_FT, MAX_ALT_FT) or 0.0

    if atype == "rapid_descent":
        rate = _norm_or_none(row.get("rate_fpm"), MAX_RATE_FPM, MAX_RATE_FPM) or 0.0
        return [alt, rate]

    if atype == "holding_pattern":
        turn = _norm_or_none(row.get("turn_rate_dps"), MAX_TURN_DPS, MAX_TURN_DPS) or 0.0
        return [alt, turn]

    return [alt]


def kinematic_similarity(target: dict[str, Any], candidate: dict[str, Any]) -> float:
    """Return a similarity score in [0.0, 1.0] based on flight regime and kinematics."""
    t_type = target.get("anomaly_type")
    c_type = candidate.get("anomaly_type")
    if t_type and c_type and t_type != c_type:
        return 0.0

    v1 = _feature_vector(target)
    v2 = _feature_vector(candidate)
    dims = max(1, len(v1))
    max_dist = math.sqrt(dims)

    sq_sum = sum((a - b) ** 2 for a, b in zip(v1, v2))
    norm_dist = min(1.0, math.sqrt(sq_sum) / max_dist)

    base_closeness = max(0.0, 1.0 - norm_dist)
    phase_match = 1.0 if (target.get("phase") and target.get("phase") == candidate.get("phase")) else 0.0
    score = base_closeness * (BASE_KINEMATIC_WEIGHT + PHASE_MATCH_WEIGHT * phase_match)

    return round(min(1.0, max(0.0, score)), 4)


def _extract_qdrant_fields(match: dict[str, Any]) -> tuple[Any, Any, Any, Optional[float]]:
    """Extract (hex, anomaly_type, detected_at_ms, score) across top-level or payload dicts."""
    payload = match.get("payload") if isinstance(match.get("payload"), dict) else {}

    hex_val = (
        match.get("hex")
        or match.get("aircraft_hex")
        or payload.get("hex")
        or payload.get("aircraft_hex")
    )
    atype_val = (
        match.get("anomaly_type")
        or match.get("type")
        or payload.get("anomaly_type")
        or payload.get("type")
    )
    ts_val = (
        match.get("detected_at_ms")
        if match.get("detected_at_ms") is not None
        else match.get("ts_ms")
        if match.get("ts_ms") is not None
        else payload.get("detected_at_ms")
        if payload.get("detected_at_ms") is not None
        else payload.get("ts_ms")
    )

    raw_score = match.get("score")
    if raw_score is None:
        raw_score = match.get("similarity")
    try:
        score_val = float(raw_score) if raw_score is not None else None
        if score_val is not None and (math.isnan(score_val) or math.isinf(score_val)):
            score_val = None
    except (TypeError, ValueError):
        score_val = None

    return hex_val, atype_val, ts_val, score_val


def _build_text_score_maps(
    qdrant_matches: list[dict[str, Any]] | None,
) -> tuple[
    dict[tuple[Any, Any, Any], float],
    dict[tuple[Any, Any], float],
    dict[Any, float],
]:
    exact_scores: dict[tuple[Any, Any, Any], float] = {}
    regime_hex_scores: dict[tuple[Any, Any], float] = {}
    hex_scores: dict[Any, float] = {}

    for m in qdrant_matches or []:
        if not isinstance(m, dict):
            continue
        hex_val, atype_val, ts_val, score_val = _extract_qdrant_fields(m)
        if score_val is None or hex_val is None:
            continue

        if ts_val is not None:
            try:
                exact_key = (hex_val, atype_val, int(ts_val))
                if exact_key not in exact_scores or score_val > exact_scores[exact_key]:
                    exact_scores[exact_key] = score_val
            except (TypeError, ValueError):
                pass

        if atype_val is not None:
            pair_key = (hex_val, atype_val)
            if pair_key not in regime_hex_scores or score_val > regime_hex_scores[pair_key]:
                regime_hex_scores[pair_key] = score_val

        if hex_val not in hex_scores or score_val > hex_scores[hex_val]:
            hex_scores[hex_val] = score_val

    return exact_scores, regime_hex_scores, hex_scores


def rank_blended_anomalies(
    target: dict[str, Any],
    candidates: list[dict[str, Any]],
    qdrant_matches: list[dict[str, Any]] | None = None,
    kinematic_weight: float = 0.75,
    limit: int = 5,
    dedupe_by_hex: bool = True,
) -> list[dict[str, Any]]:
    """Rank candidates by blended kinematic + text similarity, deduplicated by hex."""
    text_weight = max(0.0, 1.0 - kinematic_weight)
    exact_scores, regime_hex_scores, hex_scores = _build_text_score_maps(qdrant_matches)

    scored: list[dict[str, Any]] = []
    for c in candidates:
        item = dict(c)
        kin_score = kinematic_similarity(target, item)

        hex_val = item.get("hex")
        atype_val = item.get("anomaly_type")
        ts_val = item.get("detected_at_ms")

        txt_score: Optional[float] = None
        if ts_val is not None:
            try:
                txt_score = exact_scores.get((hex_val, atype_val, int(ts_val)))
            except (TypeError, ValueError):
                txt_score = None
        if txt_score is None and atype_val is not None:
            txt_score = regime_hex_scores.get((hex_val, atype_val))
        if txt_score is None:
            txt_score = hex_scores.get(hex_val)

        item["kinematic_score"] = kin_score
        item["text_score"] = round(txt_score, 4) if txt_score is not None else None
        if txt_score is not None:
            blended = kinematic_weight * kin_score + text_weight * txt_score
            item["similarity_score"] = round(min(1.0, max(0.0, blended)), 4)
        else:
            item["similarity_score"] = kin_score

        scored.append(item)

    scored.sort(
        key=lambda r: (
            r["similarity_score"],
            r["kinematic_score"],
            r.get("detected_at_ms") or 0,
        ),
        reverse=True,
    )

    if not dedupe_by_hex:
        return scored[:limit]

    deduped: list[dict[str, Any]] = []
    seen_hexes: set[Any] = set()
    for row in scored:
        h = row.get("hex")
        if h is not None and h in seen_hexes:
            continue
        if h is not None:
            seen_hexes.add(h)
        deduped.append(row)
        if len(deduped) >= limit:
            break

    return deduped
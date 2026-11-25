"""Unit tests for kinematic similarity and blended candidate ranking."""
from __future__ import annotations

import pytest

from src.ai.similarity import (
    MAX_ALT_FT,
    MAX_RATE_FPM,
    MAX_TURN_DPS,
    _norm_or_none,
    kinematic_similarity,
    rank_blended_anomalies,
)


def test_norm_or_none_bounds_and_invalid_inputs():
    assert _norm_or_none(0.0, MAX_ALT_FT, MAX_ALT_FT) == 0.0
    assert _norm_or_none(MAX_ALT_FT / 2, MAX_ALT_FT, MAX_ALT_FT) == pytest.approx(0.5)
    assert _norm_or_none(MAX_ALT_FT * 2, MAX_ALT_FT, MAX_ALT_FT) == 1.0
    assert _norm_or_none(-500.0, MAX_ALT_FT, MAX_ALT_FT) == 0.0
    assert _norm_or_none(None, MAX_ALT_FT, MAX_ALT_FT) is None
    assert _norm_or_none("bad", MAX_ALT_FT, MAX_ALT_FT) is None
    assert _norm_or_none(float("nan"), MAX_ALT_FT, MAX_ALT_FT) is None
    assert _norm_or_none(100.0, 0.0) is None


def test_kinematic_similarity_identical_and_phase_bonus():
    target = {
        "anomaly_type": "rapid_descent",
        "alt_baro_ft": 12_500.0,
        "rate_fpm": 2_250.0,
        "phase": "approach",
    }
    same_phase = dict(target)
    other_phase = {**target, "phase": "enroute"}

    assert kinematic_similarity(target, same_phase) == 1.0
    assert kinematic_similarity(target, other_phase) == 0.95


def test_kinematic_similarity_regime_and_feature_differences():
    descent = {
        "anomaly_type": "rapid_descent",
        "alt_baro_ft": 15_000.0,
        "rate_fpm": 3_000.0,
    }
    holding = {
        "anomaly_type": "holding_pattern",
        "alt_baro_ft": 15_000.0,
        "turn_rate_dps": 4.0,
    }
    assert kinematic_similarity(descent, holding) == 0.0

    hold_a = {
        "anomaly_type": "holding_pattern",
        "alt_baro_ft": 10_000.0,
        "turn_rate_dps": 2.0,
    }
    hold_b = {
        "anomaly_type": "holding_pattern",
        "alt_baro_ft": 10_000.0,
        "turn_rate_dps": MAX_TURN_DPS,
    }
    score_ab = kinematic_similarity(hold_a, hold_b)
    assert 0.0 < score_ab < 1.0


def test_rank_blended_anomalies_text_alignment_and_dedupe():
    target = {
        "hex": "484001",
        "anomaly_type": "rapid_descent",
        "alt_baro_ft": 10_000.0,
        "rate_fpm": 2_000.0,
        "phase": "descent",
    }
    candidates = [
        {
            "hex": "484002",
            "anomaly_type": "rapid_descent",
            "alt_baro_ft": 10_000.0,
            "rate_fpm": 2_000.0,
            "phase": "descent",
            "detected_at_ms": 2000,
        },
        {
            "hex": "484002",
            "anomaly_type": "rapid_descent",
            "alt_baro_ft": 2_000.0,
            "rate_fpm": MAX_RATE_FPM,
            "phase": "descent",
            "detected_at_ms": 1000,
        },
        {
            "hex": "484003",
            "anomaly_type": "rapid_descent",
            "alt_baro_ft": 10_500.0,
            "rate_fpm": 2_100.0,
            "phase": "descent",
            "detected_at_ms": 1500,
        },
    ]
    qdrant_matches = [
        {
            "payload": {
                "hex": "484002",
                "anomaly_type": "rapid_descent",
                "detected_at_ms": 2000,
            },
            "score": 0.80,
        },
        {
            "hex": "484003",
            "anomaly_type": "rapid_descent",
            "score": 0.90,
        },
    ]

    ranked = rank_blended_anomalies(
        target=target,
        candidates=candidates,
        qdrant_matches=qdrant_matches,
        kinematic_weight=0.75,
        limit=5,
        dedupe_by_hex=True,
    )

    assert [r["hex"] for r in ranked] == ["484003", "484002"]
    assert ranked[0]["text_score"] == 0.9
    assert ranked[0]["similarity_score"] == pytest.approx(0.9592)
    assert ranked[1]["kinematic_score"] == 1.0
    assert ranked[1]["text_score"] == 0.8
    assert ranked[1]["similarity_score"] == pytest.approx(0.95)

"""Unit tests for the API. Postgres and Redis are mocked."""
from unittest.mock import patch

# import pytest
from fastapi.testclient import TestClient

from src.api.main import app

client = TestClient(app)


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"




def test_brief_falls_back_to_db_and_marks_stale():
    with patch("src.api.cache.cached_brief", return_value=None), \
         patch("src.api.db.latest_brief", return_value={
             "text": "db brief",
             "provider": "pollinations",
             "generated_at": "2026-11-14T00:00:00+00:00",
         }):
        r = client.get("/airspace/brief")
    assert r.status_code == 200
    body = r.json()
    assert body["text"] == "db brief"
    assert body["stale"] is True


def test_brief_returns_503_when_no_source_available():
    with patch("src.api.cache.cached_brief", return_value=None), \
         patch("src.api.db.latest_brief", return_value=None):
        r = client.get("/airspace/brief")
    assert r.status_code == 503


def test_anomalies_empty():
    with patch("src.api.db.recent_anomalies", return_value=[]):
        r = client.get("/anomalies")
    assert r.status_code == 200
    assert r.json() == []





def test_aircraft_track_404_for_unknown_hex():
    with patch("src.api.db.aircraft_track", return_value=[]):
        r = client.get("/aircraft/does-not-exist/track")
    assert r.status_code == 404


def test_aircraft_track_returns_points():
    with patch("src.api.db.aircraft_track", return_value=[
        {"detected_at_ms": 1, "lat": 40.0, "lon": -74.0,
         "alt_baro_ft": 10000.0, "anomaly_type": "rapid_descent"},
    ]):
        r = client.get("/aircraft/abc123/track")
    assert r.status_code == 200
    assert len(r.json()) == 1


def test_stats_aggregates_by_type():
    with patch("src.api.db.stats", return_value={
        "total": 5,
        "by_type": {"rapid_descent": 3, "holding_pattern": 2},
    }):
        r = client.get("/stats?window_minutes=60")
    assert r.status_code == 200
    body = r.json()
    assert body["total_anomalies"] == 5
    assert body["window_minutes"] == 60
    assert body["by_type"]["rapid_descent"] == 3

def test_similar_returns_404_for_unknown_hex():
    with patch("src.ai.db.fetch_latest_anomaly_for_hex", return_value=None):
        r = client.get("/similar?hex_=unknown")
    assert r.status_code == 404


def test_similar_returns_matches():
    target = {
        "hex": "abc",
        "anomaly_type": "rapid_descent",
        "detected_at_ms": 1,
        "alt_baro_ft": 10000.0,
        "rate_fpm": 2000.0,
        "phase": "descent",
    }
    kinematic_match = {
        "hex": "xyz",
        "flight": "TEST123",
        "anomaly_type": "rapid_descent",
        "phase": "descent",
        "detected_at_ms": 2,
        "alt_baro_ft": 10000.0,
        "rate_fpm": 2000.0,
        "turn_rate_dps": None,
        "vector_distance": 0.0,
        "similarity_score": 1.0,
    }
    with patch("src.ai.db.fetch_latest_anomaly_for_hex", return_value=target), \
         patch("src.ai.kinematic_vectors.search_similar_kinematics", return_value=[kinematic_match]), \
         patch("src.ai.db.fetch_prior_hex_anomalies", return_value=[]), \
         patch("src.ai.db.count_regime_recurrence", return_value=1):
        r = client.get("/similar?hex_=abc&limit=5")
    assert r.status_code == 200
    body = r.json()
    assert body["query_hex"] == "abc"
    assert body["similar_aircraft"][0]["hex"] == "xyz"
    assert body["similar_aircraft"][0]["similarity_score"] == 1.0
    assert body["recurrence_summary"]["regime_count_24h"] == 1
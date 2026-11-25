from src.ingestion.parser import parse_altitude, parse_record, parse_response


def test_altitude_numeric():
    assert parse_altitude(36000) == (36000.0, False)


def test_altitude_ground_string():
    assert parse_altitude("ground") == (0.0, True)


def test_altitude_missing():
    assert parse_altitude(None) == (None, False)


def test_ground_record_is_kept_not_dropped():
    raw = {
        "hex": "abc123", "flight": "BAW117 ", "lat": 51.47, "lon": -0.45,
        "alt_baro": "ground", "gs": 12, "track": 90, "squawk": "7700",
        "seen": 2.1, "seen_pos": 2.1,
    }
    v = parse_record(raw)
    assert v is not None
    assert v.on_ground is True
    assert v.alt_baro_ft == 0.0
    assert v.squawk == "7700"
    assert v.flight == "BAW117"


def test_stale_record_dropped():
    raw = {"hex": "abc123", "lat": 51.47, "lon": -0.45, "seen": 120, "alt_baro": 30000}
    assert parse_record(raw) is None


def test_missing_position_dropped():
    raw = {"hex": "abc123", "seen": 2, "alt_baro": 30000}
    assert parse_record(raw) is None


def test_parse_response_filters_and_keeps():
    payload = {
        "ac": [
            {"hex": "a", "lat": 1.0, "lon": 2.0, "seen": 1, "alt_baro": 10000},
            {"hex": "b", "seen": 200, "lat": 1.0, "lon": 2.0},
            {"hex": "c", "lat": 3.0, "lon": 4.0, "seen": 1, "alt_baro": "ground"},
        ]
    }
    vectors = parse_response(payload)
    assert {v.hex for v in vectors} == {"a", "c"}
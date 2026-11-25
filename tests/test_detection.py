"""Unit tests for src.streaming.detection — no Spark, no I/O."""
from src.streaming.detection import (
    Position, detect_squawk, detect_rapid_descent, detect_holding,
)


def pos(alt, track, t_ms, lat=40.0, lon=-74.0, gs=None):
    return Position(
        lat=lat, lon=lon, alt_ft=alt, track_deg=track,
        event_time_ms=t_ms, gs_kts=gs,
    )


# ---------- squawk ----------

def test_squawk_general_emergency_fires():
    a = detect_squawk("abc", "DAL1", "7700", 40.0, -74.0, 30000.0, 1000, None)
    assert a is not None
    assert a.anomaly_type == "squawk_7700"
    assert "emergency" in a.details.lower()


def test_squawk_radio_failure_fires():
    a = detect_squawk("abc", "DAL1", "7600", 40.0, -74.0, 30000.0, 1000, None)
    assert a is not None
    assert a.anomaly_type == "squawk_7600"


def test_squawk_hijack_fires():
    a = detect_squawk("abc", "DAL1", "7500", 40.0, -74.0, 30000.0, 1000, None)
    assert a is not None
    assert a.anomaly_type == "squawk_7500"


def test_squawk_does_not_refire_on_same_code():
    a = detect_squawk("abc", "DAL1", "7700", 40.0, -74.0, 30000.0, 1000, "7700")
    assert a is None


def test_squawk_ignores_normal_codes():
    assert detect_squawk("abc", "DAL1", "1200", 40.0, -74.0, 30000.0, 1000, None) is None


def test_squawk_ignores_none():
    assert detect_squawk("abc", "DAL1", None, 40.0, -74.0, 30000.0, 1000, None) is None


# ---------- rapid descent ----------

def test_rapid_descent_fires():
    """4,000 fpm sustained for 75s at cruise altitude."""
    positions = [pos(30000 - i * 1000, 90, i * 15_000) for i in range(6)]
    a = detect_rapid_descent("abc", "DAL1", positions)
    assert a is not None
    assert a.anomaly_type == "rapid_descent"
    assert a.rate_fpm is not None and a.rate_fpm > 3900


def test_rapid_descent_does_not_fire_on_gentle_descent():
    positions = [pos(30000, 90, 0), pos(29500, 90, 60_000), pos(29000, 90, 120_000)]
    assert detect_rapid_descent("abc", "DAL1", positions) is None


def test_rapid_descent_does_not_fire_on_climb():
    positions = [pos(20000, 90, 0), pos(24000, 90, 30_000), pos(28000, 90, 60_000)]
    assert detect_rapid_descent("abc", "DAL1", positions) is None


def test_rapid_descent_needs_enough_samples():
    positions = [pos(30000, 90, 0), pos(24000, 90, 30_000)]
    assert detect_rapid_descent("abc", "DAL1", positions) is None


def test_rapid_descent_ignores_ground_altitudes():
    positions = [pos(1000, 90, 0), pos(0, 90, 30_000), pos(0, 90, 60_000)]
    assert detect_rapid_descent("abc", "DAL1", positions) is None


# ---------- holding ----------

def test_holding_fires_on_full_circle():
    positions = [pos(5000, (i * 60) % 360, i * 10_000) for i in range(6)]
    a = detect_holding("abc", "DAL1", positions)
    assert a is not None
    assert a.anomaly_type == "holding_pattern"


def test_holding_does_not_fire_on_straight_flight():
    positions = [pos(5000, 90, i * 10_000) for i in range(6)]
    assert detect_holding("abc", "DAL1", positions) is None


def test_holding_does_not_fire_when_climbing():
    tracks = [(i * 60) % 360 for i in range(6)]
    positions = [pos(5000 + i * 1000, tracks[i], i * 10_000) for i in range(6)]
    assert detect_holding("abc", "DAL1", positions) is None


def test_holding_needs_enough_samples():
    positions = [pos(5000, (i * 60) % 360, i * 10_000) for i in range(4)]
    assert detect_holding("abc", "DAL1", positions) is None


def test_holding_handles_360_degree_wrap():
    """Heading 350 -> 10 should count as +20 degrees, not -340."""
    tracks = [350, 10, 30, 50, 70, 90]   # +100 degrees total, not enough
    positions = [pos(5000, t, i * 10_000) for i, t in enumerate(tracks)]
    assert detect_holding("abc", "DAL1", positions) is None

# -----------------------------------------------------

def test_holding_ignores_ground_aircraft():
    """Aircraft taxiing on the tarmac must not fire holding_pattern."""
    positions = [pos(0.0, (i * 60) % 360, i * 10_000) for i in range(6)]
    assert detect_holding("abc", "DAL1", positions) is None


def test_holding_ignores_nan_altitudes():
    positions = [pos(float("nan"), (i * 60) % 360, i * 10_000) for i in range(6)]
    assert detect_holding("abc", "DAL1", positions) is None


def test_holding_ignores_nan_tracks():
    tracks = [(i * 60) % 360 for i in range(6)]
    tracks[2] = float("nan")
    positions = [pos(5000.0, t, i * 10_000) for i, t in enumerate(tracks)]
    assert detect_holding("abc", "DAL1", positions) is None


def test_holding_still_fires_for_airborne_circle():
    positions = [pos(5000.0, (i * 60) % 360, i * 10_000) for i in range(6)]
    a = detect_holding("abc", "DAL1", positions)
    assert a is not None


def test_rapid_descent_ignores_nan_altitudes():
    positions = [
        pos(30000, 90, 0),
        pos(float("nan"), 90, 30_000),
        pos(26000, 90, 60_000),
    ]
    assert detect_rapid_descent("abc", "DAL1", positions) is None


def test_squawk_ignores_nan():
    assert detect_squawk("abc", "DAL1", float("nan"), 40, -74, 30000, 1000, None) is None

def test_rapid_descent_rejects_samples_too_close_together():
    """Three samples 5 ms apart — real adsb.lol can produce this in one micro-batch."""
    positions = [
        pos(5000, 90, 0),
        pos(4500, 90, 5),
        pos(3325, 90, 10),
    ]
    assert detect_rapid_descent("abc", "DAL1", positions) is None


def test_rapid_descent_rejects_physically_impossible_rate():
    """10,000 ft in 5 seconds = 120,000 ft/min, not physically possible."""
    positions = [
        pos(13000, 90, 0),
        pos(8000, 90, 2_500),
        pos(3000, 90, 5_000),
    ]
    assert detect_rapid_descent("abc", "DAL1", positions) is None



def test_holding_ignores_aircraft_below_2000ft():
    """Taxiing aircraft on winding taxiways must not fire holding_pattern."""
    positions = [pos(500.0, (i * 60) % 360, i * 10_000) for i in range(6)]
    assert detect_holding("abc", "DAL1", positions) is None


def test_holding_still_fires_at_5000ft():
    """Real JFK holds operate at 2,000-7,000 ft; 5,000 ft must still fire."""
    positions = [pos(5000.0, (i * 60) % 360, i * 10_000) for i in range(6)]
    a = detect_holding("abc", "DAL1", positions)
    assert a is not None
    assert a.anomaly_type == "holding_pattern"
def test_rapid_descent_still_fires_on_real_emergency():
    """A real 4,000 ft/min descent sustained for 75s at cruise must trigger."""
    positions = [pos(30000 - i * 1000, 90, i * 15_000) for i in range(6)]
    a = detect_rapid_descent("abc", "DAL1", positions)
    assert a is not None
    assert "4000 ft/min" in a.details
def test_rapid_descent_does_not_fire_on_gentle_approach():
    """JFK approach: 10k→8.5k over 75s = 1,200 fpm. Below low-alt 5,000 threshold."""
    positions = [pos(10000 - i * 250, 90, i * 15_000) for i in range(6)]
    assert detect_rapid_descent("abc", "DAL1", positions) is None


def test_rapid_descent_does_not_fire_on_normal_approach_at_3000fpm():
    """3,000 fpm below 10k ft is normal approach — NOT an anomaly."""
    positions = [pos(10000 - i * 750, 90, i * 15_000) for i in range(6)]
    assert detect_rapid_descent("abc", "DAL1", positions) is None


def test_rapid_descent_fires_on_emergency_below_10k():
    """6,000 fpm below 10k is above the 5,000 low-alt threshold — fires."""
    positions = [pos(10000 - i * 1500, 90, i * 15_000) for i in range(6)]
    a = detect_rapid_descent("abc", "DAL1", positions)
    assert a is not None
    assert a.severity == "ADVISORY"


def test_holding_suppresses_slow_pattern_work():
    """A Cessna turning at 120 kts is pattern work, not a hold."""
    positions = [pos(5000.0, (i * 60) % 360, i * 10_000, gs=120.0) for i in range(6)]
    assert detect_holding("abc", "DAL1", positions) is None


def test_holding_fires_for_fast_enroute_hold():
    """A jet turning at 240 kts at FL150 is a real en-route hold."""
    positions = [pos(15000.0, (i * 60) % 360, i * 10_000, gs=240.0) for i in range(6)]
    a = detect_holding("abc", "DAL1", positions)
    assert a is not None
    assert a.phase == "en_route_hold"
    assert a.severity == "ADVISORY"


def test_severity_squawk_emergency():
    a = detect_squawk("abc", "DAL1", "7700", 40.0, -74.0, 30000.0, 1000, None)
    assert a is not None
    assert a.severity == "EMERGENCY"


def test_severity_deep_descent_emergency():
    """8,000 fpm above 10k ft is EMERGENCY tier."""
    positions = [pos(30000 - i * 2000, 90, i * 15_000) for i in range(6)]
    a = detect_rapid_descent("abc", "DAL1", positions)
    assert a is not None
    assert a.severity == "EMERGENCY"
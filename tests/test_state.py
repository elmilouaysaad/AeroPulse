"""Tests for src.streaming.state — the bridge between pure logic and Spark's
applyInPandasWithState. GroupState is mocked; this does not need a cluster."""
import json
from unittest.mock import MagicMock

import pandas as pd

from src.streaming.state import (
    MAX_POSITIONS, OUTPUT_COLUMNS,
    _load_state, _dump_state, detect_anomalies,
)
from src.streaming.detection import Position


def make_state(
    exists=False, positions=None, last_squawk=None, timed_out=False, raw=None,
    last_rapid_ms=None, last_holding_ms=None,
):
    """Mock GroupState with the interface detect_anomalies uses.

    `raw` overrides positions+last_squawk when you already have the
    serialized `(json_str, squawk, rapid_ms, holding_ms)` tuple from a
    previous update() call.
    """
    state = MagicMock()
    state.exists = exists
    state.hasTimedOut = timed_out
    if exists:
        if raw is not None:
            state.get = raw
        else:
            state.get = _dump_state(
                positions or [], last_squawk, last_rapid_ms, last_holding_ms
            )
    else:
        state.get = None
    return state


def make_pdf(rows):
    """Build a DataFrame shaped like the parsed StateVector stream."""
    return pd.DataFrame(rows)


def row(hex_="abc", squawk="1200", alt=30000.0, track=90.0,
        ts="2026-11-09T16:00:00Z", lat=40.0, lon=-74.0):
    return {
        "hex": hex_, "flight": "DAL1", "lat": lat, "lon": lon,
        "alt_baro_ft": alt, "gs_kts": 420.0, "track_deg": track,
        "squawk": squawk, "seen_sec": 1.0, "seen_pos_sec": 1.0,
        "on_ground": False,
        "kafka_ts": pd.Timestamp(ts), "event_time": pd.Timestamp(ts),
    }


# ---------- serialization roundtrip ----------

def test_dump_truncates_to_max_positions():
    positions = [
        Position(lat=40.0, lon=-74.0, alt_ft=30000.0, track_deg=90.0,
                 event_time_ms=i * 1000)
        for i in range(MAX_POSITIONS + 5)
    ]
    json_str, _squawk, _rapid, _holding = _dump_state(
        positions, "1200", None, None
    )
    loaded = json.loads(json_str)
    assert len(loaded) == MAX_POSITIONS


def test_load_state_roundtrip():
    positions = [Position(lat=40.0, lon=-74.0, alt_ft=28000.0,
                          track_deg=45.0, event_time_ms=1_700_000_000_000)]
    state = make_state(
        exists=True,
        positions=positions,
        last_squawk="7700",
        last_rapid_ms=1_700_000_000_000,
        last_holding_ms=None,
    )
    loaded_positions, loaded_squawk, loaded_rapid, loaded_holding = _load_state(state)
    assert loaded_squawk == "7700"
    assert loaded_rapid == 1_700_000_000_000
    assert loaded_holding is None
    assert len(loaded_positions) == 1
    assert loaded_positions[0].alt_ft == 28000.0
    assert loaded_positions[0].track_deg == 45.0


def test_load_state_returns_empty_when_missing():
    state = make_state(exists=False)
    positions, last_squawk, last_rapid, last_holding = _load_state(state)
    assert positions == []
    assert last_squawk is None
    assert last_rapid is None
    assert last_holding is None


# ---------- detect_anomalies ----------

def test_empty_batch_yields_empty_dataframe_with_correct_columns():
    """Regression test for the OUTPUT_SCHEMA.split(', ') bug."""
    state = make_state(exists=False)
    pdf = make_pdf([])
    results = list(detect_anomalies(("abc",), iter([pdf]), state))
    assert len(results) == 1
    assert list(results[0].columns) == OUTPUT_COLUMNS


def test_normal_flight_yields_empty_dataframe():
    state = make_state(exists=False)
    pdf = make_pdf([row(squawk="1200", alt=30000.0)])
    results = list(detect_anomalies(("abc",), iter([pdf]), state))
    assert len(results) == 1
    assert results[0].empty
    # State should now contain the one position
    assert state.update.called


def test_squawk_alert_emitted():
    state = make_state(exists=False)
    pdf = make_pdf([row(squawk="7700")])
    results = list(detect_anomalies(("abc",), iter([pdf]), state))
    out = results[0]
    assert not out.empty
    assert "squawk_7700" in out["anomaly_type"].values


def test_squawk_not_refired_across_batches():
    """State must remember last_squawk across detect_anomalies invocations."""
    # Batch 1: normal squawk — no alert
    state1 = make_state(exists=False)
    list(detect_anomalies(("abc",), iter([make_pdf([row(squawk="1200")])]), state1))

    # update() was called with the (json, squawk) tuple — capture it
    raw_after_batch1 = state1.update.call_args[0][0]

    # Batch 2: 7700 — should fire (last_squawk was 1200)
    state2 = make_state(exists=True, raw=raw_after_batch1)
    out2 = list(
        detect_anomalies(("abc",), iter([make_pdf([row(squawk="7700")])]), state2)
    )[0]
    assert "squawk_7700" in out2["anomaly_type"].values

    # Batch 3: still 7700 — must NOT fire (last_squawk is now 7700)
    raw_after_batch2 = state2.update.call_args[0][0]
    state3 = make_state(exists=True, raw=raw_after_batch2)
    out3 = list(
        detect_anomalies(("abc",), iter([make_pdf([row(squawk="7700")])]), state3)
    )[0]
    assert out3.empty


def test_timed_out_state_is_removed():
    state = make_state(exists=True, timed_out=True)
    list(detect_anomalies(("abc",), iter([make_pdf([])]), state))
    state.remove.assert_called_once()

def test_rapid_descent_not_refired_across_batches():
    """Same aircraft descending across batches fires once within suppression window."""
    batch1 = make_pdf([
        row(alt=30000.0, ts="2026-11-09T16:00:00Z"),
        row(alt=29000.0, ts="2026-11-09T16:00:12Z"),
        row(alt=28000.0, ts="2026-11-09T16:00:24Z"),
        row(alt=27000.0, ts="2026-11-09T16:00:36Z"),
        row(alt=26000.0, ts="2026-11-09T16:00:48Z"),
        row(alt=25000.0, ts="2026-11-09T16:01:00Z"),
    ])
    state1 = make_state(exists=False)
    out1 = list(detect_anomalies(("abc",), iter([batch1]), state1))[0]
    assert "rapid_descent" in out1["anomaly_type"].values

    # Second batch 15 seconds later — still descending, but suppressed
    raw = state1.update.call_args[0][0]
    batch2 = make_pdf([
        row(alt=24000.0, ts="2026-11-09T16:01:15Z"),
        row(alt=23000.0, ts="2026-11-09T16:01:27Z"),
        row(alt=22000.0, ts="2026-11-09T16:01:39Z"),
    ])
    state2 = make_state(exists=True, raw=raw)
    out2 = list(detect_anomalies(("abc",), iter([batch2]), state2))[0]
    assert out2.empty  # suppressed


def test_rapid_descent_fires_again_after_suppression_window():
    """After 60 seconds, a continuing descent re-alerts."""
    batch1 = make_pdf([
        row(alt=30000.0, ts="2026-11-09T16:00:00Z"),
        row(alt=28000.0, ts="2026-11-09T16:00:15Z"),
        row(alt=26000.0, ts="2026-11-09T16:00:30Z"),
    ])
    state1 = make_state(exists=False)
    list(detect_anomalies(("abc",), iter([batch1]), state1))

    # 90 seconds later — outside the 60-second suppression window
    raw = state1.update.call_args[0][0]
    batch2 = make_pdf([
        row(alt=24000.0, ts="2026-11-09T16:02:00Z"),
        row(alt=22000.0, ts="2026-11-09T16:02:15Z"),
        row(alt=20000.0, ts="2026-11-09T16:02:30Z"),
    ])
    state2 = make_state(exists=True, raw=raw)
    out2 = list(detect_anomalies(("abc",), iter([batch2]), state2))[0]
    assert "rapid_descent" in out2["anomaly_type"].values
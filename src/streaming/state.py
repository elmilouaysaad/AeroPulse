"""State schema and the applyInPandasWithState entry point."""
from __future__ import annotations

import json
from typing import Iterator

import pandas as pd
from pyspark.sql.streaming.state import GroupState

from src.streaming.detection import (
    Position, detect_squawk, detect_rapid_descent, detect_holding,
)

MAX_POSITIONS = 10

STATE_SCHEMA = (
    "positions_json STRING, last_squawk STRING, "
    "last_rapid_descent_ms BIGINT, last_holding_ms BIGINT"
)
OUTPUT_SCHEMA = (
    "hex STRING, flight STRING, anomaly_type STRING, detected_at_ms LONG, "
    "lat DOUBLE, lon DOUBLE, alt_baro_ft DOUBLE, details STRING, "
    "severity STRING, phase STRING, rate_fpm DOUBLE, turn_rate_dps DOUBLE"
)
OUTPUT_COLUMNS = [
    "hex", "flight", "anomaly_type", "detected_at_ms",
    "lat", "lon", "alt_baro_ft", "details",
    "severity", "phase", "rate_fpm", "turn_rate_dps",
]


def _load_state(
    state: GroupState,
) -> tuple[list[Position], str | None, int | None, int | None]:
    if not state.exists:
        return [], None, None, None
    row = state.get
    positions: list[Position] = []
    for p in json.loads(row[0]):
        # Old state entries predate gs_kts; tolerate missing field.
        positions.append(Position(
            lat=p["lat"], lon=p["lon"],
            alt_ft=p.get("alt_ft"), track_deg=p.get("track_deg"),
            event_time_ms=p["event_time_ms"],
            gs_kts=p.get("gs_kts"),
        ))
    return positions, row[1], row[2], row[3]


def _dump_state(
    positions: list[Position],
    last_squawk: str | None,
    last_rapid_descent_ms: int | None,
    last_holding_ms: int | None,
) -> tuple:
    return (
        json.dumps([p.__dict__ for p in positions[-MAX_POSITIONS:]]),
        last_squawk,
        last_rapid_descent_ms,
        last_holding_ms,
    )


def detect_anomalies(
    key: tuple[str],
    pdf_iter: Iterator[pd.DataFrame],
    state: GroupState,
) -> Iterator[pd.DataFrame]:
    if state.hasTimedOut:
        state.remove()
        return

    hex_ = key[0]
    positions, last_squawk, last_rapid_ms, last_holding_ms = _load_state(state)
    alerts: list[dict] = []

    for pdf in pdf_iter:
        for _, row in pdf.iterrows():
            event_ms = int(row["event_time"].timestamp() * 1000)
            gs = row["gs_kts"] if ("gs_kts" in row and pd.notna(row["gs_kts"])) else None
            pos = Position(
                lat=row["lat"], lon=row["lon"],
                alt_ft=row["alt_baro_ft"], track_deg=row["track_deg"],
                event_time_ms=event_ms, gs_kts=gs,
            )
            positions.append(pos)
            positions = positions[-MAX_POSITIONS:]

            sq = detect_squawk(
                hex_=hex_, flight=row["flight"], squawk=row["squawk"],
                lat=pos.lat, lon=pos.lon, alt_ft=pos.alt_ft,
                event_time_ms=event_ms, previous_squawk=last_squawk,
            )
            if sq:
                alerts.append(sq.__dict__)
            last_squawk = row["squawk"]

            rd = detect_rapid_descent(
                hex_, row["flight"], positions, last_alert_at_ms=last_rapid_ms,
            )
            if rd:
                alerts.append(rd.__dict__)
                last_rapid_ms = rd.detected_at_ms

            hd = detect_holding(
                hex_, row["flight"], positions, last_alert_at_ms=last_holding_ms,
            )
            if hd:
                alerts.append(hd.__dict__)
                last_holding_ms = hd.detected_at_ms

    state.update(
        _dump_state(positions, last_squawk, last_rapid_ms, last_holding_ms)
    )

    if not alerts:
        yield pd.DataFrame(columns=OUTPUT_COLUMNS)
        return
    yield pd.DataFrame(alerts)
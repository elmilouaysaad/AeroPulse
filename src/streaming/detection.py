"""Pure detection logic. No Spark imports, no I/O — fully unit-testable."""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional


EMERGENCY_SQUAWKS = {"7700": "general_emergency", "7600": "radio_failure", "7500": "hijack"}

# ---- rapid descent ----
RAPID_DESCENT_FPM_LOW_ALT    = 5000.0    # below 10k ft: needs more evidence
RAPID_DESCENT_FPM_HIGH_ALT   = 3000.0    # above 10k ft: cruise emergencies
RAPID_DESCENT_ALT_BOUNDARY   = 10_000.0
RAPID_DESCENT_MIN_SAMPLES    = 6
RAPID_DESCENT_MIN_WINDOW_SEC = 3.0
MAX_PLAUSIBLE_DESCENT_FPM    = 15_000.0
RAPID_DESCENT_SUPPRESSION_MS = 60_000

# ---- holding ----
HOLDING_HEADING_ROTATION_DEG  = 270.0
HOLDING_ALTITUDE_TOLERANCE_FT = 1000.0
HOLDING_MIN_SAMPLES           = 6
HOLDING_MIN_ALT_FT            = 3000.0
HOLDING_MAX_GS_KTS            = 200.0
HOLDING_SUPPRESSION_MS        = 1_800_000  # 30 min (was 5 min)


def _is_valid_number(x) -> bool:
    if x is None:
        return False
    try:
        return not math.isnan(float(x))
    except (TypeError, ValueError):
        return False


@dataclass
class Position:
    lat: float
    lon: float
    alt_ft: Optional[float]
    track_deg: Optional[float]
    event_time_ms: int
    gs_kts: Optional[float] = None


@dataclass
class Anomaly:
    hex: str
    flight: Optional[str]
    anomaly_type: str
    detected_at_ms: int
    lat: Optional[float]
    lon: Optional[float]
    alt_baro_ft: Optional[float]
    details: str
    severity: str = "INFO"
    phase: Optional[str] = None
    rate_fpm: Optional[float] = None
    turn_rate_dps: Optional[float] = None


def _severity_for(anomaly_type: str, alt_ft: Optional[float], rate_fpm: Optional[float]) -> str:
    if anomaly_type in ("squawk_7500", "squawk_7700"):
        return "EMERGENCY"
    if anomaly_type == "squawk_7600":
        return "ADVISORY"
    if anomaly_type == "rapid_descent" and rate_fpm is not None:
        return "EMERGENCY" if rate_fpm >= 7000 else "ADVISORY"
    if anomaly_type == "holding_pattern" and alt_ft is not None and alt_ft >= 15_000:
        return "ADVISORY"
    return "INFO"


def _phase_for(
    anomaly_type: str, alt_ft: Optional[float], gs_kts: Optional[float],
) -> Optional[str]:
    if alt_ft is None:
        return None
    if anomaly_type == "rapid_descent":
        return "approach" if alt_ft < 10_000 else "cruise_emergency"
    if anomaly_type == "holding_pattern":
        if gs_kts is not None and gs_kts <= HOLDING_MAX_GS_KTS:
            return "pattern_work"
        return "en_route_hold" if alt_ft >= 15_000 else "low_hold"
    return None


def detect_squawk(
    hex_: str, flight: Optional[str], squawk: Optional[str],
    lat: Optional[float], lon: Optional[float], alt_ft: Optional[float],
    event_time_ms: int, previous_squawk: Optional[str],
) -> Optional[Anomaly]:
    if not isinstance(squawk, str) or squawk not in EMERGENCY_SQUAWKS:
        return None
    if previous_squawk == squawk:
        return None
    atype = f"squawk_{squawk}"
    return Anomaly(
        hex=hex_, flight=flight, anomaly_type=atype,
        detected_at_ms=event_time_ms,
        lat=lat, lon=lon, alt_baro_ft=alt_ft,
        details=EMERGENCY_SQUAWKS[squawk],
        severity=_severity_for(atype, alt_ft, None),
        phase=_phase_for(atype, alt_ft, None),
    )


def detect_rapid_descent(
    hex_: str, flight: Optional[str], positions: list[Position],
    last_alert_at_ms: Optional[int] = None,
    suppression_window_ms: int = RAPID_DESCENT_SUPPRESSION_MS,
) -> Optional[Anomaly]:
    if len(positions) < RAPID_DESCENT_MIN_SAMPLES:
        return None
    window = positions[-RAPID_DESCENT_MIN_SAMPLES:]
    if not all(_is_valid_number(p.alt_ft) for p in window):
        return None
    alts = [p.alt_ft for p in window]
    if any(a <= 0 for a in alts):
        return None

    times_s = [(p.event_time_ms - window[0].event_time_ms) / 1000.0 for p in window]
    if times_s[-1] <= 0:
        return None
    if times_s[-1] < RAPID_DESCENT_MIN_WINDOW_SEC:
        return None

    descent_fpm = (alts[0] - alts[-1]) / (times_s[-1] / 60.0)
    threshold = (
        RAPID_DESCENT_FPM_LOW_ALT if alts[-1] < RAPID_DESCENT_ALT_BOUNDARY
        else RAPID_DESCENT_FPM_HIGH_ALT
    )
    if descent_fpm < threshold:
        return None
    if descent_fpm > MAX_PLAUSIBLE_DESCENT_FPM:
        return None

    last = window[-1]
    if (
        last_alert_at_ms is not None
        and (last.event_time_ms - last_alert_at_ms) < suppression_window_ms
    ):
        return None

    return Anomaly(
        hex=hex_, flight=flight, anomaly_type="rapid_descent",
        detected_at_ms=last.event_time_ms,
        lat=last.lat, lon=last.lon, alt_baro_ft=last.alt_ft,
        details=f"{descent_fpm:.0f} ft/min over {len(window)} samples",
        severity=_severity_for("rapid_descent", last.alt_ft, descent_fpm),
        phase=_phase_for("rapid_descent", last.alt_ft, last.gs_kts),
        rate_fpm=descent_fpm,
    )


def detect_holding(
    hex_: str, flight: Optional[str], positions: list[Position],
    last_alert_at_ms: Optional[int] = None,
    suppression_window_ms: int = HOLDING_SUPPRESSION_MS,
) -> Optional[Anomaly]:
    if len(positions) < HOLDING_MIN_SAMPLES:
        return None
    window = positions[-HOLDING_MIN_SAMPLES:]

    if not all(_is_valid_number(p.alt_ft) and p.alt_ft > 0 for p in window):
        return None
    alts = [p.alt_ft for p in window]

    if any(a < HOLDING_MIN_ALT_FT for a in alts):
        return None
    if max(alts) - min(alts) > HOLDING_ALTITUDE_TOLERANCE_FT:
        return None
    if not all(_is_valid_number(p.track_deg) for p in window):
        return None

    tracks = [p.track_deg for p in window]
    rotation = 0.0
    for prev, curr in zip(tracks, tracks[1:]):
        delta = ((curr - prev + 180) % 360) - 180
        rotation += delta
    if abs(rotation) < HOLDING_HEADING_ROTATION_DEG:
        return None

    last = window[-1]

    # Slow + rotating = pattern work, not an anomaly worth alerting
    if last.gs_kts is not None and last.gs_kts <= HOLDING_MAX_GS_KTS:
        return None

    if (
        last_alert_at_ms is not None
        and (last.event_time_ms - last_alert_at_ms) < suppression_window_ms
    ):
        return None

    window_sec = (last.event_time_ms - window[0].event_time_ms) / 1000.0
    turn_rate_dps = abs(rotation) / window_sec if window_sec > 0 else None

    return Anomaly(
        hex=hex_, flight=flight, anomaly_type="holding_pattern",
        detected_at_ms=last.event_time_ms,
        lat=last.lat, lon=last.lon, alt_baro_ft=last.alt_ft,
        details=f"rotated {rotation:.0f}° at {last.alt_ft:.0f} ft",
        severity=_severity_for("holding_pattern", last.alt_ft, None),
        phase=_phase_for("holding_pattern", last.alt_ft, last.gs_kts),
        turn_rate_dps=turn_rate_dps,
    )
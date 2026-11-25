"""Parse raw adsb.lol aircraft state vectors into clean, typed records."""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Optional


@dataclass
class StateVector:
    hex: str
    flight: Optional[str]
    lat: Optional[float]
    lon: Optional[float]
    alt_baro_ft: Optional[float]
    gs_kts: Optional[float]
    track_deg: Optional[float]
    squawk: Optional[str]
    seen_sec: float
    seen_pos_sec: Optional[float]
    on_ground: bool


def parse_altitude(value: Any) -> tuple[Optional[float], bool]:
    """
    adsb.lol emits alt_baro as:
      - int/float -> altitude in feet
      - string "ground" -> aircraft on tarmac
      - None -> unknown

    We normalise "ground" to 0.0 ft and keep the record.
    A ground aircraft squawking 7700 is still an emergency.
    """
    if isinstance(value, (int, float)):
        return float(value), False
    if isinstance(value, str) and value.strip().lower() == "ground":
        return 0.0, True
    return None, False


def parse_record(raw: dict[str, Any]) -> Optional[StateVector]:
    seen = raw.get("seen")
    if seen is None or float(seen) > 60:
        return None  # not live

    lat, lon = raw.get("lat"), raw.get("lon")
    if lat is None or lon is None:
        return None  # no usable position

    alt_ft, on_ground = parse_altitude(raw.get("alt_baro"))

    flight = raw.get("flight")
    if isinstance(flight, str):
        flight = flight.strip() or None  # callsigns arrive space-padded

    return StateVector(
        hex=raw["hex"],
        flight=flight,
        lat=float(lat),
        lon=float(lon),
        alt_baro_ft=alt_ft,
        gs_kts=raw.get("gs"),
        track_deg=raw.get("track"),
        squawk=raw.get("squawk"),
        seen_sec=float(seen),
        seen_pos_sec=raw.get("seen_pos"),
        on_ground=on_ground,
    )


def parse_response(payload: dict[str, Any]) -> list[StateVector]:
    vectors = [parse_record(ac) for ac in payload.get("ac", [])]
    return [v for v in vectors if v is not None]


def to_dicts(vectors: list[StateVector]) -> list[dict[str, Any]]:
    return [asdict(v) for v in vectors]

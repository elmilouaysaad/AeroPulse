"""Prompt construction. Pure functions — testable without any LLM."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass


@dataclass
class BriefInput:
    window_start_iso: str
    window_end_iso: str
    aircraft_count: int
    anomaly_counts: dict[str, int]
    top_anomalies: list[dict]
    repeat_aircraft: list[dict] | None = None
    regime_recurrence_24h: dict[str, int] | None = None


@dataclass
class ExplanationInput:
    hex: str
    flight: str | None
    anomaly_type: str
    detected_at_iso: str
    lat: float | None
    lon: float | None
    alt_baro_ft: float | None
    details: str


BRIEF_SYSTEM = (
    "You are an aviation operations analyst. Write a 3-sentence brief for "
    "the duty desk covering traffic volume, any active anomalies, and "
    "operational concerns. Be specific about locations and numbers. Do not "
    "speculate beyond the data. Do not use markdown."
)

EXPLANATION_SYSTEM = (
    "You are an aviation operations analyst. Given a single detected anomaly "
    "and its context, write two sentences explaining what the pattern is "
    "consistent with. Do not diagnose; describe. Do not speculate beyond the "
    "data. Do not use markdown."
)


def build_brief_prompt(data: BriefInput) -> str:
    payload = json.dumps(asdict(data), indent=2)
    return f"{BRIEF_SYSTEM}\n\nData window:\n{payload}\n\nBrief:"


def build_explanation_prompt(data: ExplanationInput) -> str:
    payload = json.dumps(asdict(data), indent=2)
    return f"{EXPLANATION_SYSTEM}\n\nAnomaly:\n{payload}\n\nExplanation:"
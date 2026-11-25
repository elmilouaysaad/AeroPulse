"""Pydantic response models for the API."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class Brief(BaseModel):
    model_config = ConfigDict(extra="ignore")

    text: str
    provider: str
    generated_at: str
    stale: bool = False


class Anomaly(BaseModel):
    model_config = ConfigDict(extra="ignore")

    hex: str
    flight: str | None = None
    anomaly_type: str
    detected_at_ms: int
    lat: float | None = None
    lon: float | None = None
    alt_baro_ft: float | None = None
    details: str | None = None
    explanation: str | None = None
    explanation_provider: str | None = None


class AircraftPoint(BaseModel):
    model_config = ConfigDict(extra="ignore")

    detected_at_ms: int
    lat: float | None = None
    lon: float | None = None
    alt_baro_ft: float | None = None
    anomaly_type: str


class Stats(BaseModel):
    model_config = ConfigDict(extra="ignore")

    total_anomalies: int
    window_minutes: int
    by_type: dict[str, int]
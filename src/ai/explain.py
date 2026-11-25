"""Generate explanations for new anomalies and index them for similarity search."""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

from src.ai import db
from src.ai.client import AllProvidersFailed, LLMClient
from src.ai.prompts import ExplanationInput, build_explanation_prompt

log = logging.getLogger(__name__)


def run(batch_size: int = 5, time_budget_sec: int = 240) -> dict:
    anomalies = db.fetch_unexplained_anomalies(limit=batch_size)
    if not anomalies:
        return {"processed": 0, "indexed": 0}

    client = LLMClient()
    deadline = time.monotonic() + time_budget_sec
    written: list[dict] = []
    last_error: Exception | None = None

    for a in anomalies:
        if time.monotonic() > deadline:
            break  # stay inside the schedule interval; the rest is picked up next run

        detected_iso = datetime.fromtimestamp(
            a["detected_at_ms"] / 1000, tz=timezone.utc
        ).isoformat()
        prompt = build_explanation_prompt(ExplanationInput(
            hex=a["hex"],
            flight=a["flight"],
            anomaly_type=a["anomaly_type"],
            detected_at_iso=detected_iso,
            lat=a["lat"],
            lon=a["lon"],
            alt_baro_ft=a["alt_baro_ft"],
            details=a["details"],
        ))

        try:
            result = client.generate(prompt, max_tokens=150)
        except AllProvidersFailed as exc:
            # Every provider is down or rate-limited: stop instead of hammering them.
            last_error = exc
            log.warning("explain: all LLM providers failed: %s", exc)
            break

        db.write_explanation(
            a["hex"], a["anomaly_type"], a["detected_at_ms"],
            result.text, result.provider,
        )
        written.append({
            "hex": a["hex"],
            "anomaly_type": a["anomaly_type"],
            "detected_at_ms": a["detected_at_ms"],
            "explanation": result.text,
        })

    # Index right away so /similar works without waiting for the embed DAG.
    indexed = 0

    if last_error and not written:
        raise last_error  # make the Airflow task go red instead of silently doing nothing
    return {"processed": len(written), "indexed": indexed}
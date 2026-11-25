"""Generate and cache the airspace brief. Called from the Airflow DAG."""
from __future__ import annotations

import time
from datetime import datetime, timezone

from src.ai import db
from src.ai.cache import set_brief
from src.ai.client import LLMClient
from src.ai.prompts import BriefInput, build_brief_prompt


def run(window_minutes: int = 15) -> dict:
    now_ms = int(time.time() * 1000)
    start_ms = now_ms - window_minutes * 60 * 1000

    anomalies = db.fetch_recent_anomalies(window_minutes)

    # Distinguish "no anomalies" (fine) from "no data" (pipeline down)
    latest_ms = db.fetch_latest_anomaly_ms()
    pipeline_stale = latest_ms is not None and (now_ms - latest_ms) > 30 * 60 * 1000

    if pipeline_stale:
        text = (
            f"Pipeline has not produced data since "
            f"{_iso(latest_ms)}. Airspace status unknown — "
            "monitor ingestion before relying on this brief."
        )
        set_brief(text, "system")
        db.write_brief(start_ms, now_ms, text, "system")
        return {"provider": "system", "chars": len(text)}

    if not anomalies:
        text = (
            f"No anomalies detected between {_iso(start_ms)} and {_iso(now_ms)}. "
            "Airspace operating normally."
        )
        set_brief(text, "system")
        db.write_brief(start_ms, now_ms, text, "system")
        return {"provider": "system", "chars": len(text)}

    counts: dict[str, int] = {}
    repeat_map: dict[str, dict] = {}
    for a in anomalies:
        atype = a.get("anomaly_type")
        if atype:
            counts[atype] = counts.get(atype, 0) + 1

        h = a.get("hex")
        if h:
            if h not in repeat_map:
                repeat_map[h] = {
                    "hex": h,
                    "flight": a.get("flight") or "",
                    "count": 0,
                    "types": set(),
                }
            repeat_map[h]["count"] += 1
            if atype:
                repeat_map[h]["types"].add(atype)

    repeat_aircraft = [
        {
            "hex": v["hex"],
            "flight": v["flight"],
            "window_occurrences": v["count"],
            "anomaly_types": sorted(v["types"]),
        }
        for v in sorted(repeat_map.values(), key=lambda x: x["count"], reverse=True)
        if v["count"] > 1
    ]

    anomalies_24h = db.fetch_recent_anomalies(24 * 60)
    regime_recurrence_24h: dict[str, int] = {}
    for a in anomalies_24h:
        atype = a.get("anomaly_type")
        if atype:
            regime_recurrence_24h[atype] = regime_recurrence_24h.get(atype, 0) + 1

    brief_input = BriefInput(
        window_start_iso=_iso(start_ms),
        window_end_iso=_iso(now_ms),
        aircraft_count=len({a["hex"] for a in anomalies if a.get("hex")}),
        anomaly_counts=counts,
        top_anomalies=anomalies[:10],
        repeat_aircraft=repeat_aircraft,
        regime_recurrence_24h=regime_recurrence_24h,
    )

    prompt = build_brief_prompt(brief_input)
    result = LLMClient().generate(prompt, max_tokens=250)

    recurrence_bits: list[str] = []
    if repeat_aircraft:
        rep_str = ", ".join(
            f"{r['flight'] or r['hex']} ({r['hex']}, x{r['window_occurrences']})"
            for r in repeat_aircraft[:5]
        )
        recurrence_bits.append(f"Repeat aircraft in window: {rep_str}")
    if regime_recurrence_24h:
        reg_str = ", ".join(f"{k}: {v}" for k, v in sorted(regime_recurrence_24h.items()))
        recurrence_bits.append(f"24h regime counts: {reg_str}")

    final_text = result.text.strip()
    if recurrence_bits:
        final_text = f"{final_text} [{' | '.join(recurrence_bits)}]"

    set_brief(final_text, result.provider)
    db.write_brief(start_ms, now_ms, final_text, result.provider)

    return {"provider": result.provider, "chars": len(final_text)}


def _iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat()
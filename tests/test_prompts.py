from src.ai.prompts import (
    BriefInput, ExplanationInput, build_brief_prompt, build_explanation_prompt,
)


def test_brief_prompt_contains_window_and_counts():
    data = BriefInput(
        window_start_iso="2026-11-09T17:00:00Z",
        window_end_iso="2026-11-09T17:15:00Z",
        aircraft_count=42,
        anomaly_counts={"squawk_7700": 1},
        top_anomalies=[],
    )
    prompt = build_brief_prompt(data)
    assert "2026-11-09T17:00:00Z" in prompt
    assert "squawk_7700" in prompt
    assert "3-sentence" in prompt


def test_explanation_prompt_contains_anomaly():
    data = ExplanationInput(
        hex="abc123", flight="DAL1", anomaly_type="squawk_7700",
        detected_at_iso="2026-11-09T17:05:00Z",
        lat=40.0, lon=-74.0, alt_baro_ft=28000.0,
        details="general_emergency",
    )
    prompt = build_explanation_prompt(data)
    assert "abc123" in prompt
    assert "squawk_7700" in prompt
    assert "two sentences" in prompt
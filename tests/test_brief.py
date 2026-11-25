"""Unit tests for brief generation and recurrence summaries."""
from __future__ import annotations

from types import SimpleNamespace

from src.ai import brief as brief_mod
from src.ai.prompts import BriefInput, build_brief_prompt


def test_brief_input_includes_recurrence_fields():
    bi = BriefInput(
        window_start_iso="2026-11-23T18:00:00+00:00",
        window_end_iso="2026-11-23T18:15:00+00:00",
        aircraft_count=2,
        anomaly_counts={"holding_pattern": 2},
        top_anomalies=[],
        repeat_aircraft=[{"hex": "ABC123", "flight": "AT101", "window_occurrences": 2}],
        regime_recurrence_24h={"holding_pattern": 7},
    )
    prompt = build_brief_prompt(bi)
    assert "repeat_aircraft" in prompt
    assert "regime_recurrence_24h" in prompt
    assert "ABC123" in prompt


def test_brief_run_pipeline_stale(monkeypatch):
    writes = []
    cached = []

    monkeypatch.setattr(brief_mod, "time", SimpleNamespace(time=lambda: 1_700_000_000.0))
    monkeypatch.setattr(brief_mod.db, "fetch_recent_anomalies", lambda _w: [])
    monkeypatch.setattr(
        brief_mod.db,
        "fetch_latest_anomaly_ms",
        lambda: int((1_700_000_000.0 - 45 * 60) * 1000),
    )
    monkeypatch.setattr(brief_mod, "set_brief", lambda text, prov: cached.append((text, prov)))
    monkeypatch.setattr(
        brief_mod.db,
        "write_brief",
        lambda s, e, text, prov: writes.append((s, e, text, prov)),
    )

    out = brief_mod.run(window_minutes=15)
    assert out["provider"] == "system"
    assert "Pipeline has not produced data since" in cached[0][0]
    assert len(writes) == 1


def test_brief_run_no_anomalies(monkeypatch):
    writes = []
    cached = []

    monkeypatch.setattr(brief_mod, "time", SimpleNamespace(time=lambda: 1_700_000_000.0))
    monkeypatch.setattr(brief_mod.db, "fetch_recent_anomalies", lambda _w: [])
    monkeypatch.setattr(
        brief_mod.db,
        "fetch_latest_anomaly_ms",
        lambda: int((1_700_000_000.0 - 2 * 60) * 1000),
    )
    monkeypatch.setattr(brief_mod, "set_brief", lambda text, prov: cached.append((text, prov)))
    monkeypatch.setattr(
        brief_mod.db,
        "write_brief",
        lambda s, e, text, prov: writes.append((s, e, text, prov)),
    )

    out = brief_mod.run(window_minutes=15)
    assert out["provider"] == "system"
    assert "No anomalies detected" in cached[0][0]
    assert len(writes) == 1


def test_brief_run_appends_repeat_aircraft_and_24h_regimes(monkeypatch):
    captured_inputs = []
    cached = []
    writes = []

    window_events = [
        {"hex": "3C66A1", "flight": "DLH400", "anomaly_type": "rapid_descent"},
        {"hex": "3C66A1", "flight": "DLH400", "anomaly_type": "rapid_descent"},
        {"hex": "4CA812", "flight": "RYR102", "anomaly_type": "holding_pattern"},
    ]
    day_events = window_events + [
        {"hex": "4CA812", "flight": "RYR102", "anomaly_type": "holding_pattern"},
        {"hex": "3C66A1", "flight": "DLH400", "anomaly_type": "rapid_descent"},
    ]

    class _FakeLLM:
        def generate(self, _prompt: str, max_tokens: int = 250):
            return SimpleNamespace(text="Traffic normal with two monitored events.", provider="stub")

    def _fake_fetch(minutes: int):
        return day_events if minutes >= 24 * 60 else window_events

    monkeypatch.setattr(brief_mod, "time", SimpleNamespace(time=lambda: 1_700_000_000.0))
    monkeypatch.setattr(brief_mod.db, "fetch_recent_anomalies", _fake_fetch)
    monkeypatch.setattr(brief_mod.db, "fetch_latest_anomaly_ms", lambda: 1_700_000_000_000)
    monkeypatch.setattr(
        brief_mod,
        "build_brief_prompt",
        lambda bi: captured_inputs.append(bi) or "prompt",
    )
    monkeypatch.setattr(brief_mod, "LLMClient", _FakeLLM)
    monkeypatch.setattr(brief_mod, "set_brief", lambda text, prov: cached.append((text, prov)))
    monkeypatch.setattr(
        brief_mod.db,
        "write_brief",
        lambda s, e, text, prov: writes.append((s, e, text, prov)),
    )

    out = brief_mod.run(window_minutes=15)
    assert out["provider"] == "stub"
    assert len(captured_inputs) == 1
    assert captured_inputs[0].repeat_aircraft[0]["hex"] == "3C66A1"
    assert captured_inputs[0].repeat_aircraft[0]["window_occurrences"] == 2
    assert captured_inputs[0].regime_recurrence_24h == {
        "rapid_descent": 3,
        "holding_pattern": 2,
    }
    assert "Repeat aircraft in window: DLH400 (3C66A1, x2)" in cached[0][0]
    assert "24h regime counts: holding_pattern: 2, rapid_descent: 3" in cached[0][0]
    assert writes[-1][2] == cached[0][0]

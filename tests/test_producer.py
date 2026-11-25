from unittest.mock import MagicMock
import json
import time

from prometheus_client import REGISTRY

from src.ingestion import producer as producer_mod
from src.ingestion.parser import StateVector


def make_sv(hex_="abc123", flight="BAW117", lat=51.47, lon=-0.45):
    return StateVector(
        hex=hex_, flight=flight, lat=lat, lon=lon,
        alt_baro_ft=36000.0, gs_kts=450.0, track_deg=90.0,
        squawk="1200", seen_sec=1.0, seen_pos_sec=1.0, on_ground=False,
    )


def counter(name, labels):
    return REGISTRY.get_sample_value(name, labels) or 0.0


# ---- produce_vectors ----

def test_produce_vectors_sends_one_message_per_aircraft():
    mock = MagicMock()
    count = producer_mod.produce_vectors(
        mock, [make_sv("aaa"), make_sv("bbb"), make_sv("ccc")]
    )
    assert count == 3
    assert mock.produce.call_count == 3
    mock.flush.assert_called_once()


def test_produce_vectors_uses_hex_as_key():
    mock = MagicMock()
    producer_mod.produce_vectors(mock, [make_sv("abc123")])
    call = mock.produce.call_args.kwargs
    assert call["key"] == b"abc123"


def test_produce_vectors_serializes_value_as_json():
    mock = MagicMock()
    producer_mod.produce_vectors(mock, [make_sv("abc123")])
    payload = json.loads(mock.produce.call_args.kwargs["value"])
    assert payload["hex"] == "abc123"
    assert payload["alt_baro_ft"] == 36000.0
    assert payload["on_ground"] is False


def test_produce_vectors_empty_list_does_not_crash():
    mock = MagicMock()
    count = producer_mod.produce_vectors(mock, [])
    assert count == 0
    assert mock.produce.call_count == 0
    mock.flush.assert_called_once()


# ---- _on_delivery ----

def _msg(topic="aircraft_state", partition=0, offset=42, key=b"abc123"):
    msg = MagicMock()
    msg.topic.return_value = topic
    msg.partition.return_value = partition
    msg.offset.return_value = offset
    msg.key.return_value = key
    msg.timestamp.return_value = (1, int(time.time() * 1000))
    return msg


def test_delivery_success_increments_counter():
    labels = {"topic": "aircraft_state", "status": "success"}
    before = counter("aeropulse_kafka_messages_produced_total", labels)
    producer_mod._on_delivery(None, _msg())
    after = counter("aeropulse_kafka_messages_produced_total", labels)
    assert after == before + 1


def test_delivery_failure_increments_failed_counter():
    labels = {"topic": "aircraft_state", "status": "failed"}
    before = counter("aeropulse_kafka_messages_produced_total", labels)
    producer_mod._on_delivery("broker rejected", _msg())
    after = counter("aeropulse_kafka_messages_produced_total", labels)
    assert after == before + 1


def test_delivery_failure_does_not_touch_success_counter():
    success = {"topic": "aircraft_state", "status": "success"}
    failed = {"topic": "aircraft_state", "status": "failed"}
    s_before = counter("aeropulse_kafka_messages_produced_total", success)
    f_before = counter("aeropulse_kafka_messages_produced_total", failed)
    producer_mod._on_delivery("broker rejected", _msg())
    assert counter("aeropulse_kafka_messages_produced_total", success) == s_before
    assert counter("aeropulse_kafka_messages_produced_total", failed) == f_before + 1
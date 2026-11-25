import json
import time
import uuid

import pytest
from confluent_kafka import Consumer

from src.ingestion import producer as producer_mod
from src.ingestion.parser import StateVector

pytestmark = pytest.mark.integration


def make_sv(hex_="abc123", alt_ft=36000.0):
    return StateVector(
        hex=hex_, flight="BAW117", lat=51.47, lon=-0.45,
        alt_baro_ft=alt_ft, gs_kts=450.0, track_deg=90.0,
        squawk="1200", seen_sec=1.0, seen_pos_sec=1.0, on_ground=False,
    )


def consume_n(bootstrap, topic, n, timeout=30):
    """Consume up to n messages, waiting at most `timeout` seconds."""
    consumer = Consumer({
        "bootstrap.servers": bootstrap,
        "group.id": f"test-{uuid.uuid4().hex}",
        "auto.offset.reset": "earliest",
        "enable.auto.commit": False,
    })
    consumer.subscribe([topic])
    messages = []
    deadline = time.time() + timeout
    while time.time() < deadline and len(messages) < n:
        msg = consumer.poll(1.0)
        if msg is None or msg.error():
            continue
        messages.append(msg)
    consumer.close()
    return messages


def test_roundtrip_three_aircraft(producer_env):
    producer = producer_mod.build_producer()
    vectors = [make_sv(f"hex{i}") for i in range(3)]
    producer_mod.produce_vectors(producer, vectors)
    messages = consume_n(producer_env["bootstrap"], producer_env["topic"], 3)
    assert len(messages) == 3


def test_key_preserved_as_hex(producer_env):
    producer = producer_mod.build_producer()
    producer_mod.produce_vectors(producer, [make_sv("abc123")])
    msgs = consume_n(producer_env["bootstrap"], producer_env["topic"], 1)
    assert msgs[0].key() == b"abc123"


def test_value_roundtrips_as_valid_json(producer_env):
    producer = producer_mod.build_producer()
    producer_mod.produce_vectors(producer, [make_sv("abc123", alt_ft=36000.0)])
    msgs = consume_n(producer_env["bootstrap"], producer_env["topic"], 1)
    payload = json.loads(msgs[0].value())
    assert payload["hex"] == "abc123"
    assert payload["alt_baro_ft"] == 36000.0
    assert payload["on_ground"] is False
    assert payload["squawk"] == "1200"


def test_same_hex_lands_on_same_partition(producer_env):
    producer = producer_mod.build_producer()
    producer_mod.produce_vectors(
        producer, [make_sv("same-hex", 36000.0), make_sv("same-hex", 35000.0)]
    )
    msgs = consume_n(producer_env["bootstrap"], producer_env["topic"], 2)
    partitions = {m.partition() for m in msgs}
    assert len(partitions) == 1


def test_different_hex_distributes_across_partitions(producer_env):
    producer = producer_mod.build_producer()
    vectors = [make_sv(f"diff{i}") for i in range(50)]
    producer_mod.produce_vectors(producer, vectors)
    msgs = consume_n(producer_env["bootstrap"], producer_env["topic"], 50)
    partitions = {m.partition() for m in msgs}
    # With 50 keys and 3 partitions, the chance all land on one is ~3 * (1/3)^50
    assert len(partitions) >= 2


def test_empty_input_produces_no_messages(producer_env):
    producer = producer_mod.build_producer()
    producer_mod.produce_vectors(producer, [])
    msgs = consume_n(producer_env["bootstrap"], producer_env["topic"], 1, timeout=5)
    assert msgs == []
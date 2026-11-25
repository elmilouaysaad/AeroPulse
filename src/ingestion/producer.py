"""Kafka producer for clean StateVectors.

Week 2 replaces the Week 1 file sink with a keyed, idempotent producer.
Key = hex (ICAO24) so that all state vectors for one aircraft land on
the same partition. Week 3's Spark job depends on this ordering.
"""
from __future__ import annotations

import json
import os
import time
from typing import Any

import structlog
from confluent_kafka import Producer
from prometheus_client import Counter, Histogram, Gauge

from .parser import StateVector

log = structlog.get_logger()

TOPIC = os.getenv("KAFKA_TOPIC", "aircraft_state")
BOOTSTRAP = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")

# ---- Producer-specific metrics ----
MESSAGES_PRODUCED = Counter(
    "aeropulse_kafka_messages_produced_total",
    "Messages acknowledged by the broker",
    ["topic", "status"],
)
DELIVERY_LATENCY = Histogram(
    "aeropulse_kafka_delivery_latency_seconds",
    "Time from produce() to delivery callback",
    buckets=(0.01, 0.05, 0.1, 0.5, 1.0, 5.0),
)
QUEUE_SIZE = Gauge(
    "aeropulse_kafka_producer_queue_size",
    "Messages currently buffered in the producer queue",
)


def build_producer() -> Producer:
    """
    Idempotent producer. librdkafka auto-enforces:
      max.in.flight.requests.per.connection <= 5, acks=all,
      retries=INT32_MAX, FIFO queuing.
    We set acks/retries explicitly only for readability; idempotence
    would enforce them anyway.
    """
    return Producer(
        {
            "bootstrap.servers": BOOTSTRAP,
            "client.id": "aeropulse-poller",
            "acks": "all",
            "enable.idempotence": True,
            "compression.type": "snappy",
            "linger.ms": 5,
            "message.timeout.ms": 30000,
        }
    )


def _on_delivery(err: Any, msg: Any) -> None:
    """Delivery callback. Runs on the producer's background poll thread."""
    if err is not None:
        MESSAGES_PRODUCED.labels(topic=msg.topic(), status="failed").inc()
        log.error(
            "kafka_delivery_failed",
            topic=msg.topic(),
            partition=msg.partition(),
            error=str(err),
        )
        return

    MESSAGES_PRODUCED.labels(topic=msg.topic(), status="success").inc()

    # msg.timestamp() returns (timestamp_type, timestamp_ms).
    # timestamp_type == 0 means "no timestamp" -> skip the observation,
    # otherwise we would record a ~50-year latency into the histogram.
    ts_type, ts_ms = msg.timestamp()
    if ts_type != 0:
        DELIVERY_LATENCY.observe(time.time() - ts_ms / 1000.0)

    log.info(
        "kafka_delivered",
        topic=msg.topic(),
        partition=msg.partition(),
        offset=msg.offset(),
        key=msg.key().decode() if msg.key() else None,
    )


def produce_vectors(producer: Producer, vectors: list[StateVector]) -> int:
    """
    Send one Kafka message per aircraft. Key = hex.
    Returns the number of messages enqueued.
    """
    for v in vectors:
        payload = json.dumps(_asdict(v)).encode("utf-8")
        producer.produce(
            topic=TOPIC,
            key=v.hex.encode("utf-8"),
            value=payload,
            callback=_on_delivery,
        )
    producer.flush()  # block until all in-flight messages are acked
    QUEUE_SIZE.set(len(producer))
    return len(vectors)


def _asdict(v: StateVector) -> dict[str, Any]:
    """Local asdict to avoid importing dataclasses in two places."""
    from dataclasses import asdict
    return asdict(v)
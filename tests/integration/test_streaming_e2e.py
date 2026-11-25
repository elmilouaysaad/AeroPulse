"""End-to-end: produce a message via confluent_kafka, read it back via Spark."""
import json
import uuid

import pytest
from confluent_kafka import Producer
from confluent_kafka.admin import AdminClient, NewTopic

from src.streaming.detector import build_spark

pytestmark = pytest.mark.integration

KAFKA_PKG = "org.apache.spark:spark-sql-kafka-0-10_2.12:3.5.3"


@pytest.fixture
def topic(bootstrap_servers):
    name = f"test_spark_{uuid.uuid4().hex[:8]}"
    admin = AdminClient({"bootstrap.servers": bootstrap_servers})
    for fut in admin.create_topics(
        [NewTopic(name, num_partitions=3, replication_factor=1)]
    ).values():
        fut.result(timeout=15)
    return name


def _produce(bootstrap, topic, key, value):
    p = Producer({"bootstrap.servers": bootstrap})
    p.produce(topic=topic, key=key, value=value)
    p.flush(10)


def test_spark_reads_produced_message(bootstrap_servers, topic):
    payload = json.dumps({"hex": "abc123", "squawk": "7700"}).encode()
    _produce(bootstrap_servers, topic, b"abc123", payload)

    spark = build_spark(kafka_package=KAFKA_PKG)
    df = (
        spark.read.format("kafka")
        .option("kafka.bootstrap.servers", bootstrap_servers)
        .option("subscribe", topic)
        .option("startingOffsets", "earliest")
        .option("endingOffsets", "latest")
        .load()
    )
    rows = df.collect()
    assert len(rows) == 1
    assert rows[0]["key"] == b"abc123"
    assert json.loads(rows[0]["value"])["squawk"] == "7700"
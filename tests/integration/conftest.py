import uuid

# import pytest
from confluent_kafka.admin import AdminClient, NewTopic

from src.ingestion import producer as producer_mod

from testcontainers.community.kafka import KafkaContainer


import os
import pytest


def pytest_configure(config):
    """Integration tests run on the host, so DB access must go through
    localhost (the compose port mapping), not the compose-internal
    service name 'postgres'. Set the env var here so every test that
    imports src.ai.db gets the right DSN."""
    os.environ.setdefault(
        "POSTGRES_DSN",
        "postgresql://aeropulse:aeropulse@localhost:5432/aeropulse",
    )



@pytest.fixture(scope="session")
def kafka_container():
    with KafkaContainer("confluentinc/cp-kafka:7.6.0") as kafka:
        yield kafka


@pytest.fixture
def bootstrap_servers(kafka_container):
    return kafka_container.get_bootstrap_server()


@pytest.fixture
def unique_topic(bootstrap_servers):
    """
    Create a fresh topic per test with 3 partitions. Explicit creation
    (rather than relying on auto-create) guarantees the partition count
    needed for the partitioning tests.
    """
    topic = f"test_aircraft_{uuid.uuid4().hex[:8]}"
    admin = AdminClient({"bootstrap.servers": bootstrap_servers})
    futures = admin.create_topics(
        [NewTopic(topic, num_partitions=3, replication_factor=1)]
    )
    for future in futures.values():
        future.result(timeout=15)
    return topic


@pytest.fixture
def producer_env(monkeypatch, bootstrap_servers, unique_topic):
    """Point the producer module at the test container and test topic."""
    monkeypatch.setattr(producer_mod, "BOOTSTRAP", bootstrap_servers)
    monkeypatch.setattr(producer_mod, "TOPIC", unique_topic)
    return {"bootstrap": bootstrap_servers, "topic": unique_topic}
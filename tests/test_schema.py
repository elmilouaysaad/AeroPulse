"""Verify the Kafka value schema matches the producer's StateVector dataclass."""
from dataclasses import fields

import pytest
from pyspark.sql.types import StringType, DoubleType, BooleanType

from src.ingestion.parser import StateVector
from src.streaming.schema import STATE_VECTOR_SCHEMA


def test_field_names_match_statevector():
    schema_names = {f.name for f in STATE_VECTOR_SCHEMA.fields}
    dataclass_names = {f.name for f in fields(StateVector)}
    missing = dataclass_names - schema_names
    extra = schema_names - dataclass_names
    assert not missing, f"StateVector fields missing from schema: {missing}"
    assert not extra, f"Schema has fields not in StateVector: {extra}"


@pytest.mark.parametrize("field_name,expected_type", [
    ("hex", StringType),
    ("flight", StringType),
    ("lat", DoubleType),
    ("lon", DoubleType),
    ("alt_baro_ft", DoubleType),
    ("gs_kts", DoubleType),
    ("track_deg", DoubleType),
    ("squawk", StringType),
    ("seen_sec", DoubleType),
    ("seen_pos_sec", DoubleType),
    ("on_ground", BooleanType),
])
def test_field_types(field_name, expected_type):
    type_map = {f.name: f.dataType for f in STATE_VECTOR_SCHEMA.fields}
    assert isinstance(type_map[field_name], expected_type)


def test_hex_is_not_nullable():
    """hex is the partitioning key and the stateful group key — it must be required."""
    hex_field = next(f for f in STATE_VECTOR_SCHEMA.fields if f.name == "hex")
    assert hex_field.nullable is False
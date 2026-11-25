"""Explicit schema for the Kafka value produced by src.ingestion.producer."""
from pyspark.sql.types import (
    StructType, StructField, StringType, DoubleType, BooleanType,
)

STATE_VECTOR_SCHEMA = StructType([
    StructField("hex", StringType(), nullable=False),
    StructField("flight", StringType(), nullable=True),
    StructField("lat", DoubleType(), nullable=True),
    StructField("lon", DoubleType(), nullable=True),
    StructField("alt_baro_ft", DoubleType(), nullable=True),
    StructField("gs_kts", DoubleType(), nullable=True),
    StructField("track_deg", DoubleType(), nullable=True),
    StructField("squawk", StringType(), nullable=True),
    StructField("seen_sec", DoubleType(), nullable=False),
    StructField("seen_pos_sec", DoubleType(), nullable=True),
    StructField("on_ground", BooleanType(), nullable=False),
])
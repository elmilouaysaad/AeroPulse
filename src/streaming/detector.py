"""Week 4: Spark Structured Streaming consumer with JDBC idempotent sink."""
from __future__ import annotations

import argparse
import os

import psycopg
from pyspark.sql import SparkSession
from pyspark.sql import functions as F
from pyspark.sql.streaming.state import GroupStateTimeout

from src.streaming.schema import STATE_VECTOR_SCHEMA
from src.streaming.state import detect_anomalies, OUTPUT_SCHEMA, STATE_SCHEMA

KAFKA_BOOTSTRAP = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")
TOPIC = os.getenv("KAFKA_TOPIC", "aircraft_state")
CHECKPOINT = os.getenv("SPARK_CHECKPOINT", "/tmp/checkpoints/detector")


def build_spark(kafka_package: str | None = None) -> SparkSession:
    b = (
        SparkSession.builder
        .appName("aeropulse-detector")
        .config("spark.sql.shuffle.partitions", "6")
        .config(
            "spark.sql.streaming.stateStore.providerClass",
            "org.apache.spark.sql.execution.streaming.state.RocksDBStateStoreProvider",
        )
    )
    if kafka_package:
        b = b.config("spark.jars.packages", kafka_package)
    return b.getOrCreate()


def _jdbc_dsn(url: str) -> str:
    """Convert jdbc:postgresql://host:port/db to a psycopg DSN."""
    return url.replace("jdbc:", "")


def _merge_staging_to_anomalies(jdbc_url: str) -> None:
    """
    Merge anomalies_staging into anomalies with deduplication.

    Spark's JDBC writer emits plain INSERTs, which have no conflict clause.
    Writing to a staging table first, then running INSERT ... ON CONFLICT
    DO NOTHING, gives idempotent writes without needing a custom dialect.

    Why this is necessary: Spark's checkpoint tracks Kafka offsets and
    state, but the JDBC sink is at-least-once. If the executor dies after
    committing 4,999 of 5,000 rows, the batch is replayed and all rows are
    re-emitted. The primary key (hex, anomaly_type, detected_at_ms) makes
    every replayed row a no-op.
    """
    user = os.getenv("POSTGRES_USER", "aeropulse")
    password = os.getenv("POSTGRES_PASSWORD", "aeropulse")
    sql = """
        INSERT INTO anomalies
            (batch_id, hex, flight, anomaly_type, detected_at_ms,
             lat, lon, alt_baro_ft, details,
             severity, phase, rate_fpm, turn_rate_dps)
        SELECT batch_id, hex, flight, anomaly_type, detected_at_ms,
               lat, lon, alt_baro_ft, details,
               COALESCE(severity, 'INFO'), phase, rate_fpm, turn_rate_dps
        FROM anomalies_staging
        ON CONFLICT (hex, anomaly_type, detected_at_ms) DO NOTHING
    """
    with psycopg.connect(
        _jdbc_dsn(jdbc_url), user=user, password=password
    ) as conn, conn.cursor() as cur:
        cur.execute(sql)
        conn.commit()


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--sink", choices=["console", "jdbc"], default="console")
    p.add_argument("--jdbc-url", default=None)
    args = p.parse_args()

    spark = build_spark()

    raw = (
        spark.readStream
        .format("kafka")
        .option("kafka.bootstrap.servers", KAFKA_BOOTSTRAP)
        .option("subscribe", TOPIC)
        .option("startingOffsets", "earliest")
        .option("minPartitions", "6")
        .option("failOnDataLoss", "false")
        .option("kafka.request.timeout.ms", "30000")
        .option("kafka.default.api.timeout.ms", "60000")
        .option("kafka.metadata.max.age.ms", "30000")
        .option("kafka.retry.backoff.ms", "1000")
        .load()
    )

    parsed = (
        raw
        .select(
            F.from_json(F.col("value").cast("string"), STATE_VECTOR_SCHEMA).alias("v"),
            F.col("timestamp").alias("kafka_ts"),
        )
        .select("v.*", "kafka_ts")
        .withColumn("event_time", F.col("kafka_ts"))
        .withWatermark("event_time", "2 minutes")
    )

    alerts = (
        parsed
        .groupBy("hex")
        .applyInPandasWithState(
            detect_anomalies,
            outputStructType=OUTPUT_SCHEMA,
            stateStructType=STATE_SCHEMA,
            outputMode="append",
            timeoutConf=GroupStateTimeout.NoTimeout,
        )
    )

    writer = (
        alerts.writeStream
        .outputMode("append")
        .option("checkpointLocation", CHECKPOINT)
        .trigger(processingTime="10 seconds")
    )

    if args.sink == "console":
        query = writer.format("console").option("truncate", "false").start()
    else:
        if not args.jdbc_url:
            raise SystemExit("--jdbc-url required for --sink jdbc")

        def write_batch(batch_df, batch_id):
            if batch_df.count() == 0:
                return
            user = os.getenv("POSTGRES_USER", "aeropulse")
            password = os.getenv("POSTGRES_PASSWORD", "aeropulse")
            (
                batch_df.withColumn("batch_id", F.lit(batch_id))
                .write
                .format("jdbc")
                .option("url", args.jdbc_url)
                .option("dbtable", "anomalies_staging")
                .option("user", user)
                .option("password", password)
                .option("driver", "org.postgresql.Driver")
                .option("truncate", "true")
                .mode("overwrite")
                .save()
            )
            _merge_staging_to_anomalies(args.jdbc_url)

        query = writer.foreachBatch(write_batch).start()

    query.awaitTermination()


if __name__ == "__main__":
    main()